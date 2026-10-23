"use client";

import Link from "next/link";
import { useAuth } from "@/lib/auth-context";
import Icon from "@/components/Icon";
import { ACTIVITY_ICONS } from "@/components/material-presentation";
import { useLang } from "@/lib/i18n";
import {
  ActivityItem,
  ActivityKind,
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
  const { t } = useLang();
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
          <span className="tabular-nums text-xs text-ink-mute">
            {totalCount} {t(totalCount === 1 ? "item" : "items")}
          </span>
          {onClear && (
            <button
              onClick={onClear}
              className="ui-button ghost"
            >
              {t("Clear all")}
            </button>
          )}
        </div>
      )}

      <div className="space-y-10">
        {ORDER.filter((k) => grouped[k].length > 0).map((kind) => (
          <section key={kind}>
            <div className="section-heading mb-3 flex items-center gap-2">
              <Icon name={ACTIVITY_ICONS[kind]} size={18} />
              <span>{t(KIND_LABEL[kind])}</span>
              <span className="text-ink-mute/60">· {grouped[kind].length}</span>
            </div>
            <div className="ui-panel overflow-hidden">
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
  const { t } = useLang();
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
    <div
      className={`group material-list-row hover:bg-bg-alt ${
        first ? "" : "border-t border-line"
      }`}
    >
      <Link href={entry.href} className="flex flex-1 min-w-0 items-center gap-4">
      <div className="w-10 h-10 rounded-xl bg-bg-alt flex items-center justify-center text-lg flex-shrink-0">
        <Icon name={ACTIVITY_ICONS[entry.kind]} />
      </div>
      <div className="flex-1 min-w-0">
        <div dir="auto" className="font-semibold break-words group-hover:text-accent transition">
          {entry.title}
        </div>
        <div className="text-xs text-ink-soft tabular-nums mt-1 flex flex-wrap items-center gap-2">
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
            {mode === "bookmark" ? t("added") + " " : ""}
            {relativeTime(entry.ts)}
          </span>
        </div>
      </div>
      </Link>
      <button
        onClick={handleStar}
        aria-label={t(marked ? "Remove bookmark" : "Add bookmark")}
        title={t(marked ? "Remove bookmark" : "Add bookmark")}
        aria-pressed={marked}
        className={`icon-button ${marked ? "is-active" : ""}`}
      >
        <Icon name="bookmark" size={18} className={marked ? "fill-current" : ""} />
      </button>
      <button
        onClick={handleRemove}
        aria-label={t(mode === "recent" ? "Remove from recent" : "Remove bookmark")}
        title={t(mode === "recent" ? "Remove from recent" : "Remove bookmark")}
        className="icon-button danger"
      >
        <Icon name="close" size={18} />
      </button>
    </div>
  );
}
