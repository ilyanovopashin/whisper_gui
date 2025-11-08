import { useEffect, useRef, useState } from 'react';

export type JobStatus = 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled';

export interface JobLogEntry {
  timestamp: string;
  message: string;
}

export interface JobResultLinks {
  srt?: string;
  vtt?: string;
  json?: string;
}

export interface JobResponse {
  id: string;
  status: JobStatus;
  progress?: number;
  eta_seconds?: number;
  logs?: JobLogEntry[];
  results?: JobResultLinks;
  duration_seconds?: number;
}

export const useJobPoller = (jobId?: string, active = true) => {
  const [data, setData] = useState<JobResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const intervalRef = useRef<number>();

  useEffect(() => {
    const controller = new AbortController();

    const load = async () => {
      if (!jobId || !active) {
        return;
      }
      try {
        const response = await fetch(`/jobs/${jobId}`, { signal: controller.signal });
        if (!response.ok) {
          throw new Error(await response.text());
        }
        const payload = (await response.json()) as JobResponse;
        setData(payload);
        setError(null);
        if (payload.status === 'succeeded' || payload.status === 'failed' || payload.status === 'cancelled') {
          window.clearInterval(intervalRef.current);
        }
      } catch (err) {
        if ((err as Error).name === 'AbortError') {
          return;
        }
        setError((err as Error).message);
      }
    };

    load();

    if (jobId && active) {
      intervalRef.current = window.setInterval(load, 2000);
    }

    return () => {
      controller.abort();
      if (intervalRef.current) {
        window.clearInterval(intervalRef.current);
      }
    };
  }, [jobId, active]);

  return { data, error } as const;
};
