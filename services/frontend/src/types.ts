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
