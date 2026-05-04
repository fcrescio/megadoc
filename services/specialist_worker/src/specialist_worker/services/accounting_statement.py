from __future__ import annotations

import re
from typing import Any

from common.db.models import DocumentUnit


def process_accounting_statement(
    document_unit: DocumentUnit,
    segment_text: str,
    input_version: str,
    structured_json: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], float]:
    text = segment_text or ""
    statement_type = _statement_type(text)
    period_from, period_to = _extract_period(text)
    tables = _extract_structured_tables(document_unit, structured_json or {}) or _extract_markdown_tables(text)
    validation_checks = _build_validation_checks(tables)

    confidence = 0.45
    if tables:
        confidence += 0.20
    if period_from or period_to:
        confidence += 0.10
    if any(check["status"] != "unknown" for check in validation_checks):
        confidence += 0.10
    if statement_type != "unknown":
        confidence += 0.10
    if any(table.get("source") == "docling_structured" for table in tables):
        confidence += 0.05
    confidence = min(confidence, 0.97)

    result = {
        "document_kind": "accounting_statement",
        "input_version": input_version,
        "statement_type": statement_type,
        "accounting_period_from": period_from,
        "accounting_period_to": period_to,
        "currency": "EUR",
        "tables": tables,
        "validation_checks": validation_checks,
    }
    return result, confidence


def _statement_type(text: str) -> str:
    lowered = text.lower()
    if "bilancio preventivo" in lowered:
        return "bilancio_preventivo"
    if "preventivo ripartizioni" in lowered or "ripartizioni per unità" in lowered:
        return "riparto_spese"
    if "riparto" in lowered:
        return "riparto_spese"
    if "rendiconto" in lowered:
        return "rendiconto"
    if "estratto contabile" in lowered:
        return "estratto_contabile"
    return "unknown"


def _extract_period(text: str) -> tuple[str | None, str | None]:
    match = re.search(r"Periodo:\s*(\d{1,2}/\d{1,2}/\d{2,4})\s*-\s*(\d{1,2}/\d{1,2}/\d{2,4})", text)
    if not match:
        return None, None
    return _normalize_date(match.group(1)), _normalize_date(match.group(2))


def _normalize_date(value: str) -> str:
    day, month, year = re.split(r"[/-]", value)
    if len(year) == 2:
        year = f"20{year}" if int(year) < 50 else f"19{year}"
    return f"{year}-{month.zfill(2)}-{day.zfill(2)}"


def _extract_structured_tables(document_unit: DocumentUnit, structured_json: dict[str, Any]) -> list[dict[str, Any]]:
    raw_tables = structured_json.get("tables")
    if not isinstance(raw_tables, list):
        return []

    extracted: list[dict[str, Any]] = []
    for index, table in enumerate(raw_tables, start=1):
        if not isinstance(table, dict):
            continue
        if not _table_overlaps_document_unit(table, document_unit.start_page, document_unit.end_page):
            continue
        parsed = _parse_structured_table(table)
        if parsed is None:
            continue
        headers, rows, raw_headers = parsed
        extracted.append(
            {
                "table_id": table.get("self_ref", f"table_{index}").split("/")[-1] or f"table_{index}",
                "table_type": _classify_table(headers, rows),
                "headers": headers,
                "raw_headers": raw_headers,
                "rows": rows,
                "totals": _extract_table_totals(headers, rows),
                "source": "docling_structured",
            }
        )
    return extracted


def _table_overlaps_document_unit(table: dict[str, Any], start_page: int, end_page: int) -> bool:
    prov = table.get("prov")
    if not isinstance(prov, list):
        return True
    pages = {
        item.get("page_no")
        for item in prov
        if isinstance(item, dict) and isinstance(item.get("page_no"), int)
    }
    if not pages:
        return True
    return any(start_page <= page <= end_page for page in pages)


