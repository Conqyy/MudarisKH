"use client";

import { useAuth } from "@/lib/auth-context";
import { useLang } from "@/lib/i18n";
import Icon from "@/components/Icon";
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
  const { t } = useLang();
  const marked = useIsBookmarked(item?.kind, item?.id);

  if (!item) return null;

  const click = (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (!user) return;
    toggleBookmark(user.uid, item);
  };

  return (
    <button
      type="button"
      onClick={click}
      title={t(marked ? "Remove bookmark" : "Add bookmark")}
      aria-label={t(marked ? "Remove bookmark" : "Add bookmark")}
      aria-pressed={marked}
      className={`icon-button ${marked ? "is-active" : ""} ${className}`}
    >
      <Icon name="bookmark" size={size === "sm" ? 18 : 20} className={marked ? "fill-current" : ""} />
    </button>
  );
}
