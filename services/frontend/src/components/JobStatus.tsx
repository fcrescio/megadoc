import { useJobs } from '../hooks/useJobs';
import type { Job } from '../types';

function JobStatus() {
  const { data: jobs, isLoading } = useJobs(20);

  const getStatusColor = (job: Job) => {
    if (job.is_stale) {
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

  const getStatusLabel = (job: Job) => {
    if (job.is_stale) {
      return 'stale';
    }
    return job.status;
  };

  const formatActivityTime = (job: Job) => {
    const timestamp = job.started_at ?? job.created_at;
    return new Date(timestamp).toLocaleString();
  };

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
    <div>
      <h2 className="text-xl font-semibold text-white mb-4">Lavori Recenti</h2>
      {jobs && jobs.length === 0 ? (
        <p className="text-slate-400">Nessun lavoro trovato.</p>
      ) : (
        <div className="bg-white/5 border border-white/10 rounded-[24px] shadow-[0_18px_60px_rgba(2,6,23,0.35)] divide-y divide-white/10 overflow-hidden backdrop-blur-md">
          {jobs?.map((job: Job) => (
            <div key={job.id} className="p-4">
              <div className="flex items-center justify-between">
                <div>
                  <p className="font-mono text-sm text-slate-100">{job.id}</p>
                  <p className="text-xs text-slate-400">Documento: {job.document_id}</p>
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
                  {job.is_stale && job.stale_reason && (
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