def _parse_structured_table(table: dict[str, Any]) -> tuple[list[str], list[dict[str, Any]], list[list[str]]] | None:
    data = table.get("data")
    if not isinstance(data, dict):
        return None
    cell_defs = data.get("table_cells")
    num_rows = data.get("num_rows")
    num_cols = data.get("num_cols")
    if not isinstance(cell_defs, list) or not isinstance(num_rows, int) or not isinstance(num_cols, int):
        return None

    grid = [["" for _ in range(num_cols)] for _ in range(num_rows)]
    column_header_rows = 0
    first_data_row = num_rows
    for cell in cell_defs:
        if not isinstance(cell, dict):
            continue
        row_start = int(cell.get("start_row_offset_idx", 0))
        row_end = int(cell.get("end_row_offset_idx", row_start + 1))
        col_start = int(cell.get("start_col_offset_idx", 0))
        col_end = int(cell.get("end_col_offset_idx", col_start + 1))
        text = str(cell.get("text", "")).strip()
        if cell.get("column_header"):
            column_header_rows = max(column_header_rows, row_end)
        if cell.get("row_header") and row_start < first_data_row:
            first_data_row = row_start
        for row_idx in range(row_start, min(row_end, num_rows)):
            for col_idx in range(col_start, min(col_end, num_cols)):
                if text and not grid[row_idx][col_idx]:
                    grid[row_idx][col_idx] = text

    if first_data_row == num_rows:
        first_data_row = 1 if num_rows > 1 else 0
    header_rows = max(column_header_rows, first_data_row)
    raw_headers = _build_raw_headers(grid, header_rows, num_cols)
    headers = _make_unique_headers(raw_headers)

    rows: list[dict[str, Any]] = []
    for row_idx in range(header_rows, num_rows):
        row_cells = grid[row_idx]
        if not any(cell.strip() for cell in row_cells):
            continue
        cells: dict[str, str] = {}
        normalized_amounts: dict[str, float] = {}
        for col_idx, header in enumerate(headers):
            value = row_cells[col_idx].strip()
            cells[header] = value
            amount = _parse_amount(value)
            if amount is not None:
                normalized_amounts[header] = amount
        rows.append(
            {
                "row_id": f"row_{len(rows) + 1}",
                "cells": cells,
                "normalized_amounts": normalized_amounts,
            }
        )
    if not rows:
        return None
    return headers, rows, raw_headers


def _build_raw_headers(grid: list[list[str]], header_rows: int, num_cols: int) -> list[list[str]]:
    raw_headers: list[list[str]] = []
    for col_idx in range(num_cols):
        parts: list[str] = []
        for row_idx in range(header_rows):
            value = grid[row_idx][col_idx].strip()
            if value and (not parts or parts[-1] != value):
                parts.append(value)
        if not parts:
            parts.append(f"column_{col_idx + 1}")
        raw_headers.append(parts)
    return raw_headers


def _make_unique_headers(raw_headers: list[list[str]]) -> list[str]:
    semantic_suffix = {
        0: "unita",
        1: "categoria",
    }
    headers: list[str] = []
    seen: dict[str, int] = {}
    for col_idx, parts in enumerate(raw_headers):
        base = " / ".join(parts)
        if not base:
            base = f"column_{col_idx + 1}"
        count = seen.get(base, 0)
        seen[base] = count + 1
        if count == 0:
            header = base
        else:
            suffix = semantic_suffix.get(count, str(count + 1))
            header = f"{base} / {suffix}"
        headers.append(header)
    return headers


def _extract_markdown_tables(text: str) -> list[dict[str, Any]]:
    lines = text.splitlines()
    blocks: list[list[str]] = []
    current: list[str] = []
    for line in lines:
        if line.count("|") >= 2:
            current.append(line)
        else:
            if current:
                blocks.append(current)
                current = []
    if current:
        blocks.append(current)

    tables: list[dict[str, Any]] = []
    for index, block in enumerate(blocks, start=1):
        parsed = _parse_table_block(block)
        if parsed is None:
            continue
        headers, rows = parsed
        tables.append(
            {
                "table_id": f"table_{index}",
                "table_type": _classify_table(headers, rows),
                "headers": headers,
                "rows": rows,
                "totals": _extract_table_totals(headers, rows),
                "source": "markdown_fallback",
            }
        )
    return tables


def _parse_table_block(block: list[str]) -> tuple[list[str], list[dict[str, Any]]] | None:
    if len(block) < 2:
        return None
    raw_rows = [_split_row(line) for line in block]
    if len(raw_rows) < 2 or not raw_rows[0]:
        return None
    headers = _make_unique_headers([[header] for header in raw_rows[0]])
    data_rows = []
    for raw in raw_rows[2:]:
        if not any(cell.strip() for cell in raw):
            continue
        cells = {}
        normalized_amounts = {}
        for idx, header in enumerate(headers):
            value = raw[idx] if idx < len(raw) else ""
            cells[header] = value
            amount = _parse_amount(value)
            if amount is not None:
                normalized_amounts[header] = amount
        data_rows.append(
            {
                "row_id": f"row_{len(data_rows) + 1}",
                "cells": cells,
                "normalized_amounts": normalized_amounts,
            }
        )
    if not data_rows:
        return None
    return headers, data_rows


def _split_row(line: str) -> list[str]:
    return [part.strip() for part in line.strip().strip("|").split("|")]


def _parse_amount(value: str | None) -> float | None:
    if not value:
        return None
    compact = value.replace("€", "").replace(" ", "")
    if not re.fullmatch(r"-?\d{1,3}(?:\.\d{3})*(?:,\d+)?|-?\d+(?:,\d+)?", compact):
        return None
    normalized = compact.replace(".", "").replace(",", ".")
    try:
        return float(normalized)
    except ValueError:
        return None


