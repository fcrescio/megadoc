import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import type {
  Document,
  DocumentVersion,
  DocumentAsset,
  OCRResult,
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
  KnowledgeContextSummary,
  ContextAccountingSubject,
  ContextAccountingComparison,
  KnowledgeGraphStats,
  KnowledgeNodeSummary,
  KnowledgeNodeDetail,
  KnowledgeAssertion,
  ManualDocument,
  ManualComment,
  ManualCommentCreatePayload,
  ManualCommentUpdatePayload,
  KnowledgeConsolidationResult,
  GraphConsolidationSuggestions,
  GraphConsolidationReviewPayload,
  GraphConsolidationReviewResult,
  KnowledgeTopicProposal,
  TopicAssignmentUpsertPayload,
  TopicCreatePayload,
  TopicProposalResolutionPayload,
} from '../types';
import {
  getDocuments,
  getSystemStatus,
  getDocument,
  getDocumentVersions,
  getDocumentAssets,
  getDocumentOCR,
  getDocumentKnowledge,
  ensureDocumentKnowledge,
  ensureDocumentSpecialists,
  getKnowledgeTopic,
  searchKnowledge,
  getSpecialistUtilityBills,
  getSpecialistAccountingStatements,
  getKnowledgeEntities,
  getKnowledgeEntityDetail,
  getCanonicalEntities,
  mergeCanonicalEntity,
  getKnowledgeContexts,
  getContextAccountingSubjects,
  compareContextAccounting,
  getKnowledgeGraphStats,
  getKnowledgeNodes,
  getKnowledgeNode,
  getKnowledgeAssertions,
  getManual,
  createManualComment,
  updateManualComment,
  getKnowledgeTopics,
  runKnowledgeConsolidation,
  getGraphConsolidationSuggestions,
  reviewGraphConsolidationSuggestion,
  uploadDocument,
  getTopicProposals,
  rejectTopicProposal,
  resolveTopicProposal,
  createKnowledgeTopic,
  addDocumentUnitTopicAssignment,
  deleteDocumentUnitTopicAssignment,
} from '../api/client';

export function useDocuments(limit = 100) {
  return useQuery<Document[]>({
    queryKey: ['documents', limit],
    queryFn: () => getDocuments(limit),
  });
}

export function useSystemStatus() {
  return useQuery<SystemStatus>({
    queryKey: ['system-status'],
    queryFn: () => getSystemStatus(),
    refetchInterval: 15000,
    staleTime: 5000,
  });
}

export function useDocument(id: string | null) {
  return useQuery<Document | null>({
    queryKey: ['document', id],
    queryFn: () => getDocument(id!),
    enabled: !!id,
  });
}

export function useDocumentVersions(documentId: string | null) {
  return useQuery<DocumentVersion[]>({
    queryKey: ['versions', documentId],
    queryFn: () => getDocumentVersions(documentId!),
    enabled: !!documentId,
  });
}

export function useDocumentAssets(documentId: string | null) {
  return useQuery<DocumentAsset[]>({
    queryKey: ['assets', documentId],
    queryFn: () => getDocumentAssets(documentId!),
    enabled: !!documentId,
  });
}

export function useDocumentOCR(documentId: string | null) {
  return useQuery<OCRResult | null>({
    queryKey: ['ocr', documentId],
    queryFn: () => getDocumentOCR(documentId!),
    enabled: !!documentId,
  });
}

export function useDocumentKnowledge(documentId: string | null) {
  return useQuery<DocumentKnowledge | null>({
    queryKey: ['knowledge', documentId],
    queryFn: () => getDocumentKnowledge(documentId!),
    enabled: !!documentId,
  });
}

export function useEnsureDocumentKnowledge() {
  const queryClient = useQueryClient();
  return useMutation<{ id: string }, Error, string>({
    mutationFn: (documentId) => ensureDocumentKnowledge(documentId),
    onSuccess: (_, documentId) => {
      queryClient.invalidateQueries({ queryKey: ['knowledge', documentId] });
      queryClient.invalidateQueries({ queryKey: ['knowledge'] });
      queryClient.invalidateQueries({ queryKey: ['jobs'] });
    },
  });
}

export function useEnsureDocumentSpecialists() {
  const queryClient = useQueryClient();
  return useMutation<
    { scan_unit_id: string; created_jobs: number; jobs: { id: string; specialist_type: string; status: string }[] },
    Error,
    string
  >({
    mutationFn: (documentId) => ensureDocumentSpecialists(documentId),
    onSuccess: (_, documentId) => {
      queryClient.invalidateQueries({ queryKey: ['knowledge', documentId] });
      queryClient.invalidateQueries({ queryKey: ['knowledge'] });
    },
  });
}

