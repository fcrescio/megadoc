from __future__ import annotations

import re
import unicodedata
from html.parser import HTMLParser
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
    accounts = _extract_accounts(tables, period_from, period_to)

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
        "accounts": accounts,
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
    extracted: list[dict[str, Any]] = []
    for index, table in enumerate(_iter_structured_tables(structured_json), start=1):
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


def _iter_structured_tables(structured_json: dict[str, Any]) -> list[dict[str, Any]]:
    """Return tables from both Docling top-level output and dots-native page output."""
    tables: list[dict[str, Any]] = []

    raw_tables = structured_json.get("tables")
    if isinstance(raw_tables, list):
        tables.extend(table for table in raw_tables if isinstance(table, dict))

    pages = structured_json.get("pages")
    if isinstance(pages, list):
        for page in pages:
            if not isinstance(page, dict):
                continue
            page_number = page.get("page_number") or page.get("page_no")
            page_tables = page.get("tables")
            if not isinstance(page_tables, list):
                continue
            for table in page_tables:
                if not isinstance(table, dict):
                    continue
                if page_number is not None and table.get("page_number") is None:
                    table = {**table, "page_number": page_number}
                tables.append(table)

    return tables


def _table_overlaps_document_unit(table: dict[str, Any], start_page: int, end_page: int) -> bool:
    page_number = table.get("page_number") or table.get("page_no")
    if isinstance(page_number, int):
        return start_page <= page_number <= end_page

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
    html = _table_html(table)
    if html:
        return _parse_html_table(html)

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


def _table_html(table: dict[str, Any]) -> str | None:
    cells = table.get("cells")
    if not isinstance(cells, list):
        return None
    html_parts: list[str] = []
    for cell in cells:
        if not isinstance(cell, dict):
            continue
        html = cell.get("html")
        if isinstance(html, str) and html.strip():
            html_parts.append(html)
    if not html_parts:
        return None
    return "\n".join(html_parts)


def _parse_html_table(html: str) -> tuple[list[str], list[dict[str, Any]], list[list[str]]] | None:
    parser = _HTMLTableParser()
    parser.feed(html)
    grid = parser.rows
    if not grid:
        return None

    max_cols = max(len(row) for row in grid)
    if max_cols <= 0:
        return None
    normalized_grid = [row + [""] * (max_cols - len(row)) for row in grid]
    header_rows = _infer_html_header_rows(normalized_grid, parser.header_row_indexes)
    raw_headers = _build_raw_headers(normalized_grid, header_rows, max_cols)
    headers = _make_unique_headers(raw_headers)

    rows: list[dict[str, Any]] = []
    for row_cells in normalized_grid[header_rows:]:
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


def _infer_html_header_rows(grid: list[list[str]], explicit_header_rows: set[int]) -> int:
    if explicit_header_rows:
        return max(explicit_header_rows) + 1
    if len(grid) <= 1:
        return 0

    first_row = grid[0]
    numeric_cells = sum(1 for cell in first_row if _parse_amount(cell) is not None)
    text_cells = sum(1 for cell in first_row if cell.strip())
    if text_cells and numeric_cells == 0:
        return 1
    return 0


