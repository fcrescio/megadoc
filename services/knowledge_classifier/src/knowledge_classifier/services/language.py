"""Language detection and prompt-localization helpers for knowledge extraction."""

from __future__ import annotations

import re

ITALIAN_MARKERS = {
    " il ",
    " lo ",
    " la ",
    " gli ",
    " delle ",
    " della ",
    " condominio ",
    " assemblea ",
    " fattura ",
    " preventivo ",
    " bolletta ",
    " verbale ",
    " contratto ",
    " amministratore ",
    " pagamento ",
    " saluti ",
    " gennaio ",
    " febbraio ",
    " marzo ",
    " aprile ",
    " maggio ",
    " giugno ",
    " luglio ",
    " agosto ",
    " settembre ",
    " ottobre ",
    " novembre ",
    " dicembre ",
}

ENGLISH_MARKERS = {
    " the ",
    " and ",
    " invoice ",
    " contract ",
    " payment ",
    " customer ",
    " amount ",
    " date ",
    " dear ",
    " sincerely ",
    " january ",
    " february ",
    " march ",
    " april ",
    " may ",
    " june ",
    " july ",
    " august ",
    " september ",
    " october ",
    " november ",
    " december ",
}


def detect_document_language(text: str | None) -> str:
    """Return a coarse language code for the document text."""
    if not text:
        return "it"

    compact = re.sub(r"\s+", " ", text.lower())
    normalized = f" {compact} "

    italian_score = sum(normalized.count(marker) for marker in ITALIAN_MARKERS)
    english_score = sum(normalized.count(marker) for marker in ENGLISH_MARKERS)

    if re.search(r"[àèéìòù]", normalized):
        italian_score += 3

    if italian_score == 0 and english_score == 0:
        return "it"
    if english_score > italian_score:
        return "en"
    return "it"


def output_language_instruction(language_code: str) -> str:
    """Instruction injected into prompts to keep output aligned to source language."""
    if language_code == "en":
        return (
            "The source document is in English. Write every free-text output field in English. "
            "This includes rationale, summaries, proposed titles, descriptions, and salient features. "
            "Do not translate proper nouns, addresses, codes, amounts, legal references, or document snippets."
        )

    return (
        "Il documento sorgente è in italiano. Scrivi in italiano tutti i campi testuali liberi. "
        "Questo include rationale, summary, proposed_title, description e salient_features. "
        "Non tradurre nomi propri, indirizzi, codici, importi, riferimenti normativi o estratti testuali del documento."
    )