export function useKnowledgeTopics(includeInactive = false, topicKind?: string) {
  return useQuery<KnowledgeTopicSummary[]>({
    queryKey: ['knowledge-topics', includeInactive, topicKind],
    queryFn: () => getKnowledgeTopics(includeInactive, topicKind),
  });
}

export function useKnowledgeTopic(topicId: string | null) {
  return useQuery<KnowledgeTopicDetail | null>({
    queryKey: ['knowledge-topic', topicId],
    queryFn: () => getKnowledgeTopic(topicId!),
    enabled: !!topicId,
  });
}

export function useKnowledgeSearch(
  query: string,
  options?: {
    includeInactive?: boolean;
    topicKind?: string;
    topicClass?: string;
    limit?: number;
  },
) {
  return useQuery<KnowledgeSearchResult>({
    queryKey: ['knowledge-search', query, options?.includeInactive, options?.topicKind, options?.topicClass, options?.limit],
    queryFn: () => searchKnowledge(query, options),
    enabled: query.trim().length >= 2,
  });
}

export function useSpecialistUtilityBills(options?: {
  query?: string;
  issuer?: string;
  paymentStatus?: string;
  overdueOnly?: boolean;
  limit?: number;
}) {
  return useQuery<{ total: number; items: SpecialistUtilityBillSummary[] }>({
    queryKey: ['specialist-utility-bills', options?.query, options?.issuer, options?.paymentStatus, options?.overdueOnly, options?.limit],
    queryFn: () => getSpecialistUtilityBills(options),
  });
}

export function useSpecialistAccountingStatements(options?: {
  query?: string;
  statementType?: string;
  checkStatus?: string;
  limit?: number;
}) {
  return useQuery<{ total: number; items: SpecialistAccountingStatementSummary[] }>({
    queryKey: ['specialist-accounting-statements', options?.query, options?.statementType, options?.checkStatus, options?.limit],
    queryFn: () => getSpecialistAccountingStatements(options),
  });
}

export function useKnowledgeEntities(options?: { query?: string; entityType?: string; limit?: number }) {
  return useQuery<KnowledgeEntitySummary[]>({
    queryKey: ['knowledge-entities', options?.query, options?.entityType, options?.limit],
    queryFn: () => getKnowledgeEntities(options),
  });
}

export function useKnowledgeEntityDetail(entityType: string | null, entityKey: string | null) {
  return useQuery<KnowledgeEntityDetail | null>({
    queryKey: ['knowledge-entity-detail', entityType, entityKey],
    queryFn: () => getKnowledgeEntityDetail(entityType!, entityKey!),
    enabled: !!entityType && !!entityKey,
  });
}

export function useCanonicalEntities(options?: { query?: string; entityType?: string; limit?: number }) {
  return useQuery<CanonicalEntitySummary[]>({
    queryKey: ['canonical-entities', options?.query, options?.entityType, options?.limit],
    queryFn: () => getCanonicalEntities(options),
  });
}

export function useMergeCanonicalEntity() {
  const queryClient = useQueryClient();
  return useMutation<CanonicalEntityDetail, Error, CanonicalEntityMergePayload>({
    mutationFn: (payload) => mergeCanonicalEntity(payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['knowledge-entities'] });
      queryClient.invalidateQueries({ queryKey: ['knowledge-entity-detail'] });
      queryClient.invalidateQueries({ queryKey: ['canonical-entities'] });
      queryClient.invalidateQueries({ queryKey: ['knowledge-search'] });
      queryClient.invalidateQueries({ queryKey: ['knowledge-graph'] });
      queryClient.invalidateQueries({ queryKey: ['knowledge-nodes'] });
      queryClient.invalidateQueries({ queryKey: ['knowledge-node'] });
      queryClient.invalidateQueries({ queryKey: ['knowledge-assertions'] });
    },
  });
}

export function useKnowledgeContexts(options?: { query?: string; entityType?: string; limit?: number }) {
  return useQuery<KnowledgeContextSummary[]>({
    queryKey: ['knowledge-contexts', options?.query, options?.entityType, options?.limit],
    queryFn: () => getKnowledgeContexts(options),
  });
}

