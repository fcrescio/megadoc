import { useQuery } from '@tanstack/react-query';
import type { Job } from '../types';
import { getJobs, getJob } from '../api/client';

export function useJobs(limit = 100) {
  return useQuery<Job[]>({
    queryKey: ['jobs', limit],
    queryFn: () => getJobs(limit),
    refetchInterval: 2000,
  });
}

export function useJob(id: string | null) {
  return useQuery<Job | null>({
    queryKey: ['job', id],
    queryFn: () => getJob(id!),
    enabled: !!id,
    refetchInterval: 2000,
  });
}
