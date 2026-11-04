// Sign-in helpers for the /api/v1/auth endpoints (plan §8, D11).
// The session itself is an httpOnly cookie: the browser stores and sends it;
// this code never sees the token.

import { readError, type Schemas } from "@/lib/api/client";

export type SessionUser = Schemas["UserOut"];

/** The signed-in user, or null when nobody is signed in. */
export async function fetchMe(): Promise<SessionUser | null> {
  const res = await fetch("/api/v1/auth/me", { cache: "no-store" });
  if (res.status === 401) return null;
  if (!res.ok) throw await readError(res);
  return (await res.json()) as SessionUser;
}

export async function signIn(email: string, password: string): Promise<SessionUser> {
  const res = await fetch("/api/v1/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  if (!res.ok) throw await readError(res);
  return (await res.json()) as SessionUser;
}

export async function signOut(): Promise<void> {
  await fetch("/api/v1/auth/logout", { method: "POST" });
}
