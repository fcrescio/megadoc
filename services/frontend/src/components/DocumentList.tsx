import { memo } from 'react';
import { useDocuments } from '../hooks/useDocuments';
import type { Document } from '../types';
import { Virtuoso } from 'react-virtuoso';

interface Props {
  onSelectDocument: (id: string) => void;
}

const DocumentRow = memo(function DocumentRow({ doc, onSelect }: { doc: Document; onSelect: (id: string) => void }) {
  const tags: { label: string; color: string }[] = [];
  if (doc.rotation_applied != null && doc.rotation_applied !== 0) {
    tags.push({ label: `Ruotato ${doc.rotation_applied}°`, color: 'bg-amber-500/20 text-amber-300 border-amber-600/30' });
  }
  if (doc.page_order_reversed) {
    tags.push({ label: 'Ordine invertito', color: 'bg-orange-500/20 text-orange-300 border-orange-600/30' });
  }
  if (doc.document_unit_count > 0) {
    tags.push({ label: `${doc.document_unit_count} documenti`, color: 'bg-sky-500/20 text-sky-300 border-sky-600/30' });
  }
  if (doc.scan_unit_count > 1) {
    tags.push({ label: `${doc.scan_unit_count} scansioni`, color: 'bg-indigo-500/20 text-indigo-300 border-indigo-600/30' });
  }
  if (doc.ingestion_status === 'failed') {
    tags.push({ label: 'OCR fallito', color: 'bg-red-500/20 text-red-300 border-red-600/30' });
  }

  return (
    <button
      onClick={() => onSelect(doc.id)}
      className="w-full p-4 hover:bg-slate-700 text-left border-b border-slate-700"
    >
      <div className="flex items-center justify-between">
        <div className="min-w-0">
          <p className="font-medium text-slate-100 truncate">{doc.original_filename}</p>
          {doc.external_id && (
            <p className="text-sm text-slate-400">ID: {doc.external_id}</p>
          )}
          {tags.length > 0 && (
            <div className="flex flex-wrap gap-1.5 mt-1.5">
              {tags.map((tag) => (
                <span
                  key={tag.label}
                  className={`inline-flex items-center px-2 py-0.5 text-xs font-medium rounded-full border ${tag.color}`}
                >
                  {tag.label}
                </span>
              ))}
            </div>
          )}
        </div>
        <div className="text-right shrink-0 ml-4">
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
});

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
        <div className="border border-slate-700 rounded-lg bg-slate-800 overflow-hidden">
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
