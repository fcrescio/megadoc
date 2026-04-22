"""Fixtures for knowledge classifier tests."""

# OCR fixture: single verbale
VERBALE_OCR_STRUCTURED = {
    "pages": [
        {
            "page_number": 1,
            "text": "VERBALE DI ASSEMBLEA\n\nCondominio Via Roma\nAssemblea Ordinaria del 15 Marzo 2024\n\nPresenti: Rossi Mario, Bianchi Luca, Verdi Giulia\nAssenti: Neri Paolo\n\nOrdine del giorno:\n1. Approvazione rendiconto 2023\n2. Deliberazione spesa facciata\n\nDeliberazioni:\n- Approvato rendiconto 2023 con spese totali €45.000\n- Autorizzato spesa €120.000 per rifacimento facciata\n\nFirma amministratore: Mario Rossi",
        },
    ],
}

VERBALE_OCR_MARKDOWN = """# VERBALE DI ASSEMBLEA

**Condominio Via Roma**

Assemblea Ordinaria del 15 Marzo 2024

**Presenti:** Rossi Mario, Bianchi Luca, Verdi Giulia

**Assenti:** Neri Paolo

## Ordine del giorno

1. Approvazione rendiconto 2023
2. Deliberazione spesa facciata

## Deliberazioni

- Approvato rendiconto 2023 con spese totali €45.000
- Autorizzato spesa €120.000 per rifacimento facciata

Firma amministratore: Mario Rossi
"""

# OCR fixture: mixed verbale + rendiconto
MIXED_OCR_STRUCTURED = {
    "pages": [
        {
            "page_number": 1,
            "text": "VERBALE DI ASSEMBLEA\n\nCondominio Via Roma\nAssemblea Straordinaria del 10 Gennaio 2024\n\nPresenti: Rossi Mario, Bianchi Luca\n\nDeliberazione: Approvazione bilancio preventivo 2024",
        },
        {
            "page_number": 2,
            "text": "RENDICONTO CONTABILE 2023\n\nCondominio Via Roma\n\nENTRATE\nQuote condominiali: €38.000\nRimborso spese: €2.000\nTotale entrate: €40.000",
        },
        {
            "page_number": 3,
            "text": "SPESE\nManutenzione ascensore: €5.000\nLuce comune: €3.000\nSpese amministrative: €8.000\nTotale spese: €16.000\n\nSaldo: €24.000",
        },
    ],
}

MIXED_OCR_MARKDOWN = """# VERBALE DI ASSEMBLEA

Condominio Via Roma
Assemblea Straordinaria del 10 Gennaio 2024

Presenti: Rossi Mario, Bianchi Luca

Deliberazione: Approvazione bilancio preventivo 2024

---

# RENDICONTO CONTABILE 2023

Condominio Via Roma

## ENTRATE

- Quote condominiali: €38.000
- Rimborso spese: €2.000
- **Totale entrate: €40.000**

## SPESE

- Manutenzione ascensore: €5.000
- Luce comune: €3.000
- Spese amministrative: €8.000
- **Totale spese: €16.000**

**Saldo: €24.000**
"""

# OCR fixture: fattura
FATTURA_OCR_STRUCTURED = {
    "pages": [
        {
            "page_number": 1,
            "text": "FATTURA N. 2024/001\n\nDitta Elettrica Srl\nVia Milano 10, Roma\nP.IVA: 12345678901\n\nSpett.le Condominio Via Roma\nVia Roma 5, Roma\n\nOggetto: Fornitura energia gennaio 2024\n\nImporto: €1.250,00\nScadenza: 31/01/2024",
        },
    ],
}

FATTURA_OCR_MARKDOWN = """# FATTURA N. 2024/001

**Ditta Elettrica Srl**
Via Milano 10, Roma
P.IVA: 12345678901

**Spett.le Condominio Via Roma**
Via Roma 5, Roma

**Oggetto:** Fornitura energia gennaio 2024

**Importo:** €1.250,00
**Scadenza:** 31/01/2024
"""

# OCR fixture: bolletta
BOLLETTA_OCR_STRUCTURED = {
    "pages": [
        {
            "page_number": 1,
            "text": "BOLLETTA ACQUA\n\nAzienda Servizi Idrici\n\nCondominio Via Roma\nVia Roma 5, Roma\n\nPeriodo: Gennaio - Marzo 2024\nConsumi: 150 mc\nImporto da pagare: €85,50\nScadenza pagamento: 28/03/2024",
        },
    ],
}

BOLLETTA_OCR_MARKDOWN = """# BOLLETTA ACQUA

**Azienda Servizi Idrici**

**Condominio Via Roma**
Via Roma 5, Roma

**Periodo:** Gennaio - Marzo 2024
**Consumi:** 150 mc
**Importo da pagare:** €85,50
**Scadenza pagamento:** 28/03/2024
"""
