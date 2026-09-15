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

  const user = auth.currentUser;
  if (!user) throw new NotSignedInError();

  const token = await user.getIdToken();
  const headers = new Headers(init.headers);
  headers.set("Authorization", `Bearer ${token}`);

  // globalThis.fetch, not apiFetch — this is the one call that must not recurse.
  return globalThis.fetch(input, { ...init, headers });
}

/**
 * Fetch a file from /api/files/serve and return an object URL for it.
 *
 * <iframe src>, <img src> and <a href> cannot carry an Authorization header,
 * so the bytes are fetched here and handed to the browser as a blob instead.
 * The caller owns the returned URL and must URL.revokeObjectURL it.
 */
export async function fetchFileObjectUrl(storagePath: string): Promise<string> {
  const res = await apiFetch(
    `${API_URL}/api/files/serve?path=${encodeURIComponent(storagePath)}`
  );
  if (!res.ok) throw new Error(`Could not load file (${res.status})`);
  return URL.createObjectURL(await res.blob());
}
