import type {
  Document,
  DocumentVersion,
  DocumentAsset,
  OCRResult,
  Job,
  SystemStatus,
  UploadResponse,
  DocumentKnowledge,
  KnowledgeTopicSummary,
  KnowledgeTopicDetail,
  KnowledgeSearchResult,
  SpecialistAccountingStatementSummary,
  SpecialistUtilityBillSummary,
  KnowledgeEntitySummary,
  KnowledgeEntityDetail,
  CanonicalEntitySummary,
  CanonicalEntityDetail,
  CanonicalEntityMergePayload,
  ManualDocument,
  ManualComment,
  ManualCommentCreatePayload,
  ManualCommentUpdatePayload,
  KnowledgeConsolidationResult,
  GraphConsolidationSuggestions,
  GraphConsolidationReviewPayload,
  GraphConsolidationReviewResult,
  KnowledgeDocumentUnit,
  KnowledgeTopicProposal,
  TopicAssignmentUpsertPayload,
  TopicCreatePayload,
  TopicProposalResolutionPayload,
} from '../types';

const API_BASE = '/api';

async function handleResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const error = await response.text();
    throw new Error(error || `HTTP ${response.status}`);
  }
  return response.json();
}

export async function getDocuments(limit = 100): Promise<Document[]> {
  const response = await fetch(`${API_BASE}/documents?limit=${limit}`);
  return handleResponse<Document[]>(response);
}

export async function getSystemStatus(): Promise<SystemStatus> {
  const response = await fetch(`${API_BASE}/system/status`);
  return handleResponse<SystemStatus>(response);
}

export async function getDocument(id: string): Promise<Document> {
  const response = await fetch(`${API_BASE}/documents/${id}`);
  return handleResponse<Document>(response);
}

export async function getDocumentVersions(documentId: string): Promise<DocumentVersion[]> {
  const response = await fetch(`${API_BASE}/documents/${documentId}/versions`);
  return handleResponse<DocumentVersion[]>(response);
}

export async function getDocumentAssets(documentId: string): Promise<DocumentAsset[]> {
  const response = await fetch(`${API_BASE}/documents/${documentId}/assets`);
  return handleResponse<DocumentAsset[]>(response);
}

export async function getDocumentOCR(documentId: string): Promise<OCRResult> {
  const response = await fetch(`${API_BASE}/documents/${documentId}/ocr`);
  return handleResponse<OCRResult>(response);
}

export async function getDocumentKnowledge(documentId: string): Promise<DocumentKnowledge> {
  const response = await fetch(`${API_BASE}/knowledge/documents/${documentId}`);
  return handleResponse<DocumentKnowledge>(response);
}

export async function ensureDocumentKnowledge(documentId: string): Promise<{ id: string }> {
  const response = await fetch(`${API_BASE}/knowledge/documents/${documentId}/ensure`, {
    method: 'POST',
  });
  return handleResponse<{ id: string }>(response);
}

export async function ensureDocumentSpecialists(
  documentId: string,
): Promise<{ scan_unit_id: string; created_jobs: number; jobs: { id: string; specialist_type: string; status: string }[] }> {
  const response = await fetch(`${API_BASE}/knowledge/documents/${documentId}/ensure-specialists`, {
    method: 'POST',
  });
  return handleResponse(response);
}

export async function getKnowledgeTopics(includeInactive = false, topicKind?: string): Promise<KnowledgeTopicSummary[]> {
  const params = new URLSearchParams();
  params.set('include_inactive', String(includeInactive));
  if (topicKind) {
    params.set('topic_kind', topicKind);
  }
  const response = await fetch(`${API_BASE}/knowledge/topics?${params.toString()}`);
  return handleResponse<KnowledgeTopicSummary[]>(response);
}

export async function getKnowledgeTopic(topicId: string): Promise<KnowledgeTopicDetail> {
  const response = await fetch(`${API_BASE}/knowledge/topics/${topicId}`);
  return handleResponse<KnowledgeTopicDetail>(response);
}

export async function searchKnowledge(
  query: string,
  options?: {
    includeInactive?: boolean;
    topicKind?: string;
    topicClass?: string;
    limit?: number;
  },
): Promise<KnowledgeSearchResult> {
  const params = new URLSearchParams();
  params.set('q', query);
  params.set('include_inactive', String(options?.includeInactive ?? false));
  if (options?.topicKind && options.topicKind !== 'all') {
    params.set('topic_kind', options.topicKind);
  }
  if (options?.topicClass && options.topicClass !== 'all') {
    params.set('topic_class', options.topicClass);
  }
  if (options?.limit) {
    params.set('limit', String(options.limit));
  }
  const response = await fetch(`${API_BASE}/knowledge/search?${params.toString()}`);
  return handleResponse<KnowledgeSearchResult>(response);
}

