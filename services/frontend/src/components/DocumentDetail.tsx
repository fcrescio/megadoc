import { useEffect, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { DocumentVersion, DocumentAsset, KnowledgeDocumentUnit } from '../types';
import {
  useDocument,
  useDocumentVersions,
  useDocumentOCR,
  useDocumentAssets,
  useDocumentKnowledge,
} from '../hooks/useDocuments';
import { downloadDocument, downloadAsset } from '../api/client';

interface Props {
  documentId: string;
  onBack: () => void;
  initialTab?: 'info' | 'ocr' | 'knowledge' | 'versions' | 'assets';
}

function DocumentDetail({ documentId, onBack, initialTab = 'info' }: Props) {
  const [activeTab, setActiveTab] = useState<'info' | 'ocr' | 'knowledge' | 'versions' | 'assets'>(initialTab);

  const { data: docData, isLoading: docLoading } = useDocument(documentId);
  const { data: versions } = useDocumentVersions(documentId);
  const { data: ocrResult, isLoading: ocrLoading } = useDocumentOCR(documentId);
  const { data: knowledge, isLoading: knowledgeLoading } = useDocumentKnowledge(documentId);
  const { data: assets } = useDocumentAssets(documentId);

  useEffect(() => {
    setActiveTab(initialTab);
  }, [documentId, initialTab]);

  if (docLoading) {
    return (
      <div className="animate-pulse space-y-4">
        <div className="h-8 bg-gray-200 rounded w-1/3"></div>
        <div className="h-32 bg-gray-200 rounded"></div>
      </div>
    );
  }

  const handleDownload = async (versionId?: string) => {
    try {
      const blob = await downloadDocument(documentId, versionId);
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = docData?.original_filename ?? 'document.pdf';
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      alert('Download failed');
    }
  };

  const handleDownloadAsset = async (assetId: string) => {
    try {
      const blob = await downloadAsset(documentId, assetId);
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `asset-${assetId}`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      alert('Download failed');
    }
  };

  return (
    <div>
      <button
        onClick={onBack}
        className="mb-4 text-blue-600 hover:text-blue-800 flex items-center"
      >
        ← Back to documents
      </button>

      <div className="bg-white rounded-lg shadow">
        <div className="border-b">
          <nav className="flex -mb-px">
            {(['info', 'ocr', 'knowledge', 'versions', 'assets'] as const).map((tab) => (
              <button
                key={tab}
                onClick={() => setActiveTab(tab)}
                className={`px-4 py-2 text-sm font-medium border-b-2 ${
                  activeTab === tab
                    ? 'border-blue-500 text-blue-600'
                    : 'border-transparent text-gray-500 hover:text-gray-700'
                }`}
              >
                {tab.charAt(0).toUpperCase() + tab.slice(1)}
              </button>
            ))}
          </nav>
        </div>

        <div className="p-6">
          {activeTab === 'info' && docData && (
            <div className="space-y-4">
              <h2 className="text-xl font-semibold">{docData.original_filename}</h2>
              <div className="grid grid-cols-2 gap-4 text-sm">
                <div>
                  <span className="text-gray-500">Document ID:</span>
                  <p className="font-mono">{documentId}</p>
                </div>
                {docData.external_id && (
                  <div>
                    <span className="text-gray-500">External ID:</span>
                    <p>{docData.external_id}</p>
                  </div>
                )}
                <div>
                  <span className="text-gray-500">Size:</span>
                  <p>{(docData.size_bytes / 1024).toFixed(1)} KB</p>
                </div>
                <div>
                  <span className="text-gray-500">Created:</span>
                  <p>{new Date(docData.created_at).toLocaleString()}</p>
                </div>
              </div>
              <button
                onClick={() => handleDownload()}
                className="px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700"
              >
                Download PDF
              </button>
            </div>
          )}

          {activeTab === 'ocr' && (
            <div>
              {ocrLoading ? (
                <div className="animate-pulse space-y-4">
                  <div className="h-4 bg-gray-200 rounded w-1/4"></div>
                  <div className="h-32 bg-gray-200 rounded"></div>
                </div>
              ) : ocrResult ? (
                <div>
                  <div className="mb-4 text-sm text-gray-500">
                    Engine: {ocrResult.engine_name} {ocrResult.engine_version} |{' '}
                    Pages: {ocrResult.page_count}
                  </div>
                  <div className="border rounded-lg p-4 markdown-body bg-gray-50 max-h-96 overflow-y-auto">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>
                      {ocrResult.markdown_text || 'No markdown content'}
                    </ReactMarkdown>
                  </div>
                </div>
              ) : (
                <p className="text-gray-500">No OCR result available yet.</p>
              )}
            </div>
          )}

          {activeTab === 'knowledge' && (
            <div>
              {knowledgeLoading ? (
                <div className="animate-pulse space-y-4">
                  <div className="h-4 bg-gray-200 rounded w-1/4"></div>
                  <div className="h-32 bg-gray-200 rounded"></div>
                </div>
              ) : knowledge && knowledge.scan_units.length > 0 ? (
                <div className="space-y-6">
                  {knowledge.scan_units.map((scanUnit) => (
                    <div key={scanUnit.id} className="border rounded-lg overflow-hidden">
                      <div className="bg-gray-50 px-4 py-3 border-b">
                        <div className="flex flex-wrap items-center justify-between gap-3">
                          <div>
                            <p className="font-medium text-gray-900">Scan unit</p>
                            <p className="font-mono text-xs text-gray-500">{scanUnit.id}</p>
                          </div>
                          <div className="flex flex-wrap gap-2 text-xs">
                            <span className="px-2 py-1 rounded-full bg-blue-50 text-blue-700">
                              {scanUnit.status}
                            </span>
                            <span className="px-2 py-1 rounded-full bg-gray-100 text-gray-700">
                              {scanUnit.page_count} pages
                            </span>
                            {scanUnit.classification_confidence !== null && (
                              <span className="px-2 py-1 rounded-full bg-emerald-50 text-emerald-700">
                                class {(scanUnit.classification_confidence * 100).toFixed(0)}%
                              </span>
                            )}
                          </div>
                        </div>
                      </div>

                      <div className="divide-y">
                        {scanUnit.document_units.map((unit: KnowledgeDocumentUnit) => (
                          <div key={unit.id} className="p-4 space-y-3">
                            <div className="flex flex-wrap items-start justify-between gap-3">
                              <div>
                                <h3 className="font-semibold text-gray-900">
                                  Unit {unit.ordinal}: {unit.document_type_code ?? 'unknown'}
                                </h3>
                                <p className="text-sm text-gray-500">
                                  Pages {unit.start_page}-{unit.end_page} · {unit.review_status}
                                  {unit.document_type_confidence !== null &&
                                    ` · ${(unit.document_type_confidence * 100).toFixed(0)}% confidence`}
                                </p>
                              </div>
                              <p className="font-mono text-xs text-gray-400">{unit.id}</p>
                            </div>

                            {unit.extracted_summary && (
                              <p className="text-sm text-gray-700 bg-amber-50 border border-amber-100 rounded p-3">
                                {unit.extracted_summary}
                              </p>
                            )}

                            <div>
                              <p className="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-2">
                                Topics
                              </p>
                              {unit.topic_assignments.length > 0 ? (
                                <div className="flex flex-wrap gap-2">
                                  {unit.topic_assignments.map((assignment) => (
                                    <span
                                      key={assignment.id}
                                      title={assignment.rationale ?? undefined}
                                      className="px-2 py-1 rounded-full bg-indigo-50 text-indigo-700 text-xs"
                                    >
                                      {assignment.topic_title ?? assignment.topic_slug}
                                      {assignment.confidence !== null &&
                                        ` · ${(assignment.confidence * 100).toFixed(0)}%`}
                                    </span>
                                  ))}
                                </div>
                              ) : (
                                <p className="text-sm text-gray-500">No topic assignment.</p>
                              )}
                              {unit.proposal && (
                                <div className="mt-2">
                                  <span
                                    className="px-2 py-1 rounded-full bg-orange-50 text-orange-700 text-xs"
                                    title={unit.proposal.rationale ?? undefined}
                                  >
                                    Proposed: {unit.proposal.proposed_title} · {unit.proposal.proposal_status}
                                  </span>
                                </div>
                              )}
                            </div>

                            <div>
                              <p className="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-2">
                                Entities
                              </p>
                              {unit.entities.length > 0 ? (
                                <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                                  {unit.entities.map((entity) => (
                                    <div key={entity.id} className="border rounded p-2 bg-white">
                                      <p className="text-xs text-gray-500">{entity.entity_type}</p>
                                      <p className="text-sm text-gray-900 truncate" title={entity.entity_value}>
                                        {entity.entity_value}
                                      </p>
                                      {entity.normalized_value && (
                                        <p className="text-xs text-gray-400 truncate" title={entity.normalized_value}>
                                          {entity.normalized_value}
                                        </p>
                                      )}
                                    </div>
                                  ))}
                                </div>
                              ) : (
                                <p className="text-sm text-gray-500">No entities extracted.</p>
                              )}
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-gray-500">No knowledge result available yet.</p>
              )}
            </div>
          )}

          {activeTab === 'versions' && (
            <div>
              {versions && versions.length === 0 ? (
                <p className="text-gray-500">No versions found.</p>
              ) : (
                <table className="min-w-full divide-y divide-gray-200">
                  <thead>
                    <tr>
                      <th className="px-4 py-2 text-left text-sm font-medium text-gray-500">Version</th>
                      <th className="px-4 py-2 text-left text-sm font-medium text-gray-500">Created</th>
                      <th className="px-4 py-2 text-left text-sm font-medium text-gray-500">Actions</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y">
                    {versions?.map((v: DocumentVersion) => (
                      <tr key={v.id}>
                        <td className="px-4 py-2 text-sm">{v.version_number}</td>
                        <td className="px-4 py-2 text-sm text-gray-500">
                          {new Date(v.created_at).toLocaleString()}
                        </td>
                        <td className="px-4 py-2 text-sm">
                          <button
                            onClick={() => handleDownload(v.id)}
                            className="text-blue-600 hover:text-blue-800"
                          >
                            Download
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          )}

          {activeTab === 'assets' && (
            <div>
              {assets && assets.length === 0 ? (
                <p className="text-gray-500">No assets found.</p>
              ) : (
                <table className="min-w-full divide-y divide-gray-200">
                  <thead>
                    <tr>
                      <th className="px-4 py-2 text-left text-sm font-medium text-gray-500">Type</th>
                      <th className="px-4 py-2 text-left text-sm font-medium text-gray-500">Created</th>
                      <th className="px-4 py-2 text-left text-sm font-medium text-gray-500">Actions</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y">
                    {assets?.map((a: DocumentAsset) => (
                      <tr key={a.id}>
                        <td className="px-4 py-2 text-sm">{a.asset_type}</td>
                        <td className="px-4 py-2 text-sm text-gray-500">
                          {new Date(a.created_at).toLocaleString()}
                        </td>
                        <td className="px-4 py-2 text-sm">
                          <button
                            onClick={() => handleDownloadAsset(a.id)}
                            className="text-blue-600 hover:text-blue-800"
                          >
                            Download
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default DocumentDetail;
