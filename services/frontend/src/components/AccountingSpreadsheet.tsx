import { memo, useState } from 'react';
import { useDocumentAccountingTable } from '../hooks/useDocuments';
import type { AccountingTableData, AccountingTableCell } from '../types';

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

function formatEvidenceValue(value: unknown): string {
  if (value === null || value === undefined) return '—';
  return String(value);
}

function CellDetailPanel({
  cell,
  category,
  unitCode,
  subjectLabel,
  onClose,
}: {
  cell: AccountingTableCell;
  category: string;
  unitCode: string;
  subjectLabel: string;
  onClose: () => void;
}) {
  return (
    <div className="rounded-xl border border-cyan-300/20 bg-slate-800/80 p-4">
      <div className="mb-3 flex items-center justify-between">
        <p className="text-sm font-semibold text-cyan-200">Dettaglio cella</p>
        <button onClick={onClose} className="rounded-full border border-white/10 px-3 py-1 text-xs text-slate-300 hover:bg-white/10">
          Chiudi
        </button>
      </div>
      <div className="grid gap-2 text-sm">
        <div className="flex justify-between">
          <span className="text-slate-400">Soggetto</span>
          <span className="text-white">{subjectLabel}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-slate-400">Unità</span>
          <span className="text-white">{unitCode}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-slate-400">Categoria</span>
          <span className="text-white">{category}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-slate-400">Importo</span>
          <span className="font-semibold text-cyan-200">{formatCurrency(cell.amount)}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-slate-400">Tipo</span>
          <span className="text-white">{cell.fact_type}</span>
        </div>
        {cell.is_total && (
          <div className="flex justify-between">
            <span className="text-slate-400">Totale</span>
            <span className="rounded-full bg-amber-400/15 px-2 py-0.5 text-xs text-amber-200">Si</span>
          </div>
        )}
        <hr className="border-white/10" />
        <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">Evidenza</p>
        <div className="flex justify-between">
          <span className="text-slate-400">Tabella</span>
          <span className="font-mono text-xs text-white">{formatEvidenceValue(cell.evidence.table_id)}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-slate-400">Riga</span>
          <span className="font-mono text-xs text-white">{formatEvidenceValue(cell.evidence.row_id)}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-slate-400">Colonna</span>
          <span className="text-white">{formatEvidenceValue(cell.evidence.column)}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-slate-400">Pagina</span>
          <span className="font-mono text-white">
            {cell.evidence.page_number != null ? cell.evidence.page_number : '—'}
          </span>
        </div>
        <div className="flex justify-between">
          <span className="text-slate-400">Valore originale</span>
          <span className="text-white">{formatEvidenceValue(cell.evidence.raw_value)}</span>
        </div>
      </div>
    </div>
  );
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
  const [selectedCell, setSelectedCell] = useState<{
    cell: AccountingTableCell;
    category: string;
    unitCode: string;
    subjectLabel: string;
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
    setSelectedCell({
      cell,
      category: col,
      unitCode: row.unit_code,
      subjectLabel: row.subject_label,
    });
  };

  const handleCloseDetail = () => {
    setSelectedCellKey(null);
    setSelectedCell(null);
  };

  if (isLoading) {
    return (
      <div className="flex h-48 items-center justify-center">
        <div className="animate-pulse text-sm text-slate-400">Caricamento dati contabili...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-xl border border-red-300/20 bg-red-400/10 p-4 text-sm text-red-200">
        Errore caricamento dati contabili: {error.message}
      </div>
    );
  }

  if (tables.length === 0) {
    return (
      <div className="flex h-48 items-center justify-center">
        <p className="text-sm text-slate-400">Nessun dato contabile disponibile per questo documento.</p>
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
                handleCloseDetail();
              }}
              className={`rounded-full border px-3 py-1.5 text-xs font-medium transition ${
                index === stableActiveIndex
                  ? 'border-cyan-300/35 bg-cyan-400/15 text-cyan-100'
                  : 'border-white/10 bg-white/5 text-slate-300 hover:bg-white/10'
              }`}
            >
              {table.title}
            </button>
          ))}
        </div>
      )}

      {/* Table info bar */}
      {activeTable && (
        <div className="flex shrink-0 items-center justify-between text-xs text-slate-400">
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

      {/* Cell detail panel */}
      {selectedCell && (
        <div className="shrink-0">
          <CellDetailPanel
            cell={selectedCell.cell}
            category={selectedCell.category}
            unitCode={selectedCell.unitCode}
            subjectLabel={selectedCell.subjectLabel}
            onClose={handleCloseDetail}
          />
        </div>
      )}
    </div>
  );
});

export default AccountingSpreadsheet;
