"""Agentic accounting table reconstruction.

Replaces the single-shot LLM account extraction with an iterative agent loop
where the LLM drives the reconstruction process using tools to inspect the
document and extract accounts table by table.

Each LLM call is small and focused — one table at a time — so there is no
hard token limit and the LLM can correct itself as it goes.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Literal

from knowledge_classifier.llm.base import ChatMessage, LLMProvider
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Agent action model — flat discriminated union
# ---------------------------------------------------------------------------

class AgentAction(BaseModel):
    """An action the agent can take.

    All fields are optional; the ``action`` discriminator determines which
    subset is populated.
    """
    action: Literal[
        "list_tables",
        "get_table",
        "get_context",
        "get_all_contexts",
        "search",
        "extract_accounts",
        "llm_extract_table",
        "label_categories",
        "review_accounts",
        "finalize",
    ]
    reasoning: str = ""

    # -- get_table / get_context --
    table_index: int | None = None

    # -- get_context --
    before_chars: int | None = None
    after_chars: int | None = None

    # -- search --
    pattern: str | None = None

    # -- extract_accounts (rule-based, one or more tables) --
    table_indices: list[int] | None = None
    category_name: str | None = None

    # -- llm_extract_table (LLM-assisted, single table) --
    llm_table_index: int | None = None
    llm_category_name: str | None = None

    # -- label_categories (LLM-assisted category labeling) --
    label_table_indices: list[int] | None = None

    # -- finalize (just a signal — accounts are accumulated automatically) --
    finalize: bool = False
    confidence: float | None = None


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

def _tool_list_tables(tables: list[dict[str, Any]]) -> str:
    """Return a summary of all available tables."""
    lines: list[str] = []
    for i, t in enumerate(tables):
        tid = t.get("table_id", f"table_{i}")
        ttype = t.get("table_type", "unknown")
        headers = t.get("headers", [])
        row_count = len(t.get("rows", []))
        page = t.get("page_number", "?")
        lines.append(
            f"[{i}] id={tid} type={ttype} page={page} "
            f"headers={headers} rows={row_count}"
        )
    if not lines:
        return "Nessuna tabella disponibile."
    return "\n".join(lines)


def _tool_get_table(tables: list[dict[str, Any]], index: int) -> str:
    """Return full details of a single table."""
    if index < 0 or index >= len(tables):
        return (
            f"Errore: indice tabella {index} non valido. "
            f"Indici disponibili: 0\u2013{len(tables) - 1}"
        )
    t = tables[index]
    lines: list[str] = [
        f"Tabella [{index}]:",
        f"  ID: {t.get('table_id', '?')}",
        f"  Tipo: {t.get('table_type', '?')}",
        f"  Pagina: {t.get('page_number', '?')}",
        f"  Headers: {t.get('headers', [])}",
        f"  Righe totali: {len(t.get('rows', []))}",
    ]
    rows = t.get("rows", [])
    for j, row in enumerate(rows[:8]):
        cells = row.get("cells", {})
        amounts = row.get("normalized_amounts", {})
        lines.append(f"  Riga {j}: cells={dict(cells)} amounts={dict(amounts)}")
    if len(rows) > 8:
        lines.append(f"  ... e altre {len(rows) - 8} righe")
    totals = t.get("totals", {})
    if totals:
        lines.append(f"  Totali: {totals}")
    return "\n".join(lines)


def _tool_get_context(
    text: str,
    tables: list[dict[str, Any]],
    index: int,
    before: int = 600,
    after: int = 300,
) -> str:
    """Return OCR text context around a table.

    Uses unique row values (amounts) to locate the table in the text,
    since headers like "Cod" appear many times and would match the
    wrong occurrence.
    """
    if index < 0 or index >= len(tables):
        return f"Errore: indice tabella {index} non valido."
    t = tables[index]
    rows = t.get("rows", [])

    # Strategy 1: search for a unique amount value from the first data row
    for row in rows[:5]:
        amounts = row.get("normalized_amounts") or {}
        for col, val in amounts.items():
            if isinstance(val, (int, float)) and val > 0:
                # Try both dot and comma as decimal separator
                val_str_dot = f"{val:.2f}"
                val_str_comma = f"{val:.2f}".replace(".", ",")
                for val_str in (val_str_dot, val_str_comma):
                    pos = text.find(val_str)
                    if pos >= 0:
                        start = max(0, pos - before)
                        end = min(len(text), pos + after)
                        ctx = text[start:end]
                        return (
                            f"Contesto attorno alla tabella [{index}] "
                            f"(valore '{val_str}' a posizione {pos}):\n"
                            f"...{ctx}..."
                        )

    # Strategy 2: search for a unique text value from the first column
    for row in rows[:5]:
        cells = row.get("cells") or {}
        for col, val in cells.items():
            if isinstance(val, str) and len(val) > 3 and not val.replace(".", "").replace(",", "").isdigit():
                pos = text.find(val)
                if pos >= 0:
                    start = max(0, pos - before)
                    end = min(len(text), pos + after)
                    ctx = text[start:end]
                    return (
                        f"Contesto attorno alla tabella [{index}] "
                        f"(valore '{val[:40]}' a posizione {pos}):\n"
                        f"...{ctx}..."
                    )

    # Strategy 3: fallback to header search
    headers = t.get("headers", [])
    for header in headers:
        pos = text.find(str(header))
        if pos >= 0:
            start = max(0, pos - before)
            end = min(len(text), pos + after)
            ctx = text[start:end]
            return (
                f"Contesto attorno alla tabella [{index}] "
                f"(header '{header}' a posizione {pos}):\n"
                f"...{ctx}..."
            )

    return f"Impossibile localizzare la tabella [{index}] nel testo OCR."


def _tool_get_all_contexts(
    text: str,
    tables: list[dict[str, Any]],
    *,
    before: int = 600,
    after: int = 300,
) -> str:
    """Return OCR context for ALL expense_allocation tables in one call.

    This is more efficient than calling get_context for each table individually.
    The LLM can use this to find category names for all tables at once.
    """
    allocation_indices = [
        i for i, t in enumerate(tables)
        if t.get("table_type") == "expense_allocation"
    ]
    if not allocation_indices:
        return "Nessuna tabella expense_allocation trovata."

    lines: list[str] = [
        f"Contesto per {len(allocation_indices)} tabelle expense_allocation:\n"
    ]
    for idx in allocation_indices:
        ctx = _tool_get_context(text, tables, idx, before=before, after=after)
        lines.append(f"--- Tabella [{idx}] ---\n{ctx}\n")

    return "\n".join(lines)


def _tool_search(text: str, pattern: str) -> str:
    """Search for a pattern in the OCR text."""
    try:
        matches = list(re.finditer(pattern, text, re.IGNORECASE))
    except re.error:
        matches = list(re.finditer(re.escape(pattern), text, re.IGNORECASE))

    if not matches:
        return f"Nessuna occorrenza trovata per '{pattern}'."

    snippets: list[str] = []
    for m in matches[:8]:
        start = max(0, m.start() - 120)
        end = min(len(text), m.end() + 120)
        ctx = text[start:end]
        snippets.append(f"...{ctx}...")
    if len(matches) > 8:
        snippets.append(f"... e altre {len(matches) - 8} occorrenze")
    return "\n\n".join(snippets)


def _tool_extract_accounts(
    text: str,
    tables: list[dict[str, Any]],
    indices: list[int],
    period_from: str | None,
    period_to: str | None,
    category_name: str | None = None,
) -> str:
    """Extract accounts from selected tables using the rule-based parser.

    If *category_name* is provided, it is set as ``_category_label`` on each
    selected table so that ``_derive_table_category`` returns it and the
    extracted facts carry the correct category label.
    """
    selected = [tables[i] for i in indices if 0 <= i < len(tables)]
    if not selected:
        return "Nessuna tabella valida selezionata."

    # Apply category override so _derive_table_category picks it up
    if category_name:
        for t in selected:
            t["_category_label"] = category_name

    from specialist_worker.services.accounting_statement import _extract_accounts
    accounts = _extract_accounts(selected, period_from, period_to)

    if not accounts:
        return (
            f"Nessun account estratto dalle tabelle {indices}. "
            f"Le tabelle potrebbero non essere di tipo riparto, "
            f"oppure il parser non ha riconosciuto le intestazioni."
        )

    lines: list[str] = [
        f"Estratti {len(accounts)} account dalle tabelle {indices}:"
    ]
    for acc in accounts:
        facts_summary = ", ".join(
            f"{f.get('category_label') or f.get('category_key', '?')}: "
            f"{f['amount']}"
            for f in acc.get("facts", [])
        )
        lines.append(
            f"  Unita {acc['unit_code']}: {acc['subject_label']} "
            f"\u2192 {facts_summary}"
        )
    return "\n".join(lines)


def _tool_llm_extract_table(
    text: str,
    tables: list[dict[str, Any]],
    index: int,
    category_name: str | None,
    period_from: str | None,
    period_to: str | None,
    *,
    provider: LLMProvider,
) -> str:
    """Extract accounts from a single table using the LLM.

    Used when the rule-based parser fails on a complex or ambiguous table.
    The LLM receives only the relevant portion of text.

    Returns a JSON string with ``summary`` (human-readable) and ``accounts``
    (structured list of {unit_code, subject_label, amount}) so the agent loop
    can accumulate the results.
    """
    if index < 0 or index >= len(tables):
        return json.dumps({"summary": f"Errore: indice tabella {index} non valido.", "accounts": []})

    t = tables[index]
    headers = t.get("headers", [])
    rows = t.get("rows", [])

    # Build a focused prompt for this single table
    table_json = json.dumps(
        {
            "table_id": t.get("table_id"),
            "page": t.get("page_number"),
            "headers": headers,
            "rows": [
                {"cells": row.get("cells"), "amounts": row.get("normalized_amounts")}
                for row in rows
            ],
            "totals": t.get("totals"),
        },
        indent=2,
        ensure_ascii=False,
    )

    # Get context text around the table
    context = _tool_get_context(text, tables, index, before=800, after=400)

    prompt = (
        f"Estrai le unita immobiliari dalla seguente tabella di riparto spese.\n\n"
        f"Categoria: {category_name or '(da determinare)'}\n\n"
        f"Contesto OCR:\n{context}\n\n"
        f"Dati tabella:\n{table_json}\n\n"
        f"Restituisci un array JSON di oggetti con:\n"
        f"- unit_code: il codice unita (es. \"1\", \"2\", \"3\")\n"
        f"- subject_label: il nome del proprietario/condomino\n"
        f"- amount: l'importo per questa categoria (numero)\n\n"
        f"Estrai SOLO da questa tabella. Se non trovi dati validi, restituisci array vuoto."
    )

    class SingleTableExtraction(BaseModel):
        accounts: list[dict[str, Any]] = Field(
            default_factory=list,
            description="Lista di {unit_code, subject_label, amount}",
        )

    try:
        parsed, raw = provider.chat_with_json(
            [
                ChatMessage(
                    role="system",
                    content=(
                        "Sei un contabile specializzato in tabelle di riparto condominiali. "
                        "Estrai le unita immobiliari da UNA SOLA tabella alla volta."
                    ),
                ),
                ChatMessage(role="user", content=prompt),
            ],
            SingleTableExtraction,
        )
        result = SingleTableExtraction.model_validate(parsed)
    except Exception as exc:
        logger.warning("LLM single-table extraction failed for table %d: %s", index, exc)
        return json.dumps({
            "summary": f"Estrazione LLM fallita per tabella [{index}]: {exc}",
            "accounts": [],
        })

    if not result.accounts:
        return json.dumps({
            "summary": f"Nessun account estratto dalla tabella [{index}].",
            "accounts": [],
        })

    lines: list[str] = [
        f"Estratti {len(result.accounts)} account dalla tabella [{index}] "
        f"(categoria: {category_name or '?'}):"
    ]
    for acc in result.accounts:
        lines.append(
            f"  Unita {acc.get('unit_code', '?')}: "
            f"{acc.get('subject_label', '?')} \u2192 "
            f"{acc.get('amount', 0)}"
        )

    return json.dumps({
        "summary": "\n".join(lines),
        "accounts": result.accounts,
        "category_name": category_name,
    })


def _tool_label_categories(
    text: str,
    tables: list[dict[str, Any]],
    indices: list[int],
    accumulated_accounts: dict[str, dict[str, Any]],
    *,
    provider: LLMProvider,
) -> str:
    """Use the LLM to assign correct category labels to accumulated accounts.

    The LLM receives the table list and the current accounts, and returns
    corrected category labels for each table.
    """
    if not accumulated_accounts:
        return "Nessun account accumulato da etichettare."

    selected = [tables[i] for i in indices if 0 <= i < len(tables)]
    if not selected:
        return "Nessuna tabella valida selezionata."

    # Build a summary of tables and their current labels
    table_info = []
    for i, t in zip(indices, selected):
        headers = t.get("headers", [])
        page = t.get("page_number", "?")
        # Get context to find category name — use generous window
        ctx = _tool_get_context(text, tables, i, before=1200, after=300)
        # Include first 2 data rows as sample
        rows = t.get("rows", [])
        sample_rows = []
        for row in rows[:2]:
            cells = row.get("cells", {})
            amounts = row.get("normalized_amounts", {})
            sample_rows.append(f"    cells={dict(cells)}, amounts={dict(amounts)}")
        table_info.append({
            "index": i,
            "page": page,
            "headers": headers,
            "context_snippet": ctx[:500],
            "sample_rows": "\n".join(sample_rows),
        })

    # Get current categories from accumulated accounts
    current_categories = set()
    for acc in accumulated_accounts.values():
        for fact in acc.get("facts", []):
            label = fact.get("category_label")
            if label and label != "Totale gestione":
                current_categories.add(label)

    prompt = (
        f"Ho {len(selected)} tabelle di riparto spese. Per ogni tabella, "
        f"determina il nome della categoria di spesa (es. GENERALI, SCALA N.10, "
        f"ASCENSORE N.6, RISCALDAMENTO, ecc.) basandoti sul contesto OCR e sui dati campione.\n\n"
        f"Categorie attuali: {sorted(current_categories) or 'nessuna'}\n\n"
        f"Dettaglio tabelle:\n"
        + "\n".join(
            f"Tabella [{t['index']}] (pagina {t['page']}):\n"
            f"  Headers: {t['headers']}\n"
            f"  Contesto: {t['context_snippet']}\n"
            f"  Righe campione:\n{t['sample_rows']}\n"
            for t in table_info
        )
        + "\n\nRestituisci un array JSON di oggetti con:\n"
        + "- table_index: l'indice della tabella\n"
        + "- category_label: il nome della categoria di spesa\n"
        + "- category_key: versione normalizzata (minuscolo, underscore)\n"
    )

    class CategoryLabeling(BaseModel):
        labels: list[dict[str, Any]] = Field(
            default_factory=list,
            description="Lista di {table_index, category_label, category_key}",
        )

    try:
        parsed, raw = provider.chat_with_json(
            [
                ChatMessage(
                    role="system",
                    content="Sei un contabile specializzato. Identifica le categorie di spesa nelle tabelle di riparto condominiali.",
                ),
                ChatMessage(role="user", content=prompt),
            ],
            CategoryLabeling,
        )
        result = CategoryLabeling.model_validate(parsed)
    except Exception as exc:
        logger.warning("Category labeling failed: %s", exc)
        return f"Etichettatura categorie fallita: {exc}"

    if not result.labels:
        return "Nessuna etichetta generata."

    # Apply labels to accumulated accounts — only relabel facts from the matching table
    from specialist_worker.services.accounting_statement import _normalize_key
    label_map = {str(lbl["table_index"]): lbl for lbl in result.labels}

    lines = ["Etichette categorie assegnate:"]
    for i, t in zip(indices, selected):
        lbl = label_map.get(str(i))
        if lbl:
            cat_label = lbl.get("category_label", "")
            cat_key = lbl.get("category_key", _normalize_key(cat_label))
            table_id = t.get("table_id")
            lines.append(f"  Tabella [{i}] (id={table_id}) → {cat_label} ({cat_key})")
            # Relabel only facts whose evidence points to this table
            for acc in accumulated_accounts.values():
                for fact in acc.get("facts", []):
                    if fact.get("category_label") in ("Totale gestione", None, "unknown"):
                        fact_table_id = (fact.get("evidence") or {}).get("table_id")
                        if fact_table_id is None or fact_table_id == table_id:
                            fact["category_label"] = cat_label
                            fact["category_key"] = cat_key
        else:
            lines.append(f"  Tabella [{i}] → nessuna etichetta")

    return "\n".join(lines)


def _tool_review_accounts(
    accumulated_accounts: dict[str, dict[str, Any]],
) -> str:
    """Show the current state of accumulated accounts for the agent to review."""
    if not accumulated_accounts:
        return "Nessun account accumulato finora."

    lines: list[str] = [
        f"Account accumulati: {len(accumulated_accounts)} unita immobiliari\n"
    ]
    # Sort by unit_code for stable output
    sorted_keys = sorted(
        accumulated_accounts.keys(),
        key=lambda k: (accumulated_accounts[k].get("unit_code", k), k),
    )
    for key in sorted_keys:
        acc = accumulated_accounts[key]
        unit_code = acc.get("unit_code", "?")
        subject = acc.get("subject_label", "?")
        facts = acc.get("facts", [])
        lines.append(f"  Unita {unit_code}: {subject}")

        # Group facts by category
        by_category: dict[str, list[dict[str, Any]]] = {}
        for f in facts:
            cat = f.get("category_label") or f.get("category_key", "unknown")
            by_category.setdefault(cat, []).append(f)

        for cat, cat_facts in sorted(by_category.items()):
            total = sum(f.get("amount", 0) for f in cat_facts)
            is_total = any(f.get("is_total") for f in cat_facts)
            tag = " [TOTALE]" if is_total else ""
            lines.append(f"    {cat}: {total:.2f}{tag}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Agent prompt
# ---------------------------------------------------------------------------

AGENT_SYSTEM_PROMPT = """Sei un contabile specializzato nell'estrazione di tabelle di riparto spese condominiali da documenti OCR.

