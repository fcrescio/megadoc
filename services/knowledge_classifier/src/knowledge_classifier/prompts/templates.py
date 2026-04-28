"""Prompt templates for knowledge classifier tasks."""

# Segmentation prompt
SEGMENTATION_PROMPT = """You are a document segmentation expert. Your task is to identify boundaries between distinct documents within a multi-page scan.

{output_language_instruction}

Analyze the provided page content and identify where one document ends and another begins.

Look for these signals of document boundaries:
1. Title patterns: "Verbale", "Rendiconto", "Fattura", "Preventivo", "Bolletta", "Contratto", "Assemblea"
2. Section resets: new numbering, new headers
3. Content discontinuity: sudden topic changes
4. Document markers: "Allegato", "Appendice", "Documento"

Input format:
- Pages with their text content
- Page numbers

Output JSON schema:
{
  "segments": [
    {
      "start_page": 1,
      "end_page": 3,
      "confidence": 0.9,
      "rationale": "Why this is a segment"
    }
  ],
  "overall_confidence": 0.85,
  "boundaries": [
    {
      "page_before": 3,
      "page_after": 4,
      "confidence": 0.9,
      "rationale": "Why boundary here"
    }
  ]
}

Rules:
- Each page must belong to exactly one segment
- Segments must be consecutive (no gaps)
- Confidence between 0 and 1
- If uncertain, create fewer segments with lower confidence
- Write every rationale in the source document language

Analyze the following pages:
{pages_content}
"""

# Classification prompt
CLASSIFICATION_PROMPT = """You are a document classification expert. Classify the given document into one of these document types:

{output_language_instruction}

Available document types:
- bolletta: Utility bills, service charges
- verbale_assemblea: Meeting minutes, assembly records
- rendiconto_contabile: Financial statements, accounting reports
- riparto_spese: Expense allocation documents
- fattura: Invoices
- preventivo: Quotes, estimates
- lettera: Letters, correspondence
- contratto: Contracts, agreements
- allegato_tecnico: Technical attachments, specifications
- altro: Other documents not fitting above categories

Document content to classify:
{document_text}

Output JSON schema:
{
  "primary_type": {
    "type_code": "verbale_assemblea",
    "confidence": 0.95,
    "salient_features": ["verbale", "assemblea", "deliberazioni"]
  },
  "alternatives": [
    {
      "type_code": "rendiconto_contabile",
      "confidence": 0.3,
      "salient_features": []
    }
  ],
  "rationale": "Sintesi molto breve della classificazione"
}

Rules:
- Choose the MOST specific matching type
- Confidence between 0 and 1
- List 1-3 alternative types if applicable
- Extract salient features that led to classification
- If confidence < 0.7, mark for review
- Write rationale and salient_features in the source document language
- Keep rationale brief: 1-2 concise sentences, ideally under 40 words total
- Keep type_code values canonical and unchanged
"""

# Entity extraction prompt
ENTITY_EXTRACTION_PROMPT = """You are an archival entity extraction expert for condominium documents.

{output_language_instruction}

Extract ONLY high-value filing/search entities from the document. This is not table transcription.

Hard rules:
- Return at most 25 entities total.
- Use only these entity_type values: condominio, organizzazione, persona, fornitore, indirizzo, data, periodo, importo, numero_documento.
- Do NOT extract every owner row, apartment row, table cell, or repeated amount.
- For monetary amounts, return at most 8 values and only if they are document-level totals, balances, installments, or payment amounts.
- For people, return only administrators, vendors, lawyers, signatories, or named parties central to the document. Do not list all condominium owners from allocation tables.
- Deduplicate aggressively. Same condominium/address/date/amount appears once.
- Use concise normalized_value. Dates as YYYY-MM-DD when unambiguous; periods as YYYY-MM-DD_to_YYYY-MM-DD.
- If the text is mostly a table, summarize the table in summary instead of enumerating rows.
- Stop immediately after a single valid JSON object. No markdown, no prose.

Entity types to extract:
- condominio: Condominium name
- organizzazione: Organizations mentioned
- persona: People names
- fornitore: Vendors, suppliers
- indirizzo: Addresses
- data: Dates (normalize to YYYY-MM-DD)
- periodo: Periods (e.g., "2024", "Gennaio-Marzo 2024")
- importo: Monetary amounts (extract number and currency)
- numero_documento: Document numbers, reference codes

Document content:
{document_text}

Output JSON schema:
{
  "entities": [
    {
      "entity_type": "condominio",
      "entity_value": "Condominio Via Roma",
      "normalized_value": "condominio_via_roma",
      "confidence": 0.9,
      "page_from": 1,
      "page_to": 1
    }
  ],
  "summary": "Brief 1-2 sentence summary of document"
}

Rules:
- Extract only the most important archival/search entities
- Normalize values for consistent matching (lowercase, underscores)
- Confidence between 0 and 1
- Track page locations when possible
- Summary should capture document purpose in one sentence, max 30 words
- Write summary in the source document language
- Keep entity_value as it appears in the document whenever possible
"""

# Topic assignment prompt
TOPIC_ASSIGNMENT_PROMPT = """You are a topic assignment expert. Assign documents to existing topics or propose new topics.

{output_language_instruction}

Existing topics available:
{topics_list}

Document to assign:
- Type: {document_type}
- Title: {document_title}
- Summary: {document_summary}
- Entities: {entities_list}

Decision options:
1. assign_existing: Match to one existing topic
2. assign_multiple: Match to multiple existing topics
3. propose_new: No good match, propose new topic
4. needs_review: Uncertain, requires human review

Output JSON schema:
{
  "action": "assign_existing",
  "topic_ids": ["uuid-of-topic"],
  "assignment_roles": ["primary"],
  "proposed_topic": {
    "proposed_slug": "new-topic-slug",
    "proposed_title": "New Topic Title",
    "topic_class": "case_file",
    "description": "Why this topic is needed"
  },
  "confidence": 0.85,
  "rationale": "Explanation of decision"
}

Topic classes:
- case_file: Case files, dossiers
- meeting: Meetings, assemblies
- financial_period: Financial periods, budgets
- vendor_relationship: Vendor relationships
- building_issue: Building maintenance, issues
- legal_matter: Legal matters
- general_administration: General admin
- other: Other

Rules:
- Assign to an existing topic only when it represents the same real-world matter, not just the same document type
- For condominium/building documents, the condominium name, street, or building address is a hard anchor: if the document names one building/address and the candidate names a different one, do not assign it
- For financial-period topics, require the same building/address plus the same or overlapping accounting period for high confidence
- For meeting topics, require the same building/address plus the same meeting date/title for high confidence
- For vendor/building/legal matters, require the same building/address or the same vendor/person/legal matter
- Do not assign solely because words like bilancio, preventivo, verbale, condominio, spese, or assemblea overlap
- If an existing candidate is broadly similar but has a different anchor, use propose_new when the document has a clear topic; otherwise use needs_review with confidence <= 0.45
- Use "primary" for main topic, "secondary" for related topics
- Prefer a new proposal over a wrong existing topic
- Confidence < 0.6 means needs_review
- Be conservative with duplicate topic proposals, but never merge different buildings, addresses, periods, meetings, or legal matters
- Write rationale, proposed_title, and description in the source document language
- Keep topic_ids, slugs, and topic_class values canonical
"""
