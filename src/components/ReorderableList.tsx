"use client";

import { useState, KeyboardEvent } from "react";

export interface ReorderableItem {
  id: string;
  title: string;
}

interface Props<T extends ReorderableItem> {
  items: T[];
  /** Called with the new ordered list of ids after a drag-drop. */
  onReorder: (orderedIds: string[]) => void | Promise<void>;
  /** Persist a renamed title. Should throw on failure. */
  onRename: (id: string, title: string) => Promise<void>;
  /** Left-side icon/badge for a row. */
  renderIcon: (item: T) => React.ReactNode;
  /** Secondary line under the title. */
  renderMeta: (item: T) => React.ReactNode;
  /** Right-side status badge. */
  renderStatus: (item: T) => React.ReactNode;
  /** Optional row click (e.g. open a viewer). */
  onItemClick?: (item: T) => void;
  /** Whether a row is clickable. */
  canClick?: (item: T) => boolean;
  /** Optional delete action — shows a trash button when provided. */
  onDelete?: (item: T) => void;
}

export default function ReorderableList<T extends ReorderableItem>({
  items,
  onReorder,
  onRename,
  renderIcon,
  renderMeta,
  renderStatus,
  onItemClick,
  canClick,
  onDelete,
}: Props<T>) {
  const [dragIndex, setDragIndex] = useState<number | null>(null);
  const [overIndex, setOverIndex] = useState<number | null>(null);

  const [editingId, setEditingId] = useState<string | null>(null);
  const [editValue, setEditValue] = useState("");
  const [savingId, setSavingId] = useState<string | null>(null);
  const [rowError, setRowError] = useState<string | null>(null);

  // ---- Drag handlers ----
  const handleDrop = (targetIndex: number) => {
    if (dragIndex === null || dragIndex === targetIndex) {
      setDragIndex(null);
      setOverIndex(null);
      return;
    }
    const reordered = [...items];
    const [moved] = reordered.splice(dragIndex, 1);
    reordered.splice(targetIndex, 0, moved);
    onReorder(reordered.map((it) => it.id));
    setDragIndex(null);
    setOverIndex(null);
  };

  // ---- Rename handlers ----
  const startEdit = (item: T) => {
    setRowError(null);
    setEditingId(item.id);
    setEditValue(item.title);
  };

  const cancelEdit = () => {
    setEditingId(null);
    setEditValue("");
    setRowError(null);
  };

  const saveEdit = async (id: string) => {
    const trimmed = editValue.trim();
    if (!trimmed) {
      setRowError("Name can't be empty.");
      return;
    }
    setSavingId(id);
    setRowError(null);
    try {
      await onRename(id, trimmed);
      setEditingId(null);
      setEditValue("");
    } catch (err: any) {
      setRowError(err?.message || "Couldn't rename. Try again.");
    } finally {
      setSavingId(null);
    }
  };

  const onEditKeyDown = (e: KeyboardEvent<HTMLInputElement>, id: string) => {
    if (e.key === "Enter") {
      e.preventDefault();
      saveEdit(id);
    } else if (e.key === "Escape") {
      e.preventDefault();
      cancelEdit();
    }
  };

  return (
    <div className="bg-paper border border-line rounded-3xl overflow-hidden">
      {items.map((item, idx) => {
        const isEditing = editingId === item.id;
        const isDragging = dragIndex === idx;
        const isOver = overIndex === idx && dragIndex !== idx;
        const clickable = !isEditing && canClick?.(item) && !!onItemClick;

        return (
          <div
            key={item.id}
            draggable={!isEditing}
            onDragStart={(e) => {
              setDragIndex(idx);
              e.dataTransfer.effectAllowed = "move";
            }}
            onDragOver={(e) => {
              e.preventDefault();
              e.dataTransfer.dropEffect = "move";
              setOverIndex(idx);
            }}
            onDragLeave={() => {
              setOverIndex((cur) => (cur === idx ? null : cur));
            }}
            onDrop={(e) => {
              e.preventDefault();
              handleDrop(idx);
            }}
            onDragEnd={() => {
              setDragIndex(null);
              setOverIndex(null);
            }}
            className={`flex items-center gap-3 p-5 transition ${
              idx !== 0 ? "border-t border-line" : ""
            } ${isDragging ? "opacity-40" : ""} ${
              isOver ? "bg-accent/5 ring-1 ring-inset ring-accent/40" : ""
            }`}
          >
            {/* Drag handle */}
            <span
              className="flex-shrink-0 text-ink-mute hover:text-ink cursor-grab active:cursor-grabbing select-none"
              title="Drag to reorder"
              aria-label="Drag to reorder"
            >
              <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
                <circle cx="5" cy="3" r="1.4" />
                <circle cx="11" cy="3" r="1.4" />
                <circle cx="5" cy="8" r="1.4" />
                <circle cx="11" cy="8" r="1.4" />
                <circle cx="5" cy="13" r="1.4" />
                <circle cx="11" cy="13" r="1.4" />
              </svg>
            </span>

            {/* Icon */}
            <div className="flex-shrink-0">{renderIcon(item)}</div>

            {/* Title + meta */}
            <div className="flex-1 min-w-0">
              {isEditing ? (
                <div>
                  <div className="flex items-center gap-2">
                    <input
                      autoFocus
                      type="text"
                      value={editValue}
                      onChange={(e) => setEditValue(e.target.value)}
                      onKeyDown={(e) => onEditKeyDown(e, item.id)}
                      maxLength={120}
                      className="flex-1 min-w-0 px-3 py-1.5 border border-accent rounded-lg bg-bg text-sm focus:outline-none"
                    />
                    <button
                      onClick={() => saveEdit(item.id)}
                      disabled={savingId === item.id}
                      className="flex-shrink-0 w-8 h-8 rounded-full bg-sage text-paper text-sm flex items-center justify-center hover:bg-ink transition disabled:opacity-50"
                      title="Save"
                    >
                      {savingId === item.id ? "…" : "✓"}
                    </button>
                    <button
                      onClick={cancelEdit}
                      disabled={savingId === item.id}
                      className="flex-shrink-0 w-8 h-8 rounded-full bg-bg-alt text-ink-soft text-sm flex items-center justify-center hover:bg-line transition disabled:opacity-50"
                      title="Cancel"
                    >
                      ×
                    </button>
                  </div>
                  {rowError && (
                    <div className="text-xs text-accent mt-1.5">{rowError}</div>
                  )}
                </div>
              ) : (
                <div
                  onClick={() => clickable && onItemClick!(item)}
                  className={`${clickable ? "cursor-pointer group" : ""}`}
                >
                  <div
                    className={`font-medium truncate ${
                      clickable ? "group-hover:text-accent transition" : ""
                    }`}
                  >
                    {item.title}
                  </div>
                  <div className="text-xs text-ink-mute font-mono mt-0.5 truncate">
                    {renderMeta(item)}
                  </div>
                </div>
              )}
            </div>

            {/* Status + actions */}
            {!isEditing && (
              <div className="flex items-center gap-3 flex-shrink-0">
                <div className="font-mono text-xs">{renderStatus(item)}</div>
                <button
                  onClick={() => startEdit(item)}
                  className="w-8 h-8 rounded-full text-ink-mute hover:bg-bg-alt hover:text-ink transition flex items-center justify-center text-sm"
                  title="Rename"
                  aria-label="Rename"
                >
                  ✎
                </button>
                {onDelete && (
                  <button
                    onClick={() => onDelete(item)}
                    className="w-8 h-8 rounded-full flex items-center justify-center text-ink-mute hover:bg-accent hover:text-paper transition text-sm"
                    title="Delete"
                    aria-label="Delete"
                  >
                    🗑
                  </button>
                )}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
