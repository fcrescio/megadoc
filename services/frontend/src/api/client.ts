const API_BASE = '';

async function handleResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const error = await response.text();
    throw new Error(error || `HTTP ${response.status}`);
  }
  return response.json();
}

export async function getDocuments(limit = 100): Promise<unknown[]> {
  const response = await fetch(`${API_BASE}/documents?limit=${limit}`);
  return handleResponse(response);
}

export async function getDocument(id: string): Promise<unknown> {
  const response = await fetch(`${API_BASE}/documents/${id}`);
  return handleResponse(response);
}

export async function getDocumentVersions(documentId: string): Promise<unknown[]> {
  const response = await fetch(`${API_BASE}/documents/${documentId}/versions`);
  return handleResponse(response);
}

export async function getDocumentAssets(documentId: string): Promise<unknown[]> {
  const response = await fetch(`${API_BASE}/documents/${documentId}/assets`);
  return handleResponse(response);
}

export async function getDocumentOCR(documentId: string): Promise<unknown> {
  const response = await fetch(`${API_BASE}/documents/${documentId}/ocr`);
  return handleResponse(response);
}

export async function downloadDocument(documentId: string, versionId?: string): Promise<Blob> {
  const url = versionId
    ? `${API_BASE}/documents/${documentId}/download?version_id=${versionId}`
    : `${API_BASE}/documents/${documentId}/download`;
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

export async function uploadDocument(file: File, externalId?: string, autoSubmit = true): Promise<unknown> {
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
  return handleResponse(response);
}

export async function getJobs(limit = 100): Promise<unknown[]> {
  const response = await fetch(`${API_BASE}/jobs?limit=${limit}`);
  return handleResponse(response);
}

export async function getJob(id: string): Promise<unknown> {
  const response = await fetch(`${API_BASE}/jobs/${id}`);
  return handleResponse(response);
}