Il tuo obiettivo e' estrarre TUTTE le unita immobiliari con i relativi importi per OGNI categoria di spesa.

Lavori in modo ITERATIVO: analizzi una tabella alla volta, estrai i dati, e costruisci gradualmente il risultato completo.

## Strumenti

1. **list_tables** — Elenca tutte le tabelle trovate nel documento.
   Parametri: nessuno.

2. **get_table** — Mostra i dettagli completi di una tabella (intestazioni, righe, totali).
   Parametri: table_index (int).

3. **get_context** — Mostra il testo OCR circostante una SINGOLA tabella per capire il contesto e trovare il nome della categoria.
   Parametri: table_index (int), before_chars (int, default 600), after_chars (int, default 300).

4. **get_all_contexts** — Mostra il testo OCR circostante TUTTE le tabelle expense_allocation in UNA SOLA chiamata.
   Molto piu' efficiente che chiamare get_context per ogni tabella.
   Parametri: before_chars (int, default 600), after_chars (int, default 300).

5. **search** — Cerca un pattern nel testo OCR.
   Parametri: pattern (stringa).

5. **extract_accounts** — Estrae le unita immobiliari da UNA O PIU tabelle usando il parser strutturale.
   Il parser funziona bene con tabelle ben formate con intestazioni "Cod", "Nominativo", "quota mill.", "TOTALE".
   Se fornisci category_name, le categorie verranno etichettate correttamente.
   Parametri: table_indices (list[int]), category_name (stringa, opzionale).

