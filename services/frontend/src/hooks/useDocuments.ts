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
  KnowledgeConsolidationResult,
  KnowledgeTopicProposal,
} from '../types';
import {
  getDocuments,
  getDocument,
  getDocumentVersions,
  getDocumentAssets,
  getDocumentOCR,
  getDocumentKnowledge,
  getKnowledgeTopic,
  getKnowledgeTopics,
  runKnowledgeConsolidation,
  uploadDocument,
  getTopicProposals,
  approveTopicProposal,
  rejectTopicProposal,
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

export function useKnowledgeTopics(includeInactive = false) {
  return useQuery<KnowledgeTopicSummary[]>({
    queryKey: ['knowledge-topics', includeInactive],
    queryFn: () => getKnowledgeTopics(includeInactive),
  });
}

export function useKnowledgeTopic(topicId: string | null) {
  return useQuery<KnowledgeTopicDetail | null>({
    queryKey: ['knowledge-topic', topicId],
    queryFn: () => getKnowledgeTopic(topicId!),
    enabled: !!topicId,
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

  return useMutation<KnowledgeTopicSummary, Error, string>({
    mutationFn: (proposalId) => approveTopicProposal(proposalId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['topic-proposals'] });
      queryClient.invalidateQueries({ queryKey: ['knowledge-topics'] });
      queryClient.invalidateQueries({ queryKey: ['knowledge-topic'] });
      queryClient.invalidateQueries({ queryKey: ['knowledge'] });
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
    },
  });
}