export async function getSpecialistUtilityBills(options?: {
  query?: string;
  issuer?: string;
  paymentStatus?: string;
  overdueOnly?: boolean;
  limit?: number;
}): Promise<{ total: number; items: SpecialistUtilityBillSummary[] }> {
  const params = new URLSearchParams();
  if (options?.query) params.set('q', options.query);
  if (options?.issuer) params.set('issuer', options.issuer);
  if (options?.paymentStatus && options.paymentStatus !== 'all') params.set('payment_status', options.paymentStatus);
  if (options?.overdueOnly) params.set('overdue_only', 'true');
  if (options?.limit) params.set('limit', String(options.limit));
  const response = await fetch(`${API_BASE}/knowledge/specialists/utility-bills?${params.toString()}`);
  return handleResponse(response);
}

export async function getSpecialistAccountingStatements(options?: {
  query?: string;
  statementType?: string;
  checkStatus?: string;
  limit?: number;
}): Promise<{ total: number; items: SpecialistAccountingStatementSummary[] }> {
  const params = new URLSearchParams();
  if (options?.query) params.set('q', options.query);
  if (options?.statementType && options.statementType !== 'all') params.set('statement_type', options.statementType);
  if (options?.checkStatus && options.checkStatus !== 'all') params.set('check_status', options.checkStatus);
  if (options?.limit) params.set('limit', String(options.limit));
  const response = await fetch(`${API_BASE}/knowledge/specialists/accounting-statements?${params.toString()}`);
  return handleResponse(response);
}

export function getSpecialistResultExportUrl(resultId: string, format: 'json' | 'csv'): string {
  return `${API_BASE}/knowledge/specialist-results/${resultId}/export?format=${format}`;
}

export async function getKnowledgeEntities(
  options?: { query?: string; entityType?: string; limit?: number },
): Promise<KnowledgeEntitySummary[]> {
  const params = new URLSearchParams();
  if (options?.query) {
    params.set('q', options.query);
  }
  if (options?.entityType && options.entityType !== 'all') {
    params.set('entity_type', options.entityType);
  }
  if (options?.limit) {
    params.set('limit', String(options.limit));
  }
  const response = await fetch(`${API_BASE}/knowledge/entities?${params.toString()}`);
  return handleResponse<KnowledgeEntitySummary[]>(response);
}

export async function getKnowledgeEntityDetail(entityType: string, entityKey: string): Promise<KnowledgeEntityDetail> {
  const params = new URLSearchParams();
  params.set('entity_type', entityType);
  params.set('entity_key', entityKey);
  const response = await fetch(`${API_BASE}/knowledge/entities/detail?${params.toString()}`);
  return handleResponse<KnowledgeEntityDetail>(response);
}

export async function getCanonicalEntities(
  options?: { query?: string; entityType?: string; limit?: number },
): Promise<CanonicalEntitySummary[]> {
  const params = new URLSearchParams();
  if (options?.query) {
    params.set('q', options.query);
  }
  if (options?.entityType && options.entityType !== 'all') {
    params.set('entity_type', options.entityType);
  }
  if (options?.limit) {
    params.set('limit', String(options.limit));
  }
  const response = await fetch(`${API_BASE}/knowledge/canonical-entities?${params.toString()}`);
  return handleResponse<CanonicalEntitySummary[]>(response);
}

