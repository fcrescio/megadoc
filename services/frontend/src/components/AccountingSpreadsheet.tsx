import { memo, useState } from 'react';
import { useDocumentAccountingTable } from '../hooks/useDocuments';
import type { AccountingTableData } from '../types';
import PdfPageViewer from './PdfPageViewer';

interface Props {
  documentId: string;
}

function formatCurrency(value: number | null | undefined) {
  if (typeof value !== 'number') return '—';
  return new Intl.NumberFormat('it-IT', {
    style: 'currency',
    currency: 'EUR',
  }).format(value);
}

function AccountingTableSpreadsheet({
  table,
  onCellClick,
  selectedCellKey,
}: {
  table: AccountingTableData;
  onCellClick: (rowIndex: number, col: string) => void;
  selectedCellKey: string | null;
}) {
  const { columns, rows, totals } = table;

  return (
    <div className="overflow-auto rounded-xl border border-white/10 bg-slate-950/60" style={{ maxHeight: '100%' }}>
      <table className="w-full text-sm">
        {/* Header row */}
        <thead>
          <tr>
            <th className="sticky left-0 top-0 z-20 min-w-[14rem] border-b border-r border-white/10 bg-slate-800 px-3 py-2 text-left text-xs font-semibold uppercase tracking-wide text-slate-400">
              Unità · Soggetto
            </th>
            {columns.map((col) => (
              <th
                key={col}
                className="sticky top-0 z-10 min-w-[8rem] border-b border-white/10 bg-slate-800 px-3 py-2 text-right text-xs font-semibold uppercase tracking-wide text-slate-400"
              >
                {col}
              </th>
            ))}
          </tr>
        </thead>
        {/* Body */}
        <tbody>
          {rows.map((row, rowIndex) => {
            const rowKey = row.account_key;
            return (
              <tr
                key={rowKey}
                className="border-b border-white/5 transition-colors hover:bg-white/5"
              >
                <td className="sticky left-0 z-10 border-r border-white/10 bg-slate-900 px-3 py-2">
                  <div className="flex items-center gap-2">
                    <span className="rounded bg-cyan-400/15 px-1.5 py-0.5 font-mono text-xs text-cyan-200">
                      {row.unit_code}
                    </span>
                    <span className="truncate text-white" title={row.subject_label}>
                      {row.subject_label}
                    </span>
                  </div>
                </td>
                {columns.map((col) => {
                  const cell = row.cells[col];
                  const cellKey = `${rowKey}:${col}`;
                  const isSelected = selectedCellKey === cellKey;
                  return (
                    <td
                      key={col}
                      onClick={() => cell && onCellClick(rowIndex, col)}
                      className={`px-3 py-2 text-right font-mono transition-colors ${
                        isSelected
                          ? 'bg-cyan-400/20 text-cyan-200'
                          : cell
                            ? 'cursor-pointer text-slate-200 hover:bg-cyan-400/10'
                            : 'text-slate-600'
                      }`}
                    >
                      {cell ? formatCurrency(cell.amount) : '—'}
                    </td>
                  );
                })}
              </tr>
            );
          })}
        </tbody>
        {/* Totals row */}
        <tfoot>
          <tr className="sticky bottom-0 border-t border-white/20 bg-slate-800">
            <td className="sticky left-0 z-10 border-r border-white/10 bg-slate-800 px-3 py-2 text-xs font-semibold uppercase tracking-wide text-slate-300">
              Totali
            </td>
            {columns.map((col) => (
              <td
                key={col}
                className="px-3 py-2 text-right font-mono text-sm font-semibold text-cyan-200"
              >
                {formatCurrency(totals[col])}
              </td>
            ))}
          </tr>
        </tfoot>
      </table>
    </div>
  );
}

const AccountingSpreadsheet = memo(function AccountingSpreadsheet({ documentId }: Props) {
  const { data, isLoading, error } = useDocumentAccountingTable(documentId);
  const [activeTableIndex, setActiveTableIndex] = useState(0);
  const [selectedCellKey, setSelectedCellKey] = useState<string | null>(null);
  const [showPdfViewer, setShowPdfViewer] = useState(false);
  const [pdfPageNumber, setPdfPageNumber] = useState<number | null>(null);
  const [pdfMetadata, setPdfMetadata] = useState<{
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
  } | null>(null);

  const tables = data?.tables ?? [];
  const stableActiveIndex = activeTableIndex < tables.length ? activeTableIndex : 0;

  const handleCellClick = (rowIndex: number, col: string) => {
    const table = tables[stableActiveIndex];
    if (!table) return;
    const row = table.rows[rowIndex];
    const cell = row.cells[col];
    if (!cell) return;
    const cellKey = `${row.account_key}:${col}`;
    setSelectedCellKey(cellKey);
    setPdfPageNumber(cell.evidence.page_number);
    setPdfMetadata({
      category: col,
      unitCode: row.unit_code,
      subjectLabel: row.subject_label,
      amount: cell.amount,
      tableId: cell.evidence.table_id,
      rowId: cell.evidence.row_id,
      column: cell.evidence.column,
      rawValue: cell.evidence.raw_value,
      pageNumber: cell.evidence.page_number,
      factType: cell.fact_type,
      isTotal: cell.is_total,
    });
    setShowPdfViewer(true);
  };

  const handleClosePdfViewer = () => {
    setShowPdfViewer(false);
    setSelectedCellKey(null);
    setPdfMetadata(null);
    setPdfPageNumber(null);
  };

  if (isLoading) {
    return (
      <div className="flex h-48 items-center justify-center">
        <div className="animate-pulse text-sm text-slate-500">Caricamento dati contabili...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
        Errore caricamento dati contabili: {error.message}
      </div>
    );
  }

  if (tables.length === 0) {
    return (
      <div className="flex h-48 items-center justify-center">
        <p className="text-sm text-slate-500">Nessun dato contabile disponibile per questo documento.</p>
      </div>
    );
  }

  const activeTable = tables[stableActiveIndex];

  return (
    <div className="flex h-full flex-col gap-3">
      {/* Document unit selector */}
      {tables.length > 1 && (
        <div className="flex shrink-0 flex-wrap gap-2">
          {tables.map((table, index) => (
            <button
              key={table.document_unit_id}
              onClick={() => {
                setActiveTableIndex(index);
                setSelectedCellKey(null);
              }}
              className={`rounded-full border px-3 py-1.5 text-xs font-medium transition ${
                index === stableActiveIndex
                  ? 'border-cyan-600 bg-cyan-500 text-white'
                  : 'border-slate-300 bg-white text-slate-700 hover:bg-slate-50'
              }`}
            >
              {table.title}
            </button>
          ))}
        </div>
      )}

      {/* Table info bar */}
      {activeTable && (
        <div className="flex shrink-0 items-center justify-between text-xs text-slate-500">
          <span>
            {activeTable.rows.length} unità · {activeTable.columns.length} categorie
            · pagine {activeTable.start_page}–{activeTable.end_page}
          </span>
        </div>
      )}

      {/* Spreadsheet */}
      {activeTable && (
        <div className="min-h-0 flex-1 overflow-hidden">
          <AccountingTableSpreadsheet
            table={activeTable}
            onCellClick={handleCellClick}
            selectedCellKey={selectedCellKey}
          />
        </div>
      )}

      {/* PDF viewer overlay */}
      {showPdfViewer && (
        <PdfPageViewer
          documentId={documentId}
          pageNumber={pdfPageNumber}
          metadata={pdfMetadata}
          onClose={handleClosePdfViewer}
        />
      )}
    </div>
  );
});

export default AccountingSpreadsheet;
