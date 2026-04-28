export interface Document {
  id: string;
  external_id: string | null;
  original_filename: string;
  mime_type: string;
  sha256: string;
  size_bytes: number;
  source_type: string;
  created_at: string;
}

export interface DocumentVersion {
  id: string;
  document_id: string;
  version_number: number;
  storage_bucket: string;
  storage_object_key: string;
  created_at: string;
}

export interface DocumentAsset {
  id: string;
  document_id: string;
  asset_type: string;
  storage_bucket: string;
  storage_object_key: string;
  content_type: string;
  created_at: string;
}

export interface OCRResult {
  id: string;
  document_id: string;
  document_version_id: string;
  engine_name: string;
  engine_version: string;
  pipeline_version: string;
  status: string;
  full_text: string;
  markdown_text: string;
  structured_json: Record<string, unknown>;
  page_count: number;
  confidence_summary: string | null;
  created_at: string;
}

export interface Job {
  id: string;
  document_id: string;
  job_type: string;
  status: 'queued' | 'running' | 'succeeded' | 'failed';
  priority: number;
  attempt_count: number;
  error_message: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface UploadResponse {
  document_id: string;
  version_id: string;
  status: string;
  deduplicated: boolean;
  job_id: string | null;
  sha256: string;
  size_bytes: number;
}

export interface KnowledgeEntity {
  id: string;
  entity_type: string;
  entity_value: string;
  normalized_value: string | null;
  confidence: number | null;
  page_from: number | null;
  page_to: number | null;
}

export interface KnowledgeTopicAssignment {
  id: string;
  topic_id: string;
  topic_slug: string | null;
  topic_title: string | null;
  topic_kind: string | null;
  topic_class: string | null;
  assignment_role: string;
  confidence: number | null;
  rationale: string | null;
}

export interface KnowledgeTopicProposal {
  id: string;
  proposed_slug: string;
  proposed_title: string;
  topic_class: string;
  proposed_topic_kind: string;
  description: string | null;
  proposal_status: string;
  matched_existing_topic_id: string | null;
  matched_existing_topic_title: string | null;
  source_document_unit_id: string | null;
  source_document_id: string | null;
  source_document_filename: string | null;
  source_start_page: number | null;
  source_end_page: number | null;
  confidence: number | null;
  rationale: string | null;
  created_at: string;
  reviewed_at: string | null;
}

export interface KnowledgeDocumentUnit {
  id: string;
  scan_unit_id: string;
  ordinal: number;
  start_page: number;
  end_page: number;
  title: string | null;
  document_type_code: string | null;
  document_type_name: string | null;
  document_type_confidence: number | null;
  segmentation_confidence: number | null;
  extracted_summary: string | null;
  review_status: string;
  entities: KnowledgeEntity[];
  topic_assignments: KnowledgeTopicAssignment[];
  proposal: KnowledgeTopicProposal | null;
  created_at: string;
  updated_at: string | null;
}

export interface KnowledgeScanUnit {
  id: string;
  source_document_id: string;
  source_document_version_id: string | null;
  source_ocr_result_id: string;
  page_count: number;
  status: string;
  segmentation_confidence: number | null;
  classification_confidence: number | null;
  assignment_confidence: number | null;
  created_at: string;
  updated_at: string | null;
  document_units: KnowledgeDocumentUnit[];
}

export interface DocumentKnowledge {
  document_id: string;
  scan_units: KnowledgeScanUnit[];
}

export interface KnowledgeTopicSummary {
  id: string;
  slug: string;
  title: string;
  topic_class: string;
  topic_kind: string;
  description: string | null;
  canonical: boolean;
  is_active: boolean;
  assignment_count: number;
  proposal_count: number;
  related_document_count: number;
  alias_count: number;
  created_at: string;
  updated_at: string | null;
}

export interface KnowledgeTopicRelatedDocument {
  document_id: string;
  external_id: string | null;
  original_filename: string;
  created_at: string;
  document_unit_id: string;
  document_type_code: string | null;
  review_status: string;
  topic_assignment_confidence: number | null;
  assignment_role: string;
  start_page: number;
  end_page: number;
  summary: string | null;
}

export interface KnowledgeTopicDetail {
  topic: KnowledgeTopicSummary;
  aliases: string[];
  related_documents: KnowledgeTopicRelatedDocument[];
}

export interface KnowledgeConsolidationResult {
  topics_before: number;
  topics_after: number;
  topics_merged: number;
  aliases_created: number;
  assignments_retargeted: number;
  proposals_retargeted: number;
}

export interface TopicCreatePayload {
  slug: string;
  title: string;
  topic_class: string;
  topic_kind: string;
  description?: string | null;
  aliases?: string[];
}

export interface TopicAssignmentUpsertPayload {
  topic_id?: string;
  assignment_role: string;
  confidence?: number | null;
  rationale?: string | null;
  create_topic?: TopicCreatePayload;
}

export interface TopicProposalResolutionPayload {
  action: 'approve_new_topic' | 'merge_into_existing' | 'add_secondary_topic' | 'reject';
  assignment_role: string;
  target_topic_id?: string;
  create_topic?: TopicCreatePayload;
}
