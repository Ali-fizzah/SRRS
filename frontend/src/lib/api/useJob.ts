"use client";

import { useQuery } from "@tanstack/react-query";

import { apiGet, type Schemas } from "@/lib/api/client";

type Job = Schemas["JobOut"];

export function isJobFinished(job: Job | undefined): boolean {
  return job?.status === "DONE" || job?.status === "FAILED";
}

/** Poll a background job every 1.5 s until it finishes (plan §10). */
export function useJob(jobId: number | undefined) {
  return useQuery({
    queryKey: ["job", jobId],
    queryFn: () => apiGet<Job>(`/jobs/${jobId}`),
    enabled: jobId !== undefined,
    refetchInterval: (q) => (isJobFinished(q.state.data) ? false : 1500),
  });
}