6. **llm_extract_table** — Estrae le unita immobiliari da UNA SINGOLA tabella usando l'LLM.
   USALO SOLO COME ULTIMA RISORSA quando extract_accounts non produce risultati.
   Parametri: llm_table_index (int), llm_category_name (stringa, opzionale).

7. **label_categories** — Usa l'LLM per assegnare i nomi corretti delle categorie di spesa a piu tabelle.
   Chiamalo DOPO extract_accounts se le etichette delle categorie sono sbagliate o mancanti.
   Parametri: label_table_indices (list[int]).

8. **review_accounts** — Mostra lo stato corrente degli account accumulati, raggruppati per categoria.
   Usalo per verificare che tutti i dati siano corretti prima di finalizzare.
   Parametri: nessuno.

9. **finalize** — Finalizza l'estrazione. Gli account accumulati verranno restituiti.
   Parametri: confidence (float, opzionale).

## Strategia consigliata (ITERATIVA, efficiente)

1. Chiama **list_tables** per vedere la struttura del documento.
2. Identifica le tabelle di **tipo expense_allocation**. Hanno intestazioni come "Cod", "Nominativo", "quota mill.", "TOTALE".
3. Chiama **get_all_contexts** UNA SOLA VOLTA per vedere il contesto di TUTTE le tabelle expense_allocation.
   Questo ti permette di trovare i nomi delle categorie per tutte le tabelle in un colpo solo.