class _HTMLTableParser(HTMLParser):
    """Small HTML table parser for OCR-produced table snippets."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self.header_row_indexes: set[int] = set()
        self._current_row: list[str] | None = None
        self._current_cell: list[str] | None = None
        self._current_cell_is_header = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self._current_row = []
        elif tag in {"td", "th"} and self._current_row is not None:
            self._current_cell = []
            self._current_cell_is_header = tag == "th"

    def handle_data(self, data: str) -> None:
        if self._current_cell is not None:
            self._current_cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._current_row is not None and self._current_cell is not None:
            value = re.sub(r"\s+", " ", "".join(self._current_cell)).strip()
            self._current_row.append(value)
            if self._current_cell_is_header:
                self.header_row_indexes.add(len(self.rows))
            self._current_cell = None
            self._current_cell_is_header = False
        elif tag == "tr" and self._current_row is not None:
            if any(cell.strip() for cell in self._current_row):
                self.rows.append(self._current_row)
            self._current_row = None


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
        labelled_amount = _last_amount(row["normalized_amounts"])
        if labelled_amount is not None:
            if "totale gestione" in marker:
                totals["Totale gestione"] = labelled_amount
            elif "saldo finale" in marker:
                totals["Saldo finale"] = labelled_amount
            elif "totale dovuto" in marker:
                totals["Totale dovuto"] = labelled_amount
            elif "totale" in marker:
                totals["Totale"] = labelled_amount
        for header, amount in row["normalized_amounts"].items():
            totals[header] = amount
    return totals


def _last_amount(amounts: dict[str, float]) -> float | None:
    if not amounts:
        return None
    return list(amounts.values())[-1]


def _build_validation_checks(tables: list[dict[str, Any]]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    summary_totals: list[float] = []
    payment_schedule_totals: list[float] = []

    for table in tables:
        if table["table_type"] not in {"summary", "balance"}:
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
        totals = table.get("totals", {})
        if not totals:
            continue
        largest_total = max(totals.values(), key=lambda value: abs(value))
        checks.append(
            {
                "check_type": "allocation_totals_extracted",
                "status": "pass",
                "details": f"Estratti totali dalla tabella di riparto; totale principale={largest_total:.2f}",
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


def _extract_accounts(
    tables: list[dict[str, Any]],
    period_from: str | None,
    period_to: str | None,
) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    alias_counts: dict[str, dict[str, int]] = {}

    for table in tables:
        if (
            table.get("table_type") not in {"expense_allocation", "payment_schedule"}
            and not _is_payment_ledger(table)
        ):
            continue
        rows = table.get("rows")
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            identity = _extract_account_identity(row)
            if identity is None:
                continue
            unit_code, subject_label = identity
            account_key = _normalize_key(unit_code)
            account = grouped.setdefault(
                account_key,
                {
                    "account_key": account_key,
                    "unit_code": unit_code,
                    "subject_label": subject_label,
                    "subject_aliases": [],
                    "facts": [],
                },
            )
            aliases = alias_counts.setdefault(account_key, {})
            aliases[subject_label] = aliases.get(subject_label, 0) + 1
            account["facts"].extend(
                _extract_row_facts(
                    table,
                    row,
                    period_from=period_from,
                    period_to=period_to,
                )
            )

    accounts: list[dict[str, Any]] = []
    for account_key, account in grouped.items():
        aliases = alias_counts[account_key]
        account["subject_label"] = max(aliases, key=lambda value: (aliases[value], len(value), value))
        account["subject_aliases"] = sorted(aliases)
        if account["facts"]:
            accounts.append(account)
    return sorted(accounts, key=lambda account: (account["unit_code"], account["subject_label"]))


def _extract_account_identity(row: dict[str, Any]) -> tuple[str, str] | None:
    cells = row.get("cells")
    if not isinstance(cells, dict):
        return None
    textual_cells = {
        str(header): str(value).strip()
        for header, value in cells.items()
        if isinstance(value, str) and value.strip()
    }

    for header, value in textual_cells.items():
        if any(token in header.lower() for token in ("nominativo", "condomino", "proprietario")):
            parsed = _parse_name_and_unit(value)
            if parsed is not None:
                return parsed

    for value in textual_cells.values():
        parsed = _parse_prefixed_account(value)
        if parsed is not None:
            return parsed

    unit_code = next(
        (
            match.group(1).upper().replace(" ", "")
            for value in textual_cells.values()
            if (
                match := re.fullmatch(
                    r"\s*([A-Z]{1,2}\s*\d{1,3})(?:\s*\([^)]*\))?\s*",
                    value,
                    re.IGNORECASE,
                )
            )
        ),
        None,
    )
    if unit_code is None:
        return None
    subject = next(
        (
            value
            for value in textual_cells.values()
            if _looks_like_subject(value) and unit_code.lower() not in value.lower()
        ),
        None,
    )
    if subject is None:
        return None
    return unit_code, subject


def _parse_name_and_unit(value: str) -> tuple[str, str] | None:
    parenthesized = re.match(r"^\s*(.+?)\s*\(([A-Z]{1,2}\s*\d{1,3})\)\s*$", value, re.IGNORECASE)
    if parenthesized and _looks_like_subject(parenthesized.group(1)):
        return parenthesized.group(2).upper().replace(" ", ""), parenthesized.group(1).strip()
    return _parse_prefixed_account(value)


def _parse_prefixed_account(value: str) -> tuple[str, str] | None:
    match = re.match(
        r"^\s*-?\s*([A-Z]{1,2}\s*\d{1,3})\s+([A-ZÀ-ÖØ-Ý' ]{3,60}?)(?:\s+-|$)",
        value,
        re.IGNORECASE,
    )
    if match is None:
        return None
    subject = re.sub(r"\s+", " ", match.group(2)).strip()
    if not _looks_like_subject(subject):
        return None
    return match.group(1).upper().replace(" ", ""), subject


def _looks_like_subject(value: str) -> bool:
    lowered = value.lower()
    if len(value) > 72 or any(token in lowered for token in ("fatt.", "rata ", "totale", "saldo", "euro")):
        return False
    words = re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿ']+", value)
    return len(words) >= 2


def _is_payment_ledger(table: dict[str, Any]) -> bool:
    headers = {
        str(header).lower()
        for row in table.get("rows", [])
        if isinstance(row, dict)
        for header in (row.get("cells") or {}).keys()
    }
    return {"nominativo", "importo"}.issubset(headers) and any("data pag" in header for header in headers)


def _extract_row_facts(
    table: dict[str, Any],
    row: dict[str, Any],
    *,
    period_from: str | None,
    period_to: str | None,
) -> list[dict[str, Any]]:
    amounts = row.get("normalized_amounts")
    cells = row.get("cells")
    if not isinstance(amounts, dict) or not isinstance(cells, dict):
        return []
    payment_ledger = _is_payment_ledger(table)
    facts: list[dict[str, Any]] = []
    for column, raw_amount in amounts.items():
        if not isinstance(raw_amount, (int, float)):
            continue
        fact_type, category_label, is_total = _classify_fact_column(
            str(column),
            table_type=str(table.get("table_type") or "unknown"),
            payment_ledger=payment_ledger,
        )
        if fact_type is None:
            continue
        amount = float(raw_amount)
        normalized_amount = (
            abs(amount)
            if fact_type
            in {
                "allocated_expense",
                "personal_charge",
                "amount_due",
                "payment_received",
                "budgeted_expense",
                "reimbursement",
                "installment_due",
            }
            else amount
        )
        facts.append(
            {
                "fact_type": fact_type,
                "category_key": _normalize_key(category_label) if category_label else None,
                "category_label": category_label,
                "amount": normalized_amount,
                "raw_amount": amount,
                "currency": "EUR",
                "period_context": {
                    "from": period_from,
                    "to": period_to,
                    "source": "document_unit",
                    "review_status": "unverified",
                },
                "is_total": is_total,
                "evidence": {
                    "table_id": table.get("table_id"),
                    "table_type": table.get("table_type"),
                    "row_id": row.get("row_id"),
                    "column": column,
                    "raw_value": cells.get(column),
                },
            }
        )
    return facts


def _classify_fact_column(
    column: str,
    *,
    table_type: str,
    payment_ledger: bool,
) -> tuple[str | None, str | None, bool]:
    lowered = column.lower()
    if "mill" in lowered or re.fullmatch(r"column_\d+", lowered):
        return None, None, False
    if payment_ledger and lowered == "importo":
        return "payment_received", None, False
    if "totale dovuto" in lowered:
        return "amount_due", None, True
    if "totale preventivo" in lowered:
        return "budgeted_expense", None, True
    if "rata n." in lowered:
        return "installment_due", column, False
    if "quote a rimborso" in lowered:
        return "reimbursement", None, False
    if "rate versate" in lowered:
        return "payment_received", None, True
    if "saldo finale" in lowered:
        return "closing_balance", None, True
    if "saldi di fine" in lowered or "saldo iniziale" in lowered:
        return "opening_balance", None, True
    if "totale gestione" in lowered or lowered == "totale":
        return "allocated_expense", "Totale gestione", True
    if table_type == "expense_allocation" and lowered == "importo":
        return "personal_charge", None, False
    if table_type == "expense_allocation":
        return "allocated_expense", column, False
    return None, None, False


def _normalize_key(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.strip().lower())
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "_", ascii_value).strip("_") or "unknown"


def _pick_amount_by_header(amounts: dict[str, float], header_hints: list[str]) -> float | None:
    normalized_amounts = {header.strip().lower(): amount for header, amount in amounts.items()}
    for hint in header_hints:
        amount = normalized_amounts.get(hint.strip().lower())
        if amount is not None:
            return amount
    for hint in header_hints:
        for header, amount in amounts.items():
            if hint.lower() in header.lower():
                return amount
    return None
