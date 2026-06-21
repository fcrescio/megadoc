import { memo, useEffect } from 'react';
import { getDocumentDownloadUrl } from '../api/client';

interface CellMetadata {
  category: string;
  unitCode: string;
  subjectLabel: string;
  amount: number;
  tableId: string | null;
  rowId: string | null;
  column: string | null;
  rawValue: string | null;
  pageNumber: number | null;
  factType: string;
  isTotal: boolean;
  factCount?: number;
}

interface Props {
  documentId: string;
  pageNumber: number | null;
  metadata: CellMetadata | null;
  onClose: () => void;
}

function formatCurrency(value: number | null | undefined) {
  if (typeof value !== 'number') return '—';
  return new Intl.NumberFormat('it-IT', {
    style: 'currency',
    currency: 'EUR',
  }).format(value);
}

const PdfPageViewer = memo(function PdfPageViewer({ documentId, pageNumber, metadata, onClose }: Props) {
  const pdfUrl = getDocumentDownloadUrl(documentId, undefined, 'inline');
  // Append #page=N for browser PDF viewer navigation
  const pdfPageUrl = pageNumber != null ? `${pdfUrl}#page=${pageNumber}` : pdfUrl;

  // Close on Escape key
  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-slate-950/60" onClick={onClose}>
      <div
        className="flex h-full w-full max-w-2xl flex-col bg-slate-900 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex shrink-0 items-center justify-between border-b border-white/10 px-4 py-3">
          <div className="flex items-center gap-3">
            <p className="text-sm font-semibold text-white">
              {pageNumber != null ? `Pagina ${pageNumber}` : 'PDF'}
            </p>
            {metadata && (
              <span className="rounded-full bg-cyan-400/15 px-2 py-0.5 text-xs text-cyan-200">
                {metadata.category}
              </span>
            )}
          </div>
          <button
            onClick={onClose}
            className="rounded-full border border-white/10 px-3 py-1.5 text-xs text-slate-300 hover:bg-white/10"
          >
            Chiudi
          </button>
        </div>

        {/* PDF iframe */}
        <div className="min-h-0 flex-1 bg-slate-950">
          <iframe
            key={pdfPageUrl}
            src={pdfPageUrl}
            title={`PDF page ${pageNumber ?? ''}`}
            className="h-full w-full"
          />
        </div>

        {/* Metadata panel */}
        {metadata && (
          <div className="shrink-0 border-t border-white/10 bg-slate-800/80 px-4 py-3">
            <div className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm">
              <div className="flex justify-between">
                <span className="text-slate-400">Soggetto</span>
                <span className="text-white">{metadata.subjectLabel}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-400">Unità</span>
                <span className="text-white">{metadata.unitCode}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-400">Categoria</span>
                <span className="text-white">{metadata.category}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-400">Importo</span>
                <span className="font-semibold text-cyan-200">{formatCurrency(metadata.amount)}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-400">Tipo</span>
                <span className="text-white">{metadata.factType}</span>
              </div>
              {metadata.factCount && metadata.factCount > 1 && (
                <div className="flex justify-between">
                  <span className="text-slate-400">Righe aggregate</span>
                  <span className="rounded-full bg-amber-400/15 px-2 py-0.5 text-xs text-amber-200">
                    {metadata.factCount}
                  </span>
                </div>
              )}
              <div className="flex justify-between">
                <span className="text-slate-400">Pagina</span>
                <span className="font-mono text-white">
                  {metadata.pageNumber != null ? metadata.pageNumber : '—'}
                </span>
              </div>
              {metadata.isTotal && (
                <div className="flex justify-between">
                  <span className="text-slate-400">Totale</span>
                  <span className="rounded-full bg-amber-400/15 px-2 py-0.5 text-xs text-amber-200">Si</span>
                </div>
              )}
              {metadata.rawValue != null && (
                <div className="flex justify-between">
                  <span className="text-slate-400">Valore originale</span>
                  <span className="text-white">{metadata.rawValue}</span>
                </div>
              )}
            </div>
            {(metadata.tableId || metadata.rowId) && (
              <div className="mt-2 flex flex-wrap gap-2 border-t border-white/10 pt-2 text-xs text-slate-500">
                {metadata.tableId && <span>Tabella: {metadata.tableId}</span>}
                {metadata.rowId && <span>Riga: {metadata.rowId}</span>}
                {metadata.column && <span>Colonna: {metadata.column}</span>}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
});

export default PdfPageViewer;
