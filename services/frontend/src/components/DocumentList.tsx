import { useDocuments } from '../hooks/useDocuments';
import type { Document } from '../types';
import { Virtuoso } from 'react-virtuoso';

interface Props {
  onSelectDocument: (id: string) => void;
}

function DocumentRow({
  doc,
  onSelect,
}: {
  doc: Document;
  onSelect: (id: string) => void;
}) {
  return (
    <button
      onClick={() => onSelect(doc.id)}
      className="w-full p-4 hover:bg-white/5 text-left transition-colors border-b border-white/10"
    >
      <div className="flex items-center justify-between">
        <div>
          <p className="font-medium text-slate-100">{doc.original_filename}</p>
          {doc.external_id && (
            <p className="text-sm text-slate-400">ID: {doc.external_id}</p>
          )}
        </div>
        <div className="text-right">
          <p className="text-sm text-slate-400">
            {new Date(doc.created_at).toLocaleDateString()}
          </p>
          <p className="text-xs text-slate-500">
            {(doc.size_bytes / 1024).toFixed(1)} KB
          </p>
        </div>
      </div>
    </button>
  );
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
        Errore nel caricamento dei documenti: {(error as Error).message}
      </div>
    );
  }

  return (
    <div className="mb-8">
      <h2 className="text-xl font-semibold text-white mb-4">Documenti</h2>
      {documents && documents.length === 0 ? (
        <p className="text-slate-400">Nessun documento trovato.</p>
      ) : (
        <div className="bg-white/5 border border-white/10 rounded-[24px] shadow-[0_18px_60px_rgba(2,6,23,0.35)] overflow-hidden backdrop-blur-md">
          <Virtuoso
            style={{ height: 'min(70vh, 600px)' }}
            totalCount={documents?.length ?? 0}
            itemContent={(index) => (
              <DocumentRow doc={documents![index]} onSelect={onSelectDocument} />
            )}
            increaseViewportBy={{ top: 200, bottom: 200 }}
          />
        </div>
      )}
    </div>
  );
}

export default DocumentList;
