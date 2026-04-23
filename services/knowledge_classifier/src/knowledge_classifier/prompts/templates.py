"""Prompt templates for knowledge classifier tasks."""

# Segmentation prompt
SEGMENTATION_PROMPT = """You are a document segmentation expert. Your task is to identify boundaries between distinct documents within a multi-page scan.

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

Analyze the following pages:
{pages_content}
"""

# Classification prompt
CLASSIFICATION_PROMPT = """You are a document classification expert. Classify the given document into one of these document types:

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
  "rationale": "Brief explanation of classification"
}

Rules:
- Choose the MOST specific matching type
- Confidence between 0 and 1
- List 1-3 alternative types if applicable
- Extract salient features that led to classification
- If confidence < 0.7, mark for review
"""

# Entity extraction prompt
ENTITY_EXTRACTION_PROMPT = """You are an archival entity extraction expert for condominium documents.

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
"""

# Topic assignment prompt
TOPIC_ASSIGNMENT_PROMPT = """You are a topic assignment expert. Assign documents to existing topics or propose new topics.

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
- Prefer existing topics over new proposals
- Use "primary" for main topic, "secondary" for related topics
- Only propose new topic if truly no match exists
- Confidence < 0.6 means needs_review
- Be conservative with new topic proposals
"""
