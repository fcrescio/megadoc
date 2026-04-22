import { useDocuments } from '../hooks/useDocuments';
import type { Document } from '../types';

interface Props {
  onSelectDocument: (id: string) => void;
}

function DocumentList({ onSelectDocument }: Props) {
  const { data: documents, isLoading, error } = useDocuments();

  if (isLoading) {
    return (
      <div className="mb-8">
        <div className="animate-pulse space-y-4">
          <div className="h-4 bg-gray-200 rounded w-1/4"></div>
          {[1, 2, 3].map((i) => (
            <div key={i} className="h-16 bg-gray-200 rounded"></div>
          ))}
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="mb-8 p-4 bg-red-50 text-red-700 rounded-lg">
        Error loading documents: {(error as Error).message}
      </div>
    );
  }

  return (
    <div className="mb-8">
      <h2 className="text-xl font-semibold text-gray-900 mb-4">Documents</h2>
      {documents && documents.length === 0 ? (
        <p className="text-gray-500">No documents found.</p>
      ) : (
        <div className="bg-white rounded-lg shadow divide-y">
          {documents?.map((doc: Document) => (
            <button
              key={doc.id}
              onClick={() => onSelectDocument(doc.id)}
              className="w-full p-4 hover:bg-gray-50 text-left transition-colors"
            >
              <div className="flex items-center justify-between">
                <div>
                  <p className="font-medium text-gray-900">{doc.original_filename}</p>
                  {doc.external_id && (
                    <p className="text-sm text-gray-500">ID: {doc.external_id}</p>
                  )}
                </div>
                <div className="text-right">
                  <p className="text-sm text-gray-500">
                    {new Date(doc.created_at).toLocaleDateString()}
                  </p>
                  <p className="text-xs text-gray-400">
                    {(doc.size_bytes / 1024).toFixed(1)} KB
                  </p>
                </div>
              </div>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

export default DocumentList;
