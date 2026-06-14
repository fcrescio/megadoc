import { useEffect, useMemo, useState } from 'react';
import { useCorrectAccountingFact } from '../hooks/useDocuments';
import type {
  ContextAccountingComparison,
  ContextAccountingPeriodBreakdown,
  ContextAccountingSource,
} from '../types';

interface Props {
  comparison: ContextAccountingComparison;
  onClose: () => void;
}

function formatCurrency(value: number | null | undefined) {
  if (typeof value !== 'number') return 'n/d';
  return new Intl.NumberFormat('it-IT', { style: 'currency', currency: 'EUR' }).format(value);
}

function evidenceLabel(source: ContextAccountingSource) {
  const evidence = source.evidence_json ?? {};
  const column = typeof evidence.column === 'string' ? evidence.column : source.category_label;
  const rawValue = typeof evidence.raw_value === 'string' ? evidence.raw_value : String(source.amount);
  return `${column ?? 'Voce'}: ${rawValue}`;
}

function PeriodFacts({
  label,
  period,
  selectedId,
  onSelect,
}: {
  label: string;
  period: ContextAccountingPeriodBreakdown | null;
  selectedId: string | null;
  onSelect: (source: ContextAccountingSource) => void;
}) {
  if (!period) return <p className="text-sm text-slate-400">Periodo non disponibile.</p>;
  return (
    <div className="min-h-0 rounded-2xl border border-white/10 bg-slate-950/45 p-3">
      <div className="mb-3 flex items-center justify-between gap-2">
        <div>
          <p className="text-sm font-medium text-white">{label}</p>
          <p className="text-xs text-slate-400">{period.period_from} / {period.period_to}</p>
        </div>
        <span className={`rounded-full px-2 py-1 text-xs ${
          period.validation_status === 'validated'
            ? 'bg-emerald-400/15 text-emerald-100'
            : 'bg-amber-400/15 text-amber-100'
        }`}>
          {period.validation_status}
        </span>
      </div>
      <div className="mb-3 grid grid-cols-2 gap-2 text-xs">
        <div className="rounded-lg border border-white/10 p-2 text-slate-300">
          Componenti <span className="block text-sm text-white">{formatCurrency(period.component_total)}</span>
        </div>
        <div className="rounded-lg border border-white/10 p-2 text-slate-300">
          Totale riportato <span className="block text-sm text-white">{formatCurrency(period.reported_total)}</span>
        </div>
      </div>
      <p className="mb-2 text-xs uppercase tracking-wide text-slate-400">Totale estratto</p>
      {period.total_sources.length ? period.total_sources.map((source) => (
        <button
          key={source.fact_id}
          onClick={() => onSelect(source)}
          className={`mb-2 w-full rounded-lg border p-2 text-left text-xs ${
            selectedId === source.fact_id
              ? 'border-cyan-300/35 bg-cyan-400/15'
              : 'border-white/10 bg-white/5 hover:bg-white/10'
          }`}
        >
          <span className="block text-white">{evidenceLabel(source)}</span>
          <span className="text-slate-400">{source.original_filename} · pag. {source.start_page}-{source.end_page}</span>
        </button>
      )) : <p className="mb-3 text-xs text-amber-100">Totale assente o ambiguo.</p>}
      <p className="mb-2 mt-3 text-xs uppercase tracking-wide text-slate-400">Componenti</p>
      <div className="max-h-[38vh] space-y-2 overflow-y-auto pr-1">
        {period.categories.flatMap((category) => category.sources.map((source) => (
          <button
            key={source.fact_id}
            onClick={() => onSelect(source)}
            className={`w-full rounded-lg border p-2 text-left text-xs ${
              selectedId === source.fact_id
                ? 'border-cyan-300/35 bg-cyan-400/15'
                : 'border-white/10 bg-white/5 hover:bg-white/10'
            }`}
          >
            <span className="flex justify-between gap-2 text-white">
              <span className="truncate">{category.category_label}</span>
              <span>{formatCurrency(source.amount)}</span>
            </span>
            <span className="mt-1 block truncate text-slate-400">{evidenceLabel(source)}</span>
          </button>
        )))}
      </div>
    </div>
  );
}