export function useContextAccountingSubjects(
  contextId: string | null,
  options?: { query?: string; accountKey?: string; limit?: number },
) {
  return useQuery<ContextAccountingSubject[]>({
    queryKey: ['context-accounting-subjects', contextId, options?.query, options?.accountKey, options?.limit],
    queryFn: () => getContextAccountingSubjects(contextId!, options),
    enabled: !!contextId,
  });
}

export function useContextAccountingComparison(
  contextId: string | null,
  options: {
    subject: string;
    accountingRole: string;
    periodAFrom: string;
    periodATo: string;
    periodBFrom: string;
    periodBTo: string;
    accountKey?: string;
  },
) {
  return useQuery<ContextAccountingComparison>({
    queryKey: ['context-accounting-comparison', contextId, options],
    queryFn: () => compareContextAccounting(contextId!, options),
    enabled: !!contextId
      && options.subject.trim().length >= 2
      && !!options.periodAFrom
      && !!options.periodATo
      && !!options.periodBFrom
      && !!options.periodBTo,
  });
}

export function useKnowledgeGraphStats() {
  return useQuery<KnowledgeGraphStats>({
    queryKey: ['knowledge-graph'],
    queryFn: () => getKnowledgeGraphStats(),
  });
}

export function useKnowledgeNodes(options?: { query?: string; nodeKind?: string; limit?: number }) {
  return useQuery<KnowledgeNodeSummary[]>({
    queryKey: ['knowledge-nodes', options?.query, options?.nodeKind, options?.limit],
    queryFn: () => getKnowledgeNodes(options),
  });
}

export function useKnowledgeNode(nodeId: string | null) {
  return useQuery<KnowledgeNodeDetail | null>({
    queryKey: ['knowledge-node', nodeId],
    queryFn: () => getKnowledgeNode(nodeId!),
    enabled: !!nodeId,
  });
}

export function useKnowledgeAssertions(options?: { query?: string; predicate?: string; nodeId?: string; limit?: number }) {
  return useQuery<KnowledgeAssertion[]>({
    queryKey: ['knowledge-assertions', options?.query, options?.predicate, options?.nodeId, options?.limit],
    queryFn: () => getKnowledgeAssertions(options),
  });
}

export function useManual(slug: string | null) {
  return useQuery<ManualDocument | null>({
    queryKey: ['manual', slug],
    queryFn: () => getManual(slug!),
    enabled: !!slug,
  });
}

export function useCreateManualComment() {
  const queryClient = useQueryClient();
  return useMutation<ManualComment, Error, { slug: string; payload: ManualCommentCreatePayload }>({
    mutationFn: ({ slug, payload }) => createManualComment(slug, payload),
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ['manual', variables.slug] });
    },
  });
}

export function useUpdateManualComment() {
  const queryClient = useQueryClient();
  return useMutation<ManualComment, Error, { slug: string; commentId: string; payload: ManualCommentUpdatePayload }>({
    mutationFn: ({ slug, commentId, payload }) => updateManualComment(slug, commentId, payload),
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ['manual', variables.slug] });
    },
  });
}

export function useRunKnowledgeConsolidation() {
  const queryClient = useQueryClient();

  return useMutation<KnowledgeConsolidationResult, Error, void>({
    mutationFn: () => runKnowledgeConsolidation(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['knowledge-topics'] });
      queryClient.invalidateQueries({ queryKey: ['knowledge-topic'] });
      queryClient.invalidateQueries({ queryKey: ['knowledge'] });
      queryClient.invalidateQueries({ queryKey: ['knowledge-search'] });
      queryClient.invalidateQueries({ queryKey: ['knowledge-entities'] });
      queryClient.invalidateQueries({ queryKey: ['knowledge-entity-detail'] });
    },
  });
}

export function useGraphConsolidationSuggestions(limitPerAxis = 12) {
  return useQuery<GraphConsolidationSuggestions>({
    queryKey: ['graph-consolidation-suggestions', limitPerAxis],
    queryFn: () => getGraphConsolidationSuggestions(limitPerAxis),
  });
}

export function useReviewGraphConsolidationSuggestion() {
  const queryClient = useQueryClient();
  return useMutation<GraphConsolidationReviewResult, Error, GraphConsolidationReviewPayload>({
    mutationFn: (payload) => reviewGraphConsolidationSuggestion(payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['graph-consolidation-suggestions'] });
      queryClient.invalidateQueries({ queryKey: ['knowledge-topics'] });
      queryClient.invalidateQueries({ queryKey: ['knowledge-topic'] });
      queryClient.invalidateQueries({ queryKey: ['knowledge-search'] });
      queryClient.invalidateQueries({ queryKey: ['knowledge'] });
    },
  });
}