export async function mergeCanonicalEntity(payload: CanonicalEntityMergePayload): Promise<CanonicalEntityDetail> {
  const response = await fetch(`${API_BASE}/knowledge/canonical-entities/merge`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  return handleResponse<CanonicalEntityDetail>(response);
}

export async function getManual(slug: string): Promise<ManualDocument> {
  const response = await fetch(`${API_BASE}/manuals/${slug}`);
  return handleResponse<ManualDocument>(response);
}

export async function createManualComment(
  slug: string,
  payload: ManualCommentCreatePayload,
): Promise<ManualComment> {
  const response = await fetch(`${API_BASE}/manuals/${slug}/comments`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  return handleResponse<ManualComment>(response);
}

export async function updateManualComment(
  slug: string,
  commentId: string,
  payload: ManualCommentUpdatePayload,
): Promise<ManualComment> {
  const response = await fetch(`${API_BASE}/manuals/${slug}/comments/${commentId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  return handleResponse<ManualComment>(response);
}

export async function runKnowledgeConsolidation(): Promise<KnowledgeConsolidationResult> {
  const response = await fetch(`${API_BASE}/knowledge/consolidate/run-sync`, {
    method: 'POST',
  });
  return handleResponse<KnowledgeConsolidationResult>(response);
}

export async function getGraphConsolidationSuggestions(limitPerAxis = 12): Promise<GraphConsolidationSuggestions> {
  const response = await fetch(`${API_BASE}/knowledge/consolidation/suggestions?limit_per_axis=${limitPerAxis}`);
  return handleResponse<GraphConsolidationSuggestions>(response);
}

export async function reviewGraphConsolidationSuggestion(
  payload: GraphConsolidationReviewPayload,
): Promise<GraphConsolidationReviewResult> {
  const response = await fetch(`${API_BASE}/knowledge/consolidation/review`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  return handleResponse<GraphConsolidationReviewResult>(response);
}

export function getDocumentDownloadUrl(
  documentId: string,
  versionId?: string,
  disposition: 'attachment' | 'inline' = 'attachment',
): string {
  const params = new URLSearchParams();
  if (versionId) {
    params.set('version_id', versionId);
  }
  if (disposition !== 'attachment') {
    params.set('disposition', disposition);
  }
  const query = params.toString();
  return query
    ? `${API_BASE}/documents/${documentId}/download?${query}`
    : `${API_BASE}/documents/${documentId}/download`;
}

export async function downloadDocument(documentId: string, versionId?: string): Promise<Blob> {
  const url = getDocumentDownloadUrl(documentId, versionId, 'attachment');
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }
  return response.blob();
}

export async function downloadAsset(documentId: string, assetId: string): Promise<Blob> {
  const response = await fetch(`${API_BASE}/documents/${documentId}/assets/${assetId}/download`);
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }
  return response.blob();
}

export async function uploadDocument(file: File, externalId?: string, autoSubmit = true): Promise<UploadResponse> {
  const formData = new FormData();
  formData.append('file', file);
  formData.append('auto_submit', String(autoSubmit));
  if (externalId) {
    formData.append('external_id', externalId);
  }

  const response = await fetch(`${API_BASE}/documents/upload`, {
    method: 'POST',
    body: formData,
  });
  return handleResponse<UploadResponse>(response);
}

export async function getJobs(limit = 100): Promise<Job[]> {
  const response = await fetch(`${API_BASE}/jobs?limit=${limit}`);
  return handleResponse<Job[]>(response);
}

export async function getJob(id: string): Promise<Job> {
  const response = await fetch(`${API_BASE}/jobs/${id}`);
  return handleResponse<Job>(response);
}

export async function getTopicProposals(includeConsolidated = false): Promise<KnowledgeTopicProposal[]> {
  const response = await fetch(
    `${API_BASE}/knowledge/topic-proposals?include_consolidated=${includeConsolidated}`,
  );
  return handleResponse<KnowledgeTopicProposal[]>(response);
}

export async function rejectTopicProposal(proposalId: string): Promise<KnowledgeTopicProposal> {
  const response = await fetch(`${API_BASE}/knowledge/topic-proposals/${proposalId}/reject`, {
    method: 'POST',
  });
  return handleResponse<KnowledgeTopicProposal>(response);
}

export async function resolveTopicProposal(
  proposalId: string,
  payload: TopicProposalResolutionPayload,
): Promise<KnowledgeDocumentUnit | KnowledgeTopicProposal> {
  if (payload.action === 'reject') {
    return rejectTopicProposal(proposalId);
  }
  const response = await fetch(`${API_BASE}/knowledge/topic-proposals/${proposalId}/approve`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  return handleResponse<KnowledgeDocumentUnit>(response);
}

export async function createKnowledgeTopic(payload: TopicCreatePayload): Promise<KnowledgeTopicSummary> {
  const response = await fetch(`${API_BASE}/knowledge/topics`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  return handleResponse<KnowledgeTopicSummary>(response);
}

export async function addDocumentUnitTopicAssignment(
  documentUnitId: string,
  payload: TopicAssignmentUpsertPayload,
): Promise<KnowledgeDocumentUnit> {
  const response = await fetch(`${API_BASE}/knowledge/document-units/${documentUnitId}/topic-assignments`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  return handleResponse<KnowledgeDocumentUnit>(response);
}

export async function deleteDocumentUnitTopicAssignment(
  documentUnitId: string,
  assignmentId: string,
): Promise<KnowledgeDocumentUnit> {
  const response = await fetch(
    `${API_BASE}/knowledge/document-units/${documentUnitId}/topic-assignments/${assignmentId}`,
    { method: 'DELETE' },
  );
  return handleResponse<KnowledgeDocumentUnit>(response);
}
