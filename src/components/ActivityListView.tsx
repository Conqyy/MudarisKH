"use client";

import Link from "next/link";
import { useAuth } from "@/lib/auth-context";
import {
  ActivityItem,
  ActivityKind,
  KIND_ICON,
  KIND_LABEL,
  relativeTime,
  toggleBookmark,
  removeRecent,
  useIsBookmarked,
} from "@/lib/activity";

interface Entry extends ActivityItem {
  /** Either lastAt (Recent) or addedAt (Bookmark). */
  ts: number;
}

interface Props {
  items: Entry[];
  /** "recent" shows "X ago"; "bookmark" shows "added X ago". */
  mode: "recent" | "bookmark";
  /** Optional handler when an item is removed (for clear-all etc). */
  onClear?: () => void;
}

// Logical order in which kinds are listed.
const ORDER: ActivityKind[] = [
  "course",
  "document",
  "audio",
  "exam",
  "summary",
  "flashcards",
];

export default function ActivityListView({ items, mode, onClear }: Props) {
  // Group by kind, preserving the array's existing sort within each group.
  const grouped: Record<ActivityKind, Entry[]> = {
    course: [],
    document: [],
    audio: [],
    exam: [],
    summary: [],
    flashcards: [],
  };
  for (const it of items) grouped[it.kind].push(it);

  const totalCount = items.length;

  return (
    <div>
      {totalCount > 0 && (
        <div className="flex items-center justify-between mb-6">
          <span className="font-mono text-xs text-ink-mute">
            {totalCount} item{totalCount === 1 ? "" : "s"}
          </span>
          {onClear && (
            <button
              onClick={onClear}
              className="text-xs text-ink-mute hover:text-accent transition"
            >
              Clear all
            </button>
          )}
        </div>
      )}

      <div className="space-y-10">
        {ORDER.filter((k) => grouped[k].length > 0).map((kind) => (
          <section key={kind}>
            <div className="font-mono text-[11px] text-ink-mute uppercase tracking-widest mb-3 flex items-center gap-2">
              <span>{KIND_ICON[kind]}</span>
              <span>{KIND_LABEL[kind]}</span>
              <span className="text-ink-mute/60">· {grouped[kind].length}</span>
            </div>
            <div className="bg-paper border border-line rounded-3xl overflow-hidden">
              {grouped[kind].map((it, idx) => (
                <ActivityRow
                  key={`${it.kind}-${it.id}`}
                  entry={it}
                  mode={mode}
                  first={idx === 0}
                />
              ))}
            </div>
          </section>
        ))}
      </div>
    </div>
  );
}

function ActivityRow({
  entry,
  mode,
  first,
}: {
  entry: Entry;
  mode: "recent" | "bookmark";
  first: boolean;
}) {
  const { user } = useAuth();
  const marked = useIsBookmarked(entry.kind, entry.id);

  const handleStar = (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (!user) return;
    toggleBookmark(user.uid, {
      kind: entry.kind,
      id: entry.id,
      title: entry.title,
      href: entry.href,
      courseCode: entry.courseCode,
      courseColor: entry.courseColor,
    });
  };

  const handleRemove = (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (!user) return;
    if (mode === "recent") {
      removeRecent(user.uid, entry.kind, entry.id);
    } else {
      toggleBookmark(user.uid, entry); // toggling off
    }
  };

  return (
    <Link
      href={entry.href}
      className={`group flex items-center gap-4 p-5 hover:bg-bg-alt transition ${
        first ? "" : "border-t border-line"
      }`}
    >
      <div className="w-10 h-10 rounded-xl bg-bg-alt flex items-center justify-center text-lg flex-shrink-0">
        {KIND_ICON[entry.kind]}
      </div>
      <div className="flex-1 min-w-0">
        <div className="font-medium truncate group-hover:text-accent transition">
          {entry.title}
        </div>
        <div className="text-xs text-ink-mute font-mono mt-0.5 flex items-center gap-2 truncate">
          {entry.courseCode && (
            <span className="flex items-center gap-1.5">
              {entry.courseColor && (
                <span
                  className="w-1.5 h-1.5 rounded-full"
                  style={{ background: entry.courseColor }}
                />
              )}
              {entry.courseCode}
            </span>
          )}
          <span className="text-ink-mute/60">·</span>
          <span>
            {mode === "bookmark" ? "added " : ""}
            {relativeTime(entry.ts)}
          </span>
        </div>
      </div>
      <button
        onClick={handleStar}
        title={marked ? "Remove bookmark" : "Add bookmark"}
        className={`w-8 h-8 rounded-full flex items-center justify-center text-sm transition flex-shrink-0 ${
          marked
            ? "bg-gold/15 text-gold"
            : "text-ink-mute hover:bg-bg-alt hover:text-ink opacity-0 group-hover:opacity-100"
        }`}
      >
        {marked ? "★" : "☆"}
      </button>
      <button
        onClick={handleRemove}
        title={mode === "recent" ? "Remove from recent" : "Remove bookmark"}
        className="w-8 h-8 rounded-full flex items-center justify-center text-ink-mute hover:bg-accent hover:text-paper transition flex-shrink-0 opacity-0 group-hover:opacity-100 text-sm"
      >
        ×
      </button>
    </Link>
  );
}
