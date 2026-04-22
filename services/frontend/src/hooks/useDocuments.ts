import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  getDocuments,
  getDocument,
  getDocumentVersions,
  getDocumentAssets,
  getDocumentOCR,
  uploadDocument,
} from '../api/client';

export function useDocuments(limit = 100) {
  return useQuery({
    queryKey: ['documents', limit],
    queryFn: () => getDocuments(limit),
  });
}

export function useDocument(id: string | null) {
  return useQuery({
    queryKey: ['document', id],
    queryFn: () => getDocument(id!),
    enabled: !!id,
  });
}

export function useDocumentVersions(documentId: string | null) {
  return useQuery({
    queryKey: ['versions', documentId],
    queryFn: () => getDocumentVersions(documentId!),
    enabled: !!documentId,
  });
}

export function useDocumentAssets(documentId: string | null) {
  return useQuery({
    queryKey: ['assets', documentId],
    queryFn: () => getDocumentAssets(documentId!),
    enabled: !!documentId,
  });
}

export function useDocumentOCR(documentId: string | null) {
  return useQuery({
    queryKey: ['ocr', documentId],
    queryFn: () => getDocumentOCR(documentId!),
    enabled: !!documentId,
  });
}

export function useUploadDocument() {
  const queryClient = useQueryClient();

  return useQueryClient().utils.mutation({
    mutationFn: ({ file, externalId, autoSubmit }: { file: File; externalId?: string; autoSubmit?: boolean }) =>
      uploadDocument(file, externalId, autoSubmit),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['documents'] });
      queryClient.invalidateQueries({ queryKey: ['jobs'] });
    },
  });
}
