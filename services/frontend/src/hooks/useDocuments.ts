import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import type { Document, DocumentVersion, DocumentAsset, OCRResult, UploadResponse } from '../types';
import {
  getDocuments,
  getDocument,
  getDocumentVersions,
  getDocumentAssets,
  getDocumentOCR,
  uploadDocument,
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
