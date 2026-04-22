import { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import {
  useDocument,
  useDocumentVersions,
  useDocumentOCR,
  useDocumentAssets,
} from '../hooks/useDocuments';
import { downloadDocument, downloadAsset } from '../api/client';

interface Props {
  documentId: string;
  onBack: () => void;
}

function DocumentDetail({ documentId, onBack }: Props) {
  const [activeTab, setActiveTab] = useState<'info' | 'ocr' | 'versions' | 'assets'>('info');

  const { data: document, isLoading: docLoading } = useDocument(documentId);
  const { data: versions } = useDocumentVersions(documentId);
  const { data: ocrResult, isLoading: ocrLoading } = useDocumentOCR(documentId);
  const { data: assets } = useDocumentAssets(documentId);

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
      a.download = (document as { original_filename: string }).original_filename;
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
            {(['info', 'ocr', 'versions', 'assets'] as const).map((tab) => (
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
          {activeTab === 'info' && document && (
            <div className="space-y-4">
              <h2 className="text-xl font-semibold">{(document as { original_filename: string }).original_filename}</h2>
              <div className="grid grid-cols-2 gap-4 text-sm">
                <div>
                  <span className="text-gray-500">Document ID:</span>
                  <p className="font-mono">{documentId}</p>
                </div>
                {(document as { external_id: string | null }).external_id && (
                  <div>
                    <span className="text-gray-500">External ID:</span>
                    <p>{(document as { external_id: string }).external_id}</p>
                  </div>
                )}
                <div>
                  <span className="text-gray-500">Size:</span>
                  <p>{((document as { size_bytes: number }).size_bytes / 1024).toFixed(1)} KB</p>
                </div>
                <div>
                  <span className="text-gray-500">Created:</span>
                  <p>{new Date((document as { created_at: string }).created_at).toLocaleString()}</p>
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
                    Engine: {(ocrResult as { engine_name: string; engine_version: string }).engine_name}{' '}
                    {(ocrResult as { engine_version: string }).engine_version} |{' '}
                    Pages: {(ocrResult as { page_count: number }).page_count}
                  </div>
                  <div className="border rounded-lg p-4 markdown-body bg-gray-50 max-h-96 overflow-y-auto">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>
                      {(ocrResult as { markdown_text: string }).markdown_text || 'No markdown content'}
                    </ReactMarkdown>
                  </div>
                </div>
              ) : (
                <p className="text-gray-500">No OCR result available yet.</p>
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
                    {versions?.map((v: { id: string; version_number: number; created_at: string }) => (
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
                    {assets?.map((a: { id: string; asset_type: string; created_at: string }) => (
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
