import { useQuery } from '@tanstack/react-query';
import type { Job } from '../types';
import { getJobs, getJob, getBackgroundActivity } from '../api/client';

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

export function useBackgroundActivity(enabled = true) {
  return useQuery({
    queryKey: ['background-activity'],
    queryFn: () => getBackgroundActivity(),
    enabled,
    refetchInterval: (query) => {
      const data = query.state.data;
      if (!enabled) return false;
      if (!data) return 5000;
      return data.active_count > 0 ? 3000 : 15000;
    },
    staleTime: 2000,
  });
}