export function useUploadDocument() {
  const queryClient = useQueryClient();

  return useMutation<UploadResponse, Error, { file: File; externalId?: string; autoSubmit?: boolean }>({
    mutationFn: ({ file, externalId, autoSubmit }) => uploadDocument(file, externalId, autoSubmit),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['documents'] });
      queryClient.invalidateQueries({ queryKey: ['jobs'] });
    },
  });
}

export function useTopicProposals(includeConsolidated = false) {
  return useQuery<KnowledgeTopicProposal[]>({
    queryKey: ['topic-proposals', includeConsolidated],
    queryFn: () => getTopicProposals(includeConsolidated),
  });
}

export function useApproveTopicProposal() {
  const queryClient = useQueryClient();

  return useMutation<unknown, Error, { proposalId: string; payload: TopicProposalResolutionPayload }>({
    mutationFn: ({ proposalId, payload }) => resolveTopicProposal(proposalId, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['topic-proposals'] });
      queryClient.invalidateQueries({ queryKey: ['knowledge-topics'] });
      queryClient.invalidateQueries({ queryKey: ['knowledge-topic'] });
      queryClient.invalidateQueries({ queryKey: ['knowledge'] });
      queryClient.invalidateQueries({ queryKey: ['knowledge-search'] });
      queryClient.invalidateQueries({ queryKey: ['knowledge-entities'] });
      queryClient.invalidateQueries({ queryKey: ['knowledge-entity-detail'] });
    },
  });
}

export function useRejectTopicProposal() {
  const queryClient = useQueryClient();

  return useMutation<KnowledgeTopicProposal, Error, string>({
    mutationFn: (proposalId) => rejectTopicProposal(proposalId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['topic-proposals'] });
      queryClient.invalidateQueries({ queryKey: ['knowledge-topics'] });
      queryClient.invalidateQueries({ queryKey: ['knowledge-topic'] });
      queryClient.invalidateQueries({ queryKey: ['knowledge'] });
      queryClient.invalidateQueries({ queryKey: ['knowledge-search'] });
      queryClient.invalidateQueries({ queryKey: ['knowledge-entities'] });
      queryClient.invalidateQueries({ queryKey: ['knowledge-entity-detail'] });
    },
  });
}

export function useCreateKnowledgeTopic() {
  const queryClient = useQueryClient();
  return useMutation<KnowledgeTopicSummary, Error, TopicCreatePayload>({
    mutationFn: (payload) => createKnowledgeTopic(payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['knowledge-topics'] });
      queryClient.invalidateQueries({ queryKey: ['topic-proposals'] });
      queryClient.invalidateQueries({ queryKey: ['knowledge-search'] });
      queryClient.invalidateQueries({ queryKey: ['knowledge-entities'] });
      queryClient.invalidateQueries({ queryKey: ['knowledge-entity-detail'] });
    },
  });
}

export function useAddDocumentUnitTopicAssignment() {
  const queryClient = useQueryClient();
  return useMutation<unknown, Error, { documentUnitId: string; payload: TopicAssignmentUpsertPayload }>({
    mutationFn: ({ documentUnitId, payload }) => addDocumentUnitTopicAssignment(documentUnitId, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['knowledge'] });
      queryClient.invalidateQueries({ queryKey: ['knowledge-topic'] });
      queryClient.invalidateQueries({ queryKey: ['knowledge-topics'] });
      queryClient.invalidateQueries({ queryKey: ['topic-proposals'] });
      queryClient.invalidateQueries({ queryKey: ['knowledge-search'] });
      queryClient.invalidateQueries({ queryKey: ['knowledge-entities'] });
      queryClient.invalidateQueries({ queryKey: ['knowledge-entity-detail'] });
    },
  });
}

export function useDeleteDocumentUnitTopicAssignment() {
  const queryClient = useQueryClient();
  return useMutation<unknown, Error, { documentUnitId: string; assignmentId: string }>({
    mutationFn: ({ documentUnitId, assignmentId }) => deleteDocumentUnitTopicAssignment(documentUnitId, assignmentId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['knowledge'] });
      queryClient.invalidateQueries({ queryKey: ['knowledge-topic'] });
      queryClient.invalidateQueries({ queryKey: ['knowledge-topics'] });
      queryClient.invalidateQueries({ queryKey: ['knowledge-search'] });
      queryClient.invalidateQueries({ queryKey: ['knowledge-entities'] });
      queryClient.invalidateQueries({ queryKey: ['knowledge-entity-detail'] });
    },
  });
}
