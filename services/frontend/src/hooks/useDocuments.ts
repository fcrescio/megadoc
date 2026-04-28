import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import type {
  Document,
  DocumentVersion,
  DocumentAsset,
  OCRResult,
  UploadResponse,
  DocumentKnowledge,
  KnowledgeTopicSummary,
  KnowledgeTopicDetail,
  KnowledgeSearchResult,
  KnowledgeEntitySummary,
  KnowledgeEntityDetail,
  KnowledgeConsolidationResult,
  KnowledgeTopicProposal,
  TopicAssignmentUpsertPayload,
  TopicCreatePayload,
  TopicProposalResolutionPayload,
} from '../types';
import {
  getDocuments,
  getDocument,
  getDocumentVersions,
  getDocumentAssets,
  getDocumentOCR,
  getDocumentKnowledge,
  ensureDocumentKnowledge,
  getKnowledgeTopic,
  searchKnowledge,
  getKnowledgeEntities,
  getKnowledgeEntityDetail,
  getKnowledgeTopics,
  runKnowledgeConsolidation,
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
