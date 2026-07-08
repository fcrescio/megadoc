import { useBackgroundActivity } from '../hooks/useJobs';
import type { BackgroundActivityJob } from '../types';

function JobStatus() {
  const { data: activity, isLoading } = useBackgroundActivity(true);

  const getStatusColor = (job: BackgroundActivityJob) => {
    if (job.is_possibly_stale) {
      return 'bg-rose-500/15 text-rose-200 ring-1 ring-rose-400/40';
    }
    const status = job.status;
    switch (status) {
      case 'queued':
        return 'bg-amber-500/15 text-amber-100 ring-1 ring-amber-400/30';
      case 'running':
        return 'bg-sky-500/15 text-sky-100 ring-1 ring-sky-400/30';
      case 'succeeded':
        return 'bg-emerald-500/15 text-emerald-100 ring-1 ring-emerald-400/30';
      case 'failed':
        return 'bg-rose-500/15 text-rose-200 ring-1 ring-rose-400/40';
      default:
        return 'bg-slate-500/15 text-slate-100 ring-1 ring-slate-400/30';
    }
  };

  const getStatusLabel = (job: BackgroundActivityJob) => {
    if (job.is_possibly_stale) {
      return 'appeso';
    }
    return job.status;
  };

  const formatActivityTime = (job: BackgroundActivityJob) => {
    const timestamp = job.started_at ?? job.created_at;
    return new Date(timestamp).toLocaleString();
  };

  const jobs = activity?.active_jobs.length
    ? activity.active_jobs
    : activity?.possibly_stale_jobs.length
      ? activity.possibly_stale_jobs
      : activity?.recent_jobs ?? [];

  if (isLoading) {
    return (
      <div className="animate-pulse space-y-2">
        <div className="h-4 bg-gray-200 rounded w-1/4"></div>
        {[1, 2, 3].map((i) => (
          <div key={i} className="h-10 bg-gray-200 rounded"></div>
        ))}
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-xl font-semibold text-white">Lavori background</h2>
        <p className="mt-1 text-sm text-slate-400">
          {activity?.is_idle ? 'Sistema idle: nessun job attivo non appeso.' : `${activity?.active_count ?? 0} job attivi.`}
          {activity && activity.possibly_stale_count > 0 ? ` ${activity.possibly_stale_count} job risultano appesi.` : ''}
        </p>
      </div>

      {activity && (
        <div className="grid gap-3 md:grid-cols-3">
          {Object.entries(activity.pipelines).map(([name, pipeline]) => (
            <div key={name} className="rounded-2xl border border-slate-700 bg-slate-800 p-4">
              <p className="text-sm font-medium text-white">
                {name === 'ingestion' ? 'Ingestione' : name === 'knowledge' ? 'Knowledge' : 'Specialisti'}
              </p>
              <div className="mt-3 flex flex-wrap gap-2 text-xs">
                <span className="rounded-full bg-cyan-400/10 px-2 py-1 text-cyan-100">{pipeline.active} attivi</span>
                <span className="rounded-full bg-amber-400/10 px-2 py-1 text-amber-100">{pipeline.possibly_stale} appesi</span>
                <span className="rounded-full bg-emerald-400/10 px-2 py-1 text-emerald-100">{pipeline.done} completati</span>
                <span className="rounded-full bg-rose-400/10 px-2 py-1 text-rose-100">{pipeline.failed} falliti</span>
              </div>
            </div>
          ))}
        </div>
      )}

      {jobs && jobs.length === 0 ? (
        <p className="text-slate-400">Nessun lavoro trovato.</p>
      ) : (
        <div className="border border-slate-700 rounded-lg bg-slate-800 divide-y divide-slate-700 overflow-hidden">
          {jobs?.map((job: BackgroundActivityJob) => (
            <div key={job.id} className="p-4">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm font-medium text-slate-100">{job.label}</p>
                  <p className="font-mono text-xs text-slate-500">{job.id}</p>
                  <p className="text-xs text-slate-400">Documento: {job.document_id ?? 'n/d'}</p>
                  <p className="text-xs text-slate-500 mt-1">
                    {job.started_at ? 'Iniziato' : 'Creato'}: {formatActivityTime(job)}
                  </p>
                </div>
                <div className="text-right">
                  <span
                    className={`px-2 py-1 rounded text-xs font-medium uppercase tracking-[0.18em] ${getStatusColor(job)}`}
                  >
                    {getStatusLabel(job)}
                  </span>
                  {job.is_possibly_stale && job.stale_reason && (
                    <p className="text-xs text-rose-300 mt-1">{job.stale_reason}</p>
                  )}
                  {job.error_message && (
                    <p className="text-xs text-rose-300 mt-1">{job.error_message}</p>
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default JobStatus;