def _classify_table(headers: list[str], rows: list[dict[str, Any]]) -> str:
    joined_headers = " ".join(headers).lower()
    sample_values = " ".join(
        value
        for row in rows[:5]
        for value in row["cells"].values()
        if isinstance(value, str)
    ).lower()
    if "rata n." in joined_headers or "totale dovuto" in joined_headers:
        return "payment_schedule"
    if (
        "appartamento" in joined_headers
        or "scala" in joined_headers
        or "unita" in joined_headers
        or "appartamento" in sample_values
        or "postoauto" in sample_values
        or re.search(r"\b[a-d]\d{1,2}\b", sample_values)
    ):
        return "expense_allocation"
    if "totale gestione" in joined_headers or "saldo finale" in joined_headers:
        return "summary"
    if "importi" in joined_headers or "totali" in joined_headers:
        return "summary"
    if any("saldo" in " ".join(row["cells"].values()).lower() for row in rows):
        return "balance"
    return "unknown"


def _extract_table_totals(headers: list[str], rows: list[dict[str, Any]]) -> dict[str, float]:
    totals: dict[str, float] = {}
    for row in rows:
        first_values = [str(value).lower() for value in list(row["cells"].values())[:2] if value]
        marker = " ".join(first_values)
        if "totale" not in marker and "saldo finale" not in marker:
            continue
        for header, amount in row["normalized_amounts"].items():
            totals[header] = amount
    return totals


def _build_validation_checks(tables: list[dict[str, Any]]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    summary_totals: list[float] = []
    payment_schedule_totals: list[float] = []

    for table in tables:
        if table["table_type"] != "summary":
            continue
        totals = table.get("totals", {})
        total_gestione = _pick_amount_by_header(totals, ["Totale gestione"])
        saldo_finale = _pick_amount_by_header(totals, ["Saldo finale (Euro)", "Saldo finale"])
        generic_total = _pick_amount_by_header(totals, ["Totali", "Totale"])
        if total_gestione is not None:
            summary_totals.append(total_gestione)
        if saldo_finale is not None:
            summary_totals.append(saldo_finale)
        if generic_total is not None:
            summary_totals.append(generic_total)
        if total_gestione is not None and saldo_finale is not None:
            status = "pass" if abs(total_gestione - saldo_finale) < 0.01 else "fail"
            checks.append(
                {
                    "check_type": "summary_total_matches_balance",
                    "status": status,
                    "details": f"Totale gestione={total_gestione:.2f}, saldo finale={saldo_finale:.2f}",
                }
            )

    for table in tables:
        if table["table_type"] != "expense_allocation":
            continue
        total_row = None
        value_rows: list[float] = []
        for row in table["rows"]:
            first_values = [str(value).lower() for value in list(row["cells"].values())[:2] if value]
            marker = " ".join(first_values)
            amount = _pick_amount_by_header(row["normalized_amounts"], ["Totale", "Totale gestione"])
            if amount is None:
                continue
            if "totale" in marker:
                total_row = amount
            else:
                value_rows.append(amount)
        if total_row is None or not value_rows:
            continue
        computed = round(sum(value_rows), 2)
        status = "pass" if abs(computed - total_row) < 0.05 else "fail"
        checks.append(
            {
                "check_type": "allocation_rows_sum_to_total",
                "status": status,
                "details": f"Somma righe={computed:.2f}, totale dichiarato={total_row:.2f}",
            }
        )

    for table in tables:
        if table["table_type"] != "payment_schedule":
            continue
        total_row = None
        installment_sum = None
        for row in table["rows"]:
            first_values = [str(value).lower() for value in list(row["cells"].values())[:2] if value]
            if not any("totale" in value for value in first_values):
                continue
            amounts = row["normalized_amounts"]
            total_row = _pick_amount_by_header(amounts, ["Totale dovuto"])
            installment_columns = [
                amount for key, amount in amounts.items() if "Rata n." in key
            ]
            if installment_columns:
                installment_sum = round(sum(installment_columns), 2)
            break
        if total_row is not None and installment_sum is not None:
            payment_schedule_totals.append(total_row)
            status = "pass" if abs(abs(installment_sum) - abs(total_row)) < 0.05 else "fail"
            checks.append(
                {
                    "check_type": "installment_sum_matches_total_due",
                    "status": status,
                    "details": f"Somma rate={installment_sum:.2f}, totale dovuto={total_row:.2f}",
                }
            )

    if summary_totals and payment_schedule_totals:
        summary_total = max(summary_totals, key=lambda value: abs(value))
        payment_total = max(payment_schedule_totals, key=lambda value: abs(value))
        status = "pass" if abs(abs(summary_total) - abs(payment_total)) < 0.05 else "fail"
        checks.append(
            {
                "check_type": "statement_total_matches_payment_schedule",
                "status": status,
                "details": f"Totale statement={summary_total:.2f}, totale piano rate={payment_total:.2f}",
            }
        )

    if not checks:
        checks.append(
            {
                "check_type": "no_numeric_validation_available",
                "status": "unknown",
                "details": "Il parser non ha trovato abbastanza colonne numeriche o righe totale per eseguire verifiche.",
            }
        )
    return checks


def _pick_amount_by_header(amounts: dict[str, float], header_hints: list[str]) -> float | None:
    for hint in header_hints:
        for header, amount in amounts.items():
            if hint.lower() in header.lower():
                return amount
    return None
