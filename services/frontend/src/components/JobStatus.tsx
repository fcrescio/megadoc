import { useJobs } from '../hooks/useJobs';

function JobStatus() {
  const { data: jobs, isLoading } = useJobs(20);

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'queued':
        return 'bg-yellow-100 text-yellow-800';
      case 'running':
        return 'bg-blue-100 text-blue-800';
      case 'succeeded':
        return 'bg-green-100 text-green-800';
      case 'failed':
        return 'bg-red-100 text-red-800';
      default:
        return 'bg-gray-100 text-gray-800';
    }
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
      <h2 className="text-xl font-semibold text-gray-900 mb-4">Recent Jobs</h2>
      {jobs && jobs.length === 0 ? (
        <p className="text-gray-500">No jobs found.</p>
      ) : (
        <div className="bg-white rounded-lg shadow divide-y">
          {jobs?.map((job: { id: string; document_id: string; status: string; created_at: string; error_message: string | null }) => (
            <div key={job.id} className="p-4">
              <div className="flex items-center justify-between">
                <div>
                  <p className="font-mono text-sm">{job.id}</p>
                  <p className="text-xs text-gray-500">Document: {job.document_id}</p>
                </div>
                <div className="text-right">
                  <span
                    className={`px-2 py-1 rounded text-xs font-medium ${getStatusColor(job.status)}`}
                  >
                    {job.status}
                  </span>
                  {job.error_message && (
                    <p className="text-xs text-red-500 mt-1">{job.error_message}</p>
                  )}
                </div>
              </div>
              <p className="text-xs text-gray-400 mt-1">
                {new Date(job.created_at).toLocaleString()}
              </p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default JobStatus;
