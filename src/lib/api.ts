// Authenticated client for the Python backend.
//
// The backend verifies a Firebase ID token on every data endpoint and derives
// the owner from it, so a plain fetch() now comes back 401. Every backend call
// goes through apiFetch, which attaches the current user's token.

import { auth } from "./firebase";

export const API_URL =
  process.env.NEXT_PUBLIC_BACKEND_URL || "http://127.0.0.1:8000";

/** Thrown when a backend call is attempted with no signed-in user. */
export class NotSignedInError extends Error {
  constructor() {
    super("Not signed in");
    this.name = "NotSignedInError";
  }
}

/**
 * The browser fetch() with `Authorization: Bearer <firebase-id-token>` added.
 *
 * Takes the same arguments as fetch. getIdToken() refreshes the token on its
 * own when it is close to expiry, so callers never deal with that. Headers are
 * merged rather than replaced, which matters for FormData bodies: setting
 * Content-Type by hand there would drop the multipart boundary.
 */
export async function apiFetch(
  input: string,
  init: RequestInit = {}
): Promise<Response> {
  // On a page load Firebase restores the session asynchronously, so a call
  // fired from an early effect can land before currentUser is populated.
  // Wait for that to settle before concluding nobody is signed in.
  await auth.authStateReady();
  init.signal?.throwIfAborted();

  const user = auth.currentUser;
  if (!user) throw new NotSignedInError();

  const token = await user.getIdToken();
  init.signal?.throwIfAborted();
  const headers = new Headers(init.headers);
  headers.set("Authorization", `Bearer ${token}`);

  // globalThis.fetch, not apiFetch — this is the one call that must not recurse.
  return globalThis.fetch(input, { ...init, headers });
}

/** Parse a backend response only after verifying its HTTP status. */
export async function apiJson<T = any>(input: string, init: RequestInit = {}): Promise<T> {
  const res = await apiFetch(input, init);
  if (!res.ok) {
    const error = await res.json().catch(() => null);
    throw new Error(typeof error?.detail === "string" ? error.detail : `Request failed (${res.status})`);
  }
  return res.json();
}

/** Fetch authenticated bytes. The caller owns and must revoke the returned URL. */
export async function fetchObjectUrl(url: string, init: RequestInit = {}): Promise<string> {
  const res = await apiFetch(url, init);
  if (!res.ok) throw new Error(`Could not load file (${res.status})`);
  const blob = await res.blob();
  init.signal?.throwIfAborted();
  return URL.createObjectURL(blob);
}

/** fetchObjectUrl for a stored upload served by /api/files/serve. */
export async function fetchFileObjectUrl(storagePath: string, init: RequestInit = {}): Promise<string> {
  return fetchObjectUrl(
    `${API_URL}/api/files/serve?path=${encodeURIComponent(storagePath)}`, init
  );
}