4. Per OGNI tabella expense_allocation, chiama **extract_accounts** con UN SOLO indice tabella e il nome della categoria.
   Esempio: extract_accounts(table_indices=[3], category_name="GENERALI")
5. Se extract_accounts non produce risultati per una tabella, prova **llm_extract_table** per quella specifica tabella.
6. Dopo aver processato TUTTE le tabelle, chiama **review_accounts** per vedere il risultato complessivo.
7. Se le categorie non sono corrette, chiama **label_categories** per correggerle.
8. Alla fine chiama **finalize** con un confidence score.

## Regole importanti

- Le tabelle di riparto hanno intestazioni "Cod", "Nominativo", "quota mill.", "TOTALE".
- Il nome della categoria si trova nel testo subito prima della tabella. Usa get_context per trovarlo.
- IGNORA le tabelle riassuntive con intestazioni diverse (es. "Voce", "Importo", "Descrizione", "Preventivo", "Consuntivo").
- Ogni unita immobiliare deve apparire UNA SOLA volta con TUTTE le categorie accumulate.
- Raccogli TUTTE le categorie di riparto che trovi.
- Se una categoria non e' presente per una unita, l'importo e' 0 (non serve inserirlo).
- Quando chiami finalize, verranno restituiti tutti gli account accumulati automaticamente.
- NON usare llm_extract_table se extract_accounts ha gia' funzionato per quella tabella.
- llm_extract_table e' LENTO e COSTOSO. Usalo solo come ultima risorsa.
- review_accounts non costa nulla — usalo liberamente per verificare i progressi.
"""


# ---------------------------------------------------------------------------
# Helpers for account accumulation
# ---------------------------------------------------------------------------

def _merge_accounts(
    accumulated: dict[str, dict[str, Any]],
    new_accounts: list[dict[str, Any]],
) -> None:
    """Merge a list of pipeline-format accounts into the accumulated dict."""
    for acc in new_accounts:
        key = acc["account_key"]
        if key in accumulated:
            existing = accumulated[key]
            existing_facts = {
                (f.get("category_key"), f.get("fact_type")): f
                for f in existing.get("facts", [])
            }
            for f in acc.get("facts", []):
                dedup_key = (f.get("category_key"), f.get("fact_type"))
                if dedup_key not in existing_facts:
                    existing["facts"].append(f)
                    existing_facts[dedup_key] = f
            if acc.get("subject_label"):
                existing["subject_label"] = acc["subject_label"]
            if acc.get("subject_aliases"):
                existing.setdefault("subject_aliases", [])
                for alias in acc["subject_aliases"]:
                    if alias not in existing["subject_aliases"]:
                        existing["subject_aliases"].append(alias)
        else:
            accumulated[key] = dict(acc)


def _llm_accounts_to_pipeline(
    llm_accounts: list[dict[str, Any]],
    category_name: str | None,
    period_from: str | None,
    period_to: str | None,
) -> list[dict[str, Any]]:
    """Convert LLM single-table extraction format to pipeline account format.

    LLM format: [{unit_code, subject_label, amount}, ...]
    Pipeline format: [{account_key, unit_code, subject_label, subject_aliases, facts}, ...]
    """
    from specialist_worker.services.accounting_statement import _normalize_key

    grouped: dict[str, dict[str, Any]] = {}
    for entry in llm_accounts:
        unit_code = str(entry.get("unit_code", "")).strip()
        subject_label = str(entry.get("subject_label", "")).strip()
        amount = float(entry.get("amount", 0))
        if not unit_code or not subject_label:
            continue

        account_key = _normalize_key(unit_code)
        cat_key = _normalize_key(category_name) if category_name else "unknown"
        cat_label = category_name or "unknown"

        if account_key not in grouped:
            grouped[account_key] = {
                "account_key": account_key,
                "unit_code": unit_code,
                "subject_label": subject_label,
                "subject_aliases": [subject_label],
                "facts": [],
            }

        grouped[account_key]["facts"].append({
            "fact_type": "allocated_expense",
            "amount": abs(amount),
            "raw_amount": amount,
            "category_key": cat_key,
            "category_label": cat_label,
            "is_total": False,
            "currency": "EUR",
            "period_context": {
                "from": period_from,
                "to": period_to,
                "source": "llm_extraction",
                "review_status": "unverified",
            },
            "evidence": {
                "table_id": None,
                "table_type": None,
                "accounting_context": None,
                "row_id": None,
                "column": None,
                "raw_value": None,
            },
        })

    return list(grouped.values())


# ---------------------------------------------------------------------------
# Agent loop
# ---------------------------------------------------------------------------

def agentic_account_extraction(
    text: str,
    tables: list[dict[str, Any]],
    period_from: str | None,
    period_to: str | None,
    *,
    provider: LLMProvider | None,
    max_steps: int = 80,
) -> list[dict[str, Any]]:
    """Extract accounts using an agentic loop with tool use.

    The LLM drives the process iteratively: it inspects the document via tools,
    extracts accounts table by table, and finally calls ``finalize`` with the
    complete result.

    Returns a list of pipeline-format account dicts (same shape as
    ``_extract_accounts``), or an empty list on failure.
    """
    if provider is None or not text.strip():
        return []

    messages: list[ChatMessage] = [
        ChatMessage(role="system", content=AGENT_SYSTEM_PROMPT),
        ChatMessage(
            role="user",
            content=(
                f"Ho un documento contabile con {len(tables)} tabelle estratte.\n"
                f"Periodo contabile: {period_from or '?'} \u2192 {period_to or '?'}.\n\n"
                f"Estrai le unita immobiliari con i relativi importi per OGNI "
                f"categoria di spesa. Usa gli strumenti passo passo."
            ),
        ),
    ]

    accumulated_accounts: dict[str, dict[str, Any]] = {}

    for step in range(max_steps):
        # --- Decide next action ---
        try:
            raw_action, raw_text = provider.chat_with_json(messages, AgentAction)
            action = AgentAction.model_validate(raw_action)
        except Exception as exc:
            logger.warning("Agent step %d decision failed: %s", step, exc)
            break

        logger.info(
            "Agent step %d: action=%s reasoning=%.120s",
            step, action.action, action.reasoning,
        )

        # --- Finalize ---
        if action.action == "finalize":
            if accumulated_accounts:
                logger.info(
                    "Agent finalized with %d accumulated accounts (confidence=%.2f)",
                    len(accumulated_accounts), action.confidence or 0.0,
                )
                return list(accumulated_accounts.values())
            logger.info("Agent finalized with no accounts")
            return []

        # --- Execute tool ---
        try:
            result = _execute_tool(
                action, text, tables, period_from, period_to,
                accumulated_accounts=accumulated_accounts,
                provider=provider,
            )
        except Exception as exc:
            logger.warning("Agent step %d tool execution failed: %s", step, exc)
            result = f"Errore durante l'esecuzione: {exc}"

        # Accumulate accounts from tool calls
        if action.action == "extract_accounts" and action.table_indices:
            selected = [
                tables[i] for i in action.table_indices if 0 <= i < len(tables)
            ]
            if selected:
                # Apply category override (same logic as _tool_extract_accounts)
                if action.category_name:
                    for t in selected:
                        t["_category_label"] = action.category_name
                from specialist_worker.services.accounting_statement import (
                    _extract_accounts,
                )
                new_accounts = _extract_accounts(
                    selected, period_from, period_to,
                )
                _merge_accounts(accumulated_accounts, new_accounts)

        elif action.action == "llm_extract_table":
            # Parse the JSON result to extract structured accounts
            try:
                llm_result = json.loads(result)
                llm_accounts = llm_result.get("accounts", [])
                cat_name = llm_result.get("category_name")
                if llm_accounts:
                    # Convert LLM single-table format to pipeline format
                    pipeline_accounts = _llm_accounts_to_pipeline(
                        llm_accounts, cat_name, period_from, period_to,
                    )
                    _merge_accounts(accumulated_accounts, pipeline_accounts)
            except (json.JSONDecodeError, Exception) as exc:
                logger.warning("Failed to parse llm_extract_table result: %s", exc)

        # Append result to conversation
        # For llm_extract_table, show only the summary to the LLM
        display_result = result
        if action.action == "llm_extract_table":
            try:
                display_result = json.loads(result).get("summary", result)
            except (json.JSONDecodeError, Exception):
                pass
        messages.append(ChatMessage(
            role="user",
            content=f"Risultato di **{action.action}**:\n{display_result}",
        ))

    # Ran out of steps — return what we have
    if accumulated_accounts:
        logger.warning(
            "Agent ran out of steps (%d) with %d accumulated accounts",
            max_steps, len(accumulated_accounts),
        )
        return list(accumulated_accounts.values())
    return []


# ---------------------------------------------------------------------------
# Tool dispatcher
# ---------------------------------------------------------------------------

def _execute_tool(
    action: AgentAction,
    text: str,
    tables: list[dict[str, Any]],
    period_from: str | None,
    period_to: str | None,
    *,
    accumulated_accounts: dict[str, dict[str, Any]] | None = None,
    provider: LLMProvider | None,
) -> str:
    """Execute the tool requested by the agent and return a text result."""
    if action.action == "list_tables":
        return _tool_list_tables(tables)

    if action.action == "get_table":
        return _tool_get_table(tables, action.table_index or 0)

    if action.action == "get_context":
        return _tool_get_context(
            text, tables,
            action.table_index or 0,
            before=action.before_chars or 600,
            after=action.after_chars or 300,
        )

    if action.action == "get_all_contexts":
        return _tool_get_all_contexts(
            text, tables,
            before=action.before_chars or 600,
            after=action.after_chars or 300,
        )

    if action.action == "search":
        return _tool_search(text, action.pattern or "")

    if action.action == "extract_accounts":
        return _tool_extract_accounts(
            text,
            tables,
            action.table_indices or [],
            period_from,
            period_to,
            category_name=action.category_name,
        )

    if action.action == "llm_extract_table":
        if provider is None:
            return "LLM non disponibile per l'estrazione."
        return _tool_llm_extract_table(
            text, tables,
            action.llm_table_index or 0,
            action.llm_category_name,
            period_from, period_to,
            provider=provider,
        )

    if action.action == "label_categories":
        if provider is None:
            return "LLM non disponibile per l'etichettatura."
        return _tool_label_categories(
            text, tables,
            action.label_table_indices or [],
            accumulated_accounts,
            provider=provider,
        )

    if action.action == "review_accounts":
        return _tool_review_accounts(accumulated_accounts or {})

    return f"Azione sconosciuta: {action.action}"
