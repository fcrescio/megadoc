import { useState } from 'react';
import { useSystemStatus } from '../hooks/useDocuments';

function statusClasses(status: 'ok' | 'degraded' | 'error') {
  if (status === 'ok') {
    return 'border-emerald-400/25 bg-emerald-400/10 text-emerald-100';
  }
  if (status === 'degraded') {
    return 'border-amber-400/25 bg-amber-400/10 text-amber-100';
  }
  return 'border-rose-400/25 bg-rose-400/10 text-rose-100';
}

function statusLabel(status: 'ok' | 'degraded' | 'error') {
  if (status === 'ok') return 'Backend OK';
  if (status === 'degraded') return 'Backend degradati';
  return 'Backend offline';
}

export default function SystemStatusButton() {
  const [open, setOpen] = useState(false);
  const { data, isLoading, error } = useSystemStatus(open);

  const effectiveStatus = error ? 'error' : (data?.status ?? 'degraded');
  const badgeClasses = statusClasses(effectiveStatus);

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        className={`px-4 py-2 rounded-full text-sm font-medium border ${badgeClasses}`}
        aria-expanded={open}
      >
        <span className="flex items-center gap-2">
          <span className={`h-2.5 w-2.5 rounded-full ${effectiveStatus === 'ok' ? 'bg-emerald-300' : effectiveStatus === 'degraded' ? 'bg-amber-300' : 'bg-rose-300'}`} />
          {!open && !data ? 'Stato backend' : isLoading ? 'Verifica dei backend…' : error ? 'Stato backend non disponibile' : statusLabel(effectiveStatus)}
        </span>
      </button>

      {open && (
        <div className="absolute right-0 mt-3 w-[22rem] rounded-lg border border-slate-700 bg-slate-800 p-4 space-y-3 z-30">
          <div>
            <p className="text-xs uppercase tracking-[0.28em] text-cyan-300/75">Stato sistema</p>
            <p className="mt-1 text-sm text-slate-300">
              Se LLM o OCR remoto non rispondono, qui lo vedi subito. Il fallback non è più invisibile.
            </p>
          </div>

          {error || !data ? (
            <div className="rounded-2xl border border-rose-400/20 bg-rose-400/10 px-4 py-3 text-sm text-rose-100">
              Impossibile leggere lo stato del sistema.
            </div>
          ) : (
            <>
              <div className="grid grid-cols-3 gap-2 text-xs">
                <div className={`rounded-2xl px-3 py-2 border ${statusClasses(data.database as 'ok' | 'degraded' | 'error')}`}>DB {data.database}</div>
                <div className={`rounded-2xl px-3 py-2 border ${statusClasses(data.redis as 'ok' | 'degraded' | 'error')}`}>Redis {data.redis}</div>
                <div className={`rounded-2xl px-3 py-2 border ${statusClasses(data.storage as 'ok' | 'degraded' | 'error')}`}>Storage {data.storage}</div>
              </div>

              {[data.ocr_backend, data.llm_backend].map((backend) => (
                <div key={backend.name} className="rounded-2xl border border-white/10 bg-white/5 p-4">
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <p className="text-sm font-semibold text-white">{backend.name}</p>
                      <p className="text-xs text-slate-400 break-all">{backend.model ?? 'modello non configurato'}</p>
                    </div>
                    <span className={`rounded-full border px-2.5 py-1 text-xs font-semibold ${statusClasses(backend.status)}`}>
                      {backend.status}
                    </span>
                  </div>
                  <p className="mt-2 text-xs text-slate-400 break-all">{backend.endpoint ?? 'backend locale'}</p>
                  <div className="mt-3 space-y-1 text-sm text-slate-200">
                    <p>Raggiungibile: {backend.server_reachable ? 'sì' : 'no'}</p>
                    <p>Modello disponibile: {backend.model_available === null ? 'n/a' : backend.model_available ? 'sì' : 'no'}</p>
                    <p>Latenza: {backend.latency_ms === null ? 'n/a' : `${backend.latency_ms} ms`}</p>
                  </div>
                  {backend.detail && (
                    <p className="mt-3 text-xs text-slate-400">{backend.detail}</p>
                  )}
                </div>
              ))}
            </>
          )}
        </div>
      )}
    </div>
  );
}
