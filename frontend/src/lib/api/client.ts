// Small fetch wrapper for /api/v1 (plan §8). Types come from schema.d.ts (`npm run gen:api`).
// The session is an httpOnly cookie, which the browser sends by itself.

import type { components } from "@/lib/api/schema";

export type Schemas = components["schemas"];

type ApiErrorBody = { error?: { code?: string; message?: string; details?: unknown } };

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
  ) {
    super(message);
  }
}

export async function readError(res: Response): Promise<ApiError> {
  const body = (await res.json().catch(() => ({}))) as ApiErrorBody;
  return new ApiError(
    res.status,
    body.error?.code ?? "ERROR",
    body.error?.message ?? `Request failed (${res.status}).`,
  );
}

export async function apiGet<T>(
  path: string,
  params: Record<string, string | number | undefined> = {},
): Promise<T> {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined) query.set(key, String(value));
  }
  const suffix = query.size ? `?${query}` : "";
  const res = await fetch(`/api/v1${path}${suffix}`, { cache: "no-store" });
  if (!res.ok) throw await readError(res);
  return (await res.json()) as T;
}

/** Start a recognition run for a period: the server queues a job (plan §10). */
export async function postRecognitionRun(periodKey: string): Promise<Schemas["JobAccepted"]> {
  const res = await fetch(`/api/v1/periods/${periodKey}/recognition-run`, { method: "POST" });
  if (!res.ok) throw await readError(res);
  return (await res.json()) as Schemas["JobAccepted"];
}

/** POST /uploads: the server queues a job and answers at once (plan §10). */
export async function postUploads(files: File[]): Promise<Schemas["UploadAccepted"]> {
  const form = new FormData();
  for (const file of files) form.append("files", file);
  const res = await fetch("/api/v1/uploads", { method: "POST", body: form });
  if (!res.ok) throw await readError(res);
  return (await res.json()) as Schemas["UploadAccepted"];
}
