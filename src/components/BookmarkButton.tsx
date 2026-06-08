"use client";

import { useAuth } from "@/lib/auth-context";
import {
  ActivityItem,
  toggleBookmark,
  useIsBookmarked,
} from "@/lib/activity";

interface Props {
  item: ActivityItem | null;
  size?: "sm" | "md";
  className?: string;
}

export default function BookmarkButton({
  item,
  size = "md",
  className = "",
}: Props) {
  const { user } = useAuth();
  const marked = useIsBookmarked(item?.kind, item?.id);

  if (!item) return null;

  const click = (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (!user) return;
    toggleBookmark(user.uid, item);
  };

  const dims =
    size === "sm" ? "w-7 h-7 text-sm" : "w-9 h-9 text-base";

  return (
    <button
      type="button"
      onClick={click}
      title={marked ? "Remove bookmark" : "Add bookmark"}
      aria-label={marked ? "Remove bookmark" : "Add bookmark"}
      className={`${dims} rounded-full border transition flex items-center justify-center flex-shrink-0 ${
        marked
          ? "bg-gold/15 border-gold text-gold"
          : "border-line text-ink-mute hover:bg-bg-alt hover:text-ink"
      } ${className}`}
    >
      {marked ? "★" : "☆"}
    </button>
  );
}
