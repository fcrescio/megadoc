import { useQuery } from '@tanstack/react-query';
import type { Job } from '../types';
import { getJobs, getJob } from '../api/client';

export function useJobs(limit = 100, enabled = true) {
  return useQuery<Job[]>({
    queryKey: ['jobs', limit],
    queryFn: () => getJobs(limit),
    refetchInterval: enabled ? 5000 : false,
    enabled,
  });
}

export function useJob(id: string | null) {
  return useQuery<Job | null>({
    queryKey: ['job', id],
    queryFn: () => getJob(id!),
    enabled: !!id,
    refetchInterval: 5000,
  });
}
