"use client";

// Lightweight "Recent" + "Bookmarked" tracking, stored per-user in
// localStorage. A custom event lets all subscribed React components stay in
// sync without a global state library.

import { useEffect, useState } from "react";
import { useAuth } from "./auth-context";

export type ActivityKind =
  | "course"
  | "document"
  | "audio"
  | "exam"
  | "summary"
  | "flashcards";

export interface ActivityItem {
  kind: ActivityKind;
  id: string;
  title: string;
  href: string;
  /** Optional context (e.g. the course this item belongs to). */
  courseCode?: string;
  courseColor?: string;
}

export interface StoredRecent extends ActivityItem {
  lastAt: number;
}

export interface StoredBookmark extends ActivityItem {
  addedAt: number;
}

const MAX_RECENT = 30;
const EVENT = "mudaris:activity";

const keyRecent = (uid: string) => `mudaris.recent.${uid}`;
const keyBookmark = (uid: string) => `mudaris.bookmarks.${uid}`;

function readArray<T>(key: string): T[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T[]) : [];
  } catch {
    return [];
  }
}

function writeArray<T>(key: string, value: T[]) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(key, JSON.stringify(value));
    window.dispatchEvent(new CustomEvent(EVENT));
  } catch {
    /* ignore quota / private-mode errors */
  }
}

const sameItem = (
  a: { kind: ActivityKind; id: string },
  b: { kind: ActivityKind; id: string }
) => a.kind === b.kind && a.id === b.id;

// ---------- Recents ----------

function getRecents(uid: string | null | undefined): StoredRecent[] {
  if (!uid) return [];
  return readArray<StoredRecent>(keyRecent(uid)).sort(
    (a, b) => b.lastAt - a.lastAt
  );
}

function trackRecent(
  uid: string | null | undefined,
  item: ActivityItem
): void {
  if (!uid || !item?.id || !item?.title) return;
  const list = readArray<StoredRecent>(keyRecent(uid));
  const filtered = list.filter((it) => !sameItem(it, item));
  filtered.unshift({ ...item, lastAt: Date.now() });
  writeArray(keyRecent(uid), filtered.slice(0, MAX_RECENT));
}

export function removeRecent(
  uid: string,
  kind: ActivityKind,
  id: string
): void {
  const list = readArray<StoredRecent>(keyRecent(uid));
  writeArray(
    keyRecent(uid),
    list.filter((it) => !sameItem(it, { kind, id }))
  );
}

export function clearRecents(uid: string): void {
  writeArray(keyRecent(uid), []);
}

// ---------- Bookmarks ----------

function getBookmarks(
  uid: string | null | undefined
): StoredBookmark[] {
  if (!uid) return [];
  return readArray<StoredBookmark>(keyBookmark(uid)).sort(
    (a, b) => b.addedAt - a.addedAt
  );
}

function isBookmarked(
  uid: string | null | undefined,
  kind: ActivityKind,
  id: string
): boolean {
  if (!uid) return false;
  return readArray<StoredBookmark>(keyBookmark(uid)).some((it) =>
    sameItem(it, { kind, id })
  );
}

/** Toggles a bookmark. Returns the new bookmarked state (true = now marked). */
export function toggleBookmark(
  uid: string | null | undefined,
  item: ActivityItem
): boolean {
  if (!uid) return false;
  const list = readArray<StoredBookmark>(keyBookmark(uid));
  const exists = list.some((it) => sameItem(it, item));
  const next = exists
    ? list.filter((it) => !sameItem(it, item))
    : [{ ...item, addedAt: Date.now() }, ...list];
  writeArray(keyBookmark(uid), next);
  return !exists;
}

// ---------- React hooks ----------

function useActivityVersion() {
  const [v, setV] = useState(0);
  useEffect(() => {
    const bump = () => setV((x) => x + 1);
    window.addEventListener(EVENT, bump);
    window.addEventListener("storage", bump);
    return () => {
      window.removeEventListener(EVENT, bump);
      window.removeEventListener("storage", bump);
    };
  }, []);
  return v;
}

export function useRecents(): StoredRecent[] {
  const { user } = useAuth();
  const v = useActivityVersion();
  const [list, setList] = useState<StoredRecent[]>([]);
  useEffect(() => {
    setList(getRecents(user?.uid));
  }, [user, v]);
  return list;
}

export function useBookmarks(): StoredBookmark[] {
  const { user } = useAuth();
  const v = useActivityVersion();
  const [list, setList] = useState<StoredBookmark[]>([]);
  useEffect(() => {
    setList(getBookmarks(user?.uid));
  }, [user, v]);
  return list;
}

export function useIsBookmarked(
  kind: ActivityKind | undefined,
  id: string | undefined
): boolean {
  const { user } = useAuth();
  const v = useActivityVersion();
  const [marked, setMarked] = useState(false);
  useEffect(() => {
    if (!kind || !id) {
      setMarked(false);
      return;
    }
    setMarked(isBookmarked(user?.uid, kind, id));
  }, [user, kind, id, v]);
  return marked;
}

/** Records the item as "recently opened" when it (or the user) first becomes
 * available. Pages call this near the top of their component body. */
export function useTrackRecent(item: ActivityItem | null | undefined) {
  const { user } = useAuth();
  const key = item ? `${item.kind}:${item.id}:${item.title}` : "";
  useEffect(() => {
    if (!user?.uid || !item?.id || !item?.title) return;
    trackRecent(user.uid, item);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user?.uid, key]);
}

// ---------- Display helpers ----------

export const KIND_LABEL: Record<ActivityKind, string> = {
  course: "Courses",
  document: "Documents",
  audio: "Recordings",
  exam: "Practice Exams",
  summary: "Summaries",
  flashcards: "Flashcards",
};

export const KIND_ICON: Record<ActivityKind, string> = {
  course: "📚",
  document: "📄",
  audio: "🎙️",
  exam: "📝",
  summary: "📋",
  flashcards: "🗂️",
};

export function relativeTime(ms: number): string {
  const diff = Date.now() - ms;
  if (diff < 60_000) return "just now";
  const mins = Math.floor(diff / 60_000);
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  if (days < 30) return `${days}d ago`;
  const months = Math.floor(days / 30);
  if (months < 12) return `${months}mo ago`;
  return new Date(ms).toLocaleDateString();
}
