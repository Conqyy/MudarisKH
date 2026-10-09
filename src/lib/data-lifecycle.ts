/** Keep failed server purges visible to the caller; only success can clear UI. */
export async function requireDeletionSuccess(response: Response, resource: string): Promise<void> {
  if (response.ok) return;
  let detail: unknown;
  try {
    detail = (await response.json()).detail;
  } catch { /* A proxy may return an HTML error instead of JSON. */ }
  throw new Error(typeof detail === "string" ? detail : `Could not delete ${resource} (${response.status}). Please retry.`);
}

/** Destructive account cleanup must use the token of the account the user
 * just confirmed, even when another tab changes the active Firebase session. */
export async function purgeAccountWithToken(apiUrl: string, token: string): Promise<void> {
  const response = await globalThis.fetch(`${apiUrl}/api/account`, {
    method: "DELETE",
    headers: { Authorization: `Bearer ${token}` },
  });
  await requireDeletionSuccess(response, "account");
}

/** Delete only this user's device-local activity after confirmed server cleanup. */
export function clearDeletedActivity(uid: string, courseId?: string): void {
  if (typeof window === "undefined") return;
  for (const kind of ["recent", "bookmarks"]) {
    const key = `mudaris.${kind}.${uid}`;
    try {
      if (!courseId) {
        window.localStorage.removeItem(key);
      } else {
        const raw = window.localStorage.getItem(key);
        if (!raw) continue;
        const items: unknown = JSON.parse(raw);
        if (!Array.isArray(items)) continue;
        const path = `/course/${encodeURIComponent(courseId)}`;
        const next = items.filter((item) => {
          if (!item || typeof item !== "object") return false;
          const href = typeof item.href === "string" ? item.href.split(/[?#]/)[0] : "";
          return !(item.kind === "course" && item.id === courseId) && href !== path && !href.startsWith(`${path}/`);
        });
        window.localStorage.setItem(key, JSON.stringify(next));
      }
    } catch { /* A disabled/quota-limited local store must not undo server success. */ }
  }
  window.dispatchEvent(new CustomEvent("mudaris:activity"));
}