function AccountingReconciliationModal({ comparison, onClose }: Props) {
  const correction = useCorrectAccountingFact();
  const allSources = useMemo(
    () => [comparison.period_a, comparison.period_b].flatMap((period) => (
      period ? [...period.total_sources, ...period.categories.flatMap((category) => category.sources)] : []
    )),
    [comparison.period_a, comparison.period_b],
  );
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const selected = allSources.find((source) => source.fact_id === selectedId) ?? null;
  const [amount, setAmount] = useState('');
  const [categoryLabel, setCategoryLabel] = useState('');
  const [isTotal, setIsTotal] = useState(false);
  const [note, setNote] = useState('');
  const [actedBy, setActedBy] = useState('');

  useEffect(() => {
    if (!allSources.length) {
      setSelectedId(null);
    } else if (!selectedId || !allSources.some((source) => source.fact_id === selectedId)) {
      setSelectedId(allSources[0].fact_id);
    }
  }, [allSources]);

  useEffect(() => {
    if (!selected) return;
    setAmount(String(selected.amount));
    setCategoryLabel(selected.category_label ?? '');
    setIsTotal(selected.is_total);
    setNote('');
  }, [selected]);

  const saveCorrection = () => {
    if (!selected) return;
    const parsedAmount = Number(amount.replace(',', '.'));
    if (!Number.isFinite(parsedAmount)) return;
    correction.mutate({
      factId: selected.fact_id,
      payload: {
        corrected_amount: parsedAmount,
        corrected_category_label: categoryLabel.trim() || selected.category_label || undefined,
        corrected_is_total: isTotal,
        note: note.trim() || undefined,
        acted_by: actedBy.trim() || undefined,
      },
    });
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/80 p-4 backdrop-blur-sm" onClick={onClose}>
      <div className="flex max-h-[92vh] w-full max-w-7xl flex-col rounded-3xl border border-amber-300/20 bg-slate-900 p-5 shadow-2xl" onClick={(event) => event.stopPropagation()}>
        <div className="mb-4 flex shrink-0 flex-wrap items-start justify-between gap-3">
          <div>
            <p className="text-lg font-semibold text-white">Riconciliazione tabella contabile</p>
            <p className="mt-1 text-sm text-slate-400">
              {comparison.selected_subject?.subject_label ?? comparison.requested_subject} · correggi colonne o cifre mantenendo il valore sorgente.
            </p>
          </div>
          <button onClick={onClose} className="rounded-full border border-white/10 px-4 py-2 text-sm text-slate-200">Chiudi</button>
        </div>
        <div className="grid min-h-0 flex-1 gap-3 lg:grid-cols-[minmax(18rem,1fr)_minmax(18rem,1fr)_22rem]">
          <PeriodFacts label="Periodo A" period={comparison.period_a} selectedId={selectedId} onSelect={(source) => setSelectedId(source.fact_id)} />
          <PeriodFacts label="Periodo B" period={comparison.period_b} selectedId={selectedId} onSelect={(source) => setSelectedId(source.fact_id)} />
          <div className="min-h-0 overflow-y-auto rounded-2xl border border-cyan-300/15 bg-slate-950/45 p-4">
            <p className="mb-3 text-sm font-medium text-white">Correzione selezionata</p>
            {selected ? (
              <div className="space-y-3 text-sm">
                <div className="rounded-xl border border-white/10 bg-white/5 p-3 text-xs text-slate-300">
                  <p className="text-white">{selected.original_filename}</p>
                  <p className="mt-1">Pagine {selected.start_page}-{selected.end_page}</p>
                  <p className="mt-2 text-cyan-100">{evidenceLabel(selected)}</p>
                  {selected.review_status === 'human_reviewed' && <p className="mt-2 text-emerald-200">Gia revisionato manualmente</p>}
                </div>
                <label className="block text-xs text-slate-300">
                  Voce / colonna normalizzata
                  <input value={categoryLabel} onChange={(event) => setCategoryLabel(event.target.value)} className="mt-1 w-full rounded-lg border border-white/10 bg-slate-950 px-3 py-2 text-sm text-white" />
                </label>
                <label className="block text-xs text-slate-300">
                  Importo utilizzato
                  <input type="number" step="0.01" value={amount} onChange={(event) => setAmount(event.target.value)} className="mt-1 w-full rounded-lg border border-white/10 bg-slate-950 px-3 py-2 text-sm text-white" />
                </label>
                <label className="flex items-center gap-2 text-xs text-slate-300">
                  <input type="checkbox" checked={isTotal} onChange={(event) => setIsTotal(event.target.checked)} />
                  Questa riga e il totale del periodo
                </label>
                <input value={actedBy} onChange={(event) => setActedBy(event.target.value)} placeholder="Revisore (facoltativo)" className="w-full rounded-lg border border-white/10 bg-slate-950 px-3 py-2 text-sm text-white" />
                <textarea value={note} onChange={(event) => setNote(event.target.value)} placeholder="Motivo della correzione" className="h-20 w-full rounded-lg border border-white/10 bg-slate-950 p-3 text-sm text-white" />
                <button
                  onClick={saveCorrection}
                  disabled={correction.isPending}
                  className="w-full rounded-full border border-cyan-300/25 bg-cyan-400/15 px-4 py-2 text-sm text-cyan-100 disabled:opacity-50"
                >
                  {correction.isPending ? 'Salvataggio...' : 'Applica e ricalcola'}
                </button>
                {correction.isError && <p className="text-xs text-rose-200">{correction.error.message}</p>}
                {correction.isSuccess && <p className="text-xs text-emerald-200">Correzione registrata e fatti riproiettati.</p>}
              </div>
            ) : (
              <p className="text-sm text-slate-400">Seleziona una voce o un totale.</p>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

export default AccountingReconciliationModal;
