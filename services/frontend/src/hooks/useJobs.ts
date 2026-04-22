import { useQuery } from '@tanstack/react-query';
import { getJobs, getJob } from '../api/client';

export function useJobs(limit = 100) {
  return useQuery({
    queryKey: ['jobs', limit],
    queryFn: () => getJobs(limit),
    refetchInterval: 2000,
  });
}

export function useJob(id: string | null) {
  return useQuery({
    queryKey: ['job', id],
    queryFn: () => getJob(id!),
    enabled: !!id,
    refetchInterval: 2000,
  });
}
