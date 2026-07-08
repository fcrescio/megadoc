import { useMemo, useState } from 'react';
import { useBackgroundActivity } from '../hooks/useJobs';
import type { BackgroundActivityJob, BackgroundActivityPipeline } from '../types';

function formatAge(seconds: number) {
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  return `${hours}h ${minutes % 60}m`;
}

function pipelineLabel(key: string) {
  if (key === 'ingestion') return 'Ingestione';
  if (key === 'knowledge') return 'Knowledge';
  if (key === 'specialists') return 'Specialisti';
  return key;
}

function statusClass(status: string, stale = false) {
  if (stale) return 'border-amber-300/25 bg-amber-400/10 text-amber-100';
  if (['queued', 'pending'].includes(status)) return 'border-sky-300/25 bg-sky-400/10 text-sky-100';
  if (['processing', 'running'].includes(status)) return 'border-cyan-300/25 bg-cyan-400/10 text-cyan-100';
  if (['succeeded', 'completed'].includes(status)) return 'border-emerald-300/20 bg-emerald-400/10 text-emerald-100';
  if (status === 'failed') return 'border-rose-300/25 bg-rose-400/10 text-rose-100';
  return 'border-white/10 bg-white/5 text-slate-200';
}

function PipelineSummary({ name, pipeline }: { name: string; pipeline: BackgroundActivityPipeline }) {
  return (
    <div className="rounded-2xl border border-white/10 bg-white/5 p-3">
      <div className="flex items-center justify-between gap-2">
        <p className="text-sm font-medium text-white">{pipelineLabel(name)}</p>
        <span className="text-xs text-slate-400">{pipeline.total} recenti</span>
      </div>
      <div className="mt-2 flex flex-wrap gap-1.5 text-xs">
        <span className="rounded-full border border-cyan-300/20 bg-cyan-400/10 px-2 py-1 text-cyan-100">
          {pipeline.active} attivi
        </span>
        {pipeline.possibly_stale > 0 && (
          <span className="rounded-full border border-amber-300/20 bg-amber-400/10 px-2 py-1 text-amber-100">
            {pipeline.possibly_stale} appesi
          </span>
        )}
        {pipeline.failed > 0 && (
          <span className="rounded-full border border-rose-300/20 bg-rose-400/10 px-2 py-1 text-rose-100">
            {pipeline.failed} falliti
          </span>
        )}
        <span className="rounded-full border border-emerald-300/20 bg-emerald-400/10 px-2 py-1 text-emerald-100">
          {pipeline.done} completati
        </span>
      </div>
    </div>
  );
}

function JobRow({ job }: { job: BackgroundActivityJob }) {
  return (
    <div className="rounded-xl border border-white/10 bg-slate-950/50 p-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate text-sm font-medium text-white">{job.label}</p>
          <p className="mt-1 truncate font-mono text-xs text-slate-500">{job.id}</p>
          {job.document_id && (
            <p className="mt-1 truncate text-xs text-slate-400">Documento {job.document_id}</p>
          )}
        </div>
        <span className={`shrink-0 rounded-full border px-2 py-1 text-xs ${statusClass(job.status, job.is_possibly_stale)}`}>
          {job.is_possibly_stale ? 'appeso' : job.status}
        </span>
      </div>
      <div className="mt-2 flex flex-wrap gap-2 text-xs text-slate-400">
        <span>{pipelineLabel(job.pipeline)}</span>
        <span>eta {formatAge(job.age_seconds)}</span>
        {job.attempt_count > 0 && <span>try {job.attempt_count}</span>}
      </div>
      {(job.stale_reason || job.error_message) && (
        <p className="mt-2 text-xs text-amber-200">{job.error_message ?? job.stale_reason}</p>
      )}
    </div>
  );
}

export default function BackgroundActivityButton() {
  const [open, setOpen] = useState(false);
  const activity = useBackgroundActivity(true);
  const data = activity.data;

  const label = useMemo(() => {
    if (activity.isLoading && !data) return 'Controllo lavori...';
    if (!data) return 'Lavori non disponibili';
    if (data.active_count > 0) return `${data.active_count} lavori in corso`;
    if (data.possibly_stale_count > 0) return `Idle · ${data.possibly_stale_count} appesi`;
    return 'Idle';
  }, [activity.isLoading, data]);

  const activeTone = data?.active_count ? 'border-cyan-300/35 bg-cyan-400/15 text-cyan-100' : 'border-emerald-300/25 bg-emerald-400/10 text-emerald-100';
  const panelJobs = data?.active_jobs.length
    ? data.active_jobs
    : data?.possibly_stale_jobs.length
      ? data.possibly_stale_jobs
      : data?.recent_jobs.slice(0, 8) ?? [];

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        className={`w-full rounded-xl border px-3 py-2 text-left text-sm transition hover:bg-white/10 ${activeTone}`}
        title="Stato lavori background"
      >
        <span className="flex items-center justify-between gap-2">
          <span className="truncate">{label}</span>
          {data?.active_count ? (
            <span className="h-2 w-2 shrink-0 animate-pulse rounded-full bg-cyan-300" />
          ) : (
            <span className="h-2 w-2 shrink-0 rounded-full bg-emerald-300" />
          )}
        </span>
      </button>

      {open && (
        <div className="fixed inset-x-4 top-20 z-50 max-h-[80vh] overflow-y-auto rounded-3xl border border-cyan-300/15 bg-slate-900 p-4 shadow-2xl shadow-cyan-950/30 lg:left-24 lg:right-auto lg:w-[34rem]">
          <div className="flex items-start justify-between gap-3">
            <div>
              <p className="text-sm font-semibold text-white">Lavori background</p>
              <p className="mt-1 text-xs text-slate-400">
                {data?.is_idle ? 'Nessun job attivo non appeso.' : 'Il sistema sta ancora elaborando documenti.'}
              </p>
            </div>
            <button onClick={() => setOpen(false)} className="rounded-full border border-white/10 px-3 py-1.5 text-xs text-slate-300 hover:bg-white/10">
              Chiudi
            </button>
          </div>

          {data ? (
            <>
              <div className="mt-4 grid gap-2 md:grid-cols-3">
                {Object.entries(data.pipelines).map(([name, pipeline]) => (
                  <PipelineSummary key={name} name={name} pipeline={pipeline} />
                ))}
              </div>
              {data.possibly_stale_count > 0 && (
                <div className="mt-3 rounded-2xl border border-amber-300/20 bg-amber-400/10 p-3 text-xs text-amber-100">
                  Alcuni job risultano ancora attivi ma sono vecchi: li mostro separatamente come possibili stati appesi.
                </div>
              )}
              <div className="mt-4 space-y-2">
                <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">
                  {data.active_jobs.length ? 'In corso' : data.possibly_stale_jobs.length ? 'Possibili appesi' : 'Recenti'}
                </p>
                {panelJobs.length ? panelJobs.map((job) => <JobRow key={`${job.pipeline}:${job.id}`} job={job} />) : (
                  <p className="text-sm text-slate-400">Nessun lavoro recente.</p>
                )}
              </div>
            </>
          ) : (
            <p className="mt-4 text-sm text-slate-400">Stato non disponibile.</p>
          )}
        </div>
      )}
    </div>
  );
}
