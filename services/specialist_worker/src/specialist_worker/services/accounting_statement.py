from __future__ import annotations

import re
from typing import Any

from common.db.models import DocumentUnit


def process_accounting_statement(
    document_unit: DocumentUnit,
    segment_text: str,
    input_version: str,
) -> tuple[dict[str, Any], float]:
    text = segment_text or ""
    statement_type = _statement_type(text)
    period_from, period_to = _extract_period(text)
    tables = _extract_markdown_tables(text)
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
    confidence = min(confidence, 0.95)

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
            }
        )
    return tables


def _parse_table_block(block: list[str]) -> tuple[list[str], list[dict[str, Any]]] | None:
    if len(block) < 2:
        return None
    raw_rows = [_split_row(line) for line in block]
    if len(raw_rows) < 2 or not raw_rows[0]:
        return None
    headers = raw_rows[0]
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
    parts = [part.strip() for part in line.strip().strip("|").split("|")]
    return parts


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
    if "rata n." in joined_headers or "totale dovuto" in joined_headers:
        return "payment_schedule"
    if "totale gestione" in joined_headers or "saldo finale" in joined_headers:
        return "summary"
    if "palazzina" in joined_headers or "appartamento" in joined_headers or "totale gestione" in joined_headers:
        return "expense_allocation"
    if "importi" in joined_headers or "totali" in joined_headers:
        return "summary"
    if any("saldo" in " ".join(row["cells"].values()).lower() for row in rows):
        return "balance"
    return "unknown"


def _extract_table_totals(headers: list[str], rows: list[dict[str, Any]]) -> dict[str, float]:
    totals: dict[str, float] = {}
    for row in rows:
        first_cell = next(iter(row["cells"].values()), "").lower()
        if "totale" not in first_cell and "saldo finale" not in first_cell:
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
        total_gestione = totals.get("Totale gestione")
        saldo_finale = totals.get("Saldo finale (Euro)")
        generic_total = totals.get("Totali") or totals.get("Totale")
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
            first_cell = next(iter(row["cells"].values()), "").lower()
            amount = row["normalized_amounts"].get("Totale") or row["normalized_amounts"].get("Totale gestione")
            if amount is None:
                continue
            if "totale" in first_cell:
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
            first_values = [str(value).lower() for value in row["cells"].values() if value]
            if not any("totale" in value for value in first_values):
                continue
            amounts = row["normalized_amounts"]
            total_row = amounts.get("Totale dovuto")
            installment_columns = [amount for key, amount in amounts.items() if "Rata n." in key]
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
