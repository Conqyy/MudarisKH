"use client";

import Icon from "@/components/Icon";
import { useLang } from "@/lib/i18n";
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
  const { t } = useLang();
  const [dragIndex, setDragIndex] = useState<number | null>(null);
  const [overIndex, setOverIndex] = useState<number | null>(null);

  const [editingId, setEditingId] = useState<string | null>(null);
  const [editValue, setEditValue] = useState("");
  const [savingId, setSavingId] = useState<string | null>(null);
  const [rowError, setRowError] = useState<string | null>(null);
  const [reordering, setReordering] = useState(false);
  const saveOrder = async (from: number, to: number) => {
    if (reordering || to < 0 || to >= items.length) return;
    const reordered = [...items];
    const [moved] = reordered.splice(from, 1);
    reordered.splice(to, 0, moved);
    setReordering(true);
    try { await onReorder(reordered.map(item => item.id)); }
    catch { setRowError("Could not save the order. Please retry."); }
    finally { setReordering(false); }
  };

  // ---- Drag handlers ----
  const handleDrop = (targetIndex: number) => {
    if (dragIndex === null || dragIndex === targetIndex) {
      setDragIndex(null);
      setOverIndex(null);
      return;
    }
    saveOrder(dragIndex, targetIndex);
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

  return <div className="ui-panel overflow-hidden">
    {rowError && !editingId && <p role="alert" className="p-4 text-sm text-danger">{rowError}</p>}
    {items.map((item, index) => {
      const isEditing = editingId === item.id;
      const clickable = !isEditing && canClick?.(item) && !!onItemClick;
      return <div key={item.id} draggable={!isEditing && !reordering}
        onDragStart={event => { setDragIndex(index); event.dataTransfer.effectAllowed = "move"; }}
        onDragOver={event => { event.preventDefault(); event.dataTransfer.dropEffect = "move"; setOverIndex(index); }}
        onDragLeave={() => setOverIndex(value => value === index ? null : value)}
        onDrop={event => { event.preventDefault(); handleDrop(index); }}
        onDragEnd={() => { setDragIndex(null); setOverIndex(null); }}
        className={"material-list-row " + (index ? "border-t border-line " : "") + (dragIndex === index ? "opacity-40 " : "") + (overIndex === index && dragIndex !== index ? "bg-depth ring-1 ring-inset ring-accent " : "")}>
        <span className="shrink-0 text-ink-soft cursor-grab active:cursor-grabbing select-none" title={t("Drag to reorder")} aria-label={t("Drag to reorder")}><Icon name="grip" size={18} /></span>
        <div className="shrink-0">{renderIcon(item)}</div>
        <div className="material-row-copy">
          {isEditing ? <div>
            <div className="flex items-center gap-1">
              <input autoFocus type="text" aria-label={t("Material name")} value={editValue} onChange={event => setEditValue(event.target.value)} onKeyDown={event => onEditKeyDown(event,item.id)} maxLength={120} className="ui-input flex-1 min-w-0" />
              <button type="button" onClick={() => saveEdit(item.id)} disabled={savingId === item.id} title={t("Save")} aria-label={t("Save")} className="icon-button"><Icon name={savingId === item.id ? "loader" : "check"} className={savingId === item.id ? "animate-spin" : ""} /></button>
              <button type="button" onClick={cancelEdit} disabled={savingId === item.id} title={t("Cancel")} aria-label={t("Cancel")} className="icon-button"><Icon name="close" /></button>
            </div>
            {rowError && <p role="alert" className="text-xs text-danger mt-2">{rowError}</p>}
          </div> : <div role={clickable ? "button" : undefined} tabIndex={clickable ? 0 : undefined}
            onClick={() => clickable && onItemClick!(item)}
            onKeyDown={event => { if (clickable && (event.key === "Enter" || event.key === " ")) { event.preventDefault(); onItemClick!(item); } }}
            className={"material-list-open " + (clickable ? "cursor-pointer group" : "")}>
            <div dir="auto" className={"font-semibold break-words " + (clickable ? "group-hover:text-accent" : "")}>{item.title}</div>
            <div className="text-xs text-ink-soft tabular-nums mt-1 flex flex-wrap gap-x-2 gap-y-1">{renderMeta(item)}</div>
          </div>}
        </div>
        {!isEditing && <div className="material-row-actions">
          <div className="material-row-status tabular-nums">{renderStatus(item)}</div>
          <button type="button" aria-label={t("Move") + " " + item.title + " " + t("up")} disabled={reordering || index === 0} onClick={() => saveOrder(index,index - 1)} className="icon-button"><Icon name="arrow-up" size={17} /></button>
          <button type="button" aria-label={t("Move") + " " + item.title + " " + t("down")} disabled={reordering || index === items.length - 1} onClick={() => saveOrder(index,index + 1)} className="icon-button"><Icon name="arrow-down" size={17} /></button>
          <button type="button" onClick={() => startEdit(item)} title={t("Rename")} aria-label={t("Rename")} className="icon-button"><Icon name="edit" size={17} /></button>
          {onDelete && <button type="button" onClick={() => onDelete(item)} title={t("Delete")} aria-label={t("Delete")} className="icon-button danger"><Icon name="trash" size={17} /></button>}
        </div>}
      </div>;
    })}
  </div>;
}
