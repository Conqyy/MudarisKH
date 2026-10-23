"use client";

import Icon from "@/components/Icon";
import { REMINDER_ICONS } from "@/components/material-presentation";

import { useState, FormEvent } from "react";
import { CourseReminder, ReminderType } from "@/lib/firestore-helpers";
import { useLang } from "@/lib/i18n";
import { useDialog } from "@/lib/use-dialog";

interface Props {
  reminders: CourseReminder[];
  /** Persist the full updated list (page wires this to updateCourse). */
  onChange: (reminders: CourseReminder[]) => void | Promise<void>;
}

const TYPE_META: Record<
  ReminderType,
  { label: string; chip: string }
> = {
  quiz: { label: "Quiz", chip: "bg-gold/10 text-gold" },
  midterm: { label: "Midterm", chip: "bg-accent/10 text-accent" },
  final: { label: "Final", chip: "bg-accent/10 text-accent" },
  assignment: { label: "Assignment", chip: "bg-sage/10 text-sage" },
  project: { label: "Project", chip: "bg-accent/10 text-accent" },
  presentation: {
    label: "Presentation",
    chip: "bg-accent/10 text-accent",
  },
  other: { label: "Other", chip: "bg-bg-alt text-ink-soft" },
};

const TYPE_ORDER: ReminderType[] = [
  "quiz",
  "midterm",
  "final",
  "assignment",
  "project",
  "presentation",
  "other",
];

const newId = () =>
  typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `r_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;

// Days until a YYYY-MM-DD date, comparing date-only (local midnight).
function daysUntil(dateStr?: string): number | null {
  if (!dateStr) return null;
  const target = new Date(dateStr + "T00:00:00");
  if (isNaN(target.getTime())) return null;
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  return Math.round((target.getTime() - today.getTime()) / 86_400_000);
}

function dueLabel(
  dateStr: string | undefined,
  t: (s: string) => string
): { text: string; tone: string } | null {
  const d = daysUntil(dateStr);
  if (d === null) return null;
  if (d < 0) return { text: `${t("Overdue")} ${Math.abs(d)}${t("d")}`, tone: "text-danger" };
  if (d === 0) return { text: t("Today"), tone: "text-danger" };
  if (d === 1) return { text: t("Tomorrow"), tone: "text-gold" };
  if (d <= 7) return { text: `${t("In")} ${d}${t("d")}`, tone: "text-gold" };
  return { text: `${t("In")} ${d}${t("d")}`, tone: "text-ink-mute" };
}

export default function CourseReminders({ reminders, onChange }: Props) {
  const { t } = useLang();
  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState<CourseReminder | null>(null);

  // Form fields
  const [type, setType] = useState<ReminderType>("quiz");
  const [title, setTitle] = useState("");
  const [date, setDate] = useState("");
  const [time, setTime] = useState("");
  const [notes, setNotes] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [actionError, setActionError] = useState("");
  const dialogRef = useDialog(() => { if (!saving) { setShowForm(false); setEditing(null); } }, showForm);

  const openAdd = () => {
    setEditing(null);
    setType("quiz");
    setTitle("");
    setDate("");
    setTime("");
    setNotes("");
    setError("");
    setShowForm(true);
  };

  const openEdit = (r: CourseReminder) => {
    setEditing(r);
    setType(r.type);
    setTitle(r.title);
    setDate(r.date || "");
    setTime(r.time || "");
    setNotes(r.notes || "");
    setError("");
    setShowForm(true);
  };

  const closeForm = () => {
    setShowForm(false);
    setEditing(null);
  };

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (saving) return;
    if (!title.trim()) {
      setError(t("Give the reminder a title."));
      return;
    }
    const base = {
      title: title.trim(),
      type,
      date: date || undefined,
      time: time || undefined,
      notes: notes.trim() || undefined,
    };
    let next: CourseReminder[];
    if (editing) {
      next = reminders.map((r) =>
        r.id === editing.id ? { ...r, ...base } : r
      );
    } else {
      next = [
        ...reminders,
        { id: newId(), done: false, createdAt: Date.now(), ...base },
      ];
    }
    setSaving(true);
    setError("");
    try { await onChange(next); closeForm(); }
    catch (error: any) { setError(error?.message || t("Could not save the reminder. Please retry.")); }
    finally { setSaving(false); }
  };

  const saveAction = async (next: CourseReminder[]) => {
    if (saving) return;
    setSaving(true); setActionError("");
    try { await onChange(next); }
    catch (error: any) { setActionError(error?.message || t("Could not save reminders. Please retry.")); }
    finally { setSaving(false); }
  };

  const toggleDone = (id: string) => {
    saveAction(
      reminders.map((r) => (r.id === id ? { ...r, done: !r.done } : r))
    );
  };

  const remove = (r: CourseReminder) => {
    if (!confirm(`Delete reminder "${r.title}"?`)) return;
    saveAction(reminders.filter((x) => x.id !== r.id));
  };

  // Sort: open first (by date asc, undated last), done at the bottom.
  const sorted = [...reminders].sort((a, b) => {
    if (a.done !== b.done) return a.done ? 1 : -1;
    const da = daysUntil(a.date);
    const db = daysUntil(b.date);
    if (da === null && db === null) return a.createdAt - b.createdAt;
    if (da === null) return 1;
    if (db === null) return -1;
    return da - db;
  });

  const openCount = reminders.filter((r) => !r.done).length;

  return (
    <section className="mb-12">
      {actionError && <p role="alert" className="text-sm text-accent mb-3">{actionError}</p>}
      <div className="flex flex-wrap items-center justify-between gap-3 mb-5">
        <h2 className="section-heading flex flex-wrap items-center gap-3">
          {t("Reminders")}
          {openCount > 0 && (
            <span className="text-xs tabular-nums text-accent bg-accent/10 px-2.5 py-1 rounded-full">
              {openCount} {t("upcoming")}
            </span>
          )}
        </h2>
        <button
          onClick={openAdd}
          className="ui-button primary"
        >
          <Icon name="plus" size={17} /> {t("Add")}
        </button>
      </div>

      {reminders.length === 0 ? (
        <div className="ui-panel p-8 text-center">
          <span className="material-upload-symbol mx-auto mb-4"><Icon name="calendar" size={26} /></span>
          <h3 className="font-sans text-xl font-medium mb-2">
            {t("No reminders yet")}
          </h3>
          <p className="text-ink-soft text-sm mb-5 max-w-md mx-auto">
            {t("Track quizzes, midterms, assignments, and deadlines for this course so nothing slips through.")}
          </p>
          <button
            onClick={openAdd}
            className="ui-button primary"
          >
            <Icon name="plus" size={17} /> {t("Add your first reminder")}
          </button>
        </div>
      ) : (
        <div className="ui-panel overflow-hidden">
          {sorted.map((r, idx) => {
            const meta = TYPE_META[r.type];
            const due = dueLabel(r.date, t);
            return (
              <div
                key={r.id}
                className={`material-reminder-row ${
                  idx !== 0 ? "border-t border-line" : ""
                } ${r.done ? "opacity-55" : "hover:bg-bg-alt"}`}
              >
                {/* Done toggle */}
                <button
                  onClick={() => toggleDone(r.id)}
                  title={r.done ? t("Mark as not done") : t("Mark as done")}
                  className="material-toggle" aria-pressed={r.done} aria-label={t(r.done ? "Mark as not done" : "Mark as done")}
                ><Icon name="check" size={18} className={r.done ? "" : "opacity-0"} /></button>

                {/* Type icon */}
                <div className="w-9 h-9 rounded-xl bg-bg-alt flex items-center justify-center text-base flex-shrink-0">
                  <Icon name={REMINDER_ICONS[r.type]} size={18} />
                </div>

                {/* Title + meta */}
                <div className="material-row-copy">
                  <div
                    dir="auto" className={`font-semibold break-words ${
                      r.done ? "line-through text-ink-mute" : ""
                    }`}
                  >
                    {r.title}
                  </div>
                  <div className="text-xs text-ink-mute tabular-nums mt-0.5 flex items-center gap-2 flex-wrap">
                    <span
                      className={`px-2 py-0.5 rounded-full ${meta.chip}`}
                    >
                      {t(meta.label)}
                    </span>
                    {r.date && (
                      <span>
                        {new Date(r.date + "T00:00:00").toLocaleDateString(
                          "en-US",
                          { month: "short", day: "numeric" }
                        )}
                        {r.time ? ` · ${r.time}` : ""}
                      </span>
                    )}
                    {!r.done && due && (
                      <span className={due.tone}>· {due.text}</span>
                    )}
                    {r.notes && (
                      <span dir="auto" className="text-ink-soft break-words">
                        · {r.notes}
                      </span>
                    )}
                  </div>
                </div>

                {/* Actions */}
                <div className="flex items-center gap-1 flex-shrink-0">
                  <button
                    onClick={() => openEdit(r)}
                    title={t("Edit")}
                    className="icon-button"
                  ><Icon name="edit" size={17} /></button>
                  <button
                    onClick={() => remove(r)}
                    title={t("Delete")}
                    className="icon-button danger"
                  ><Icon name="trash" size={17} /></button>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Add / Edit modal */}
      {showForm && (
        <div
          ref={dialogRef} role="dialog" aria-modal="true" aria-label={editing ? t("Edit reminder") : t("New reminder")} tabIndex={-1}
          className="dialog-overlay"
          onClick={closeForm}
        >
          <div
            className="dialog-panel material-dialog max-w-md"
            onClick={(e) => e.stopPropagation()}
          >
            <button
              onClick={closeForm}
              disabled={saving} aria-label={t("Close reminder")}
              className="icon-button material-dialog-close"
            ><Icon name="close" /></button>

            <h2 className="font-sans text-2xl font-medium mb-1 tracking-tight">
              {editing ? t("Edit reminder") : t("New reminder")}
            </h2>
            <p className="text-ink-soft text-sm mb-6">
              {t("Quizzes, midterms, assignments, deadlines — anything you need to remember for this course.")}
            </p>

            {error && (
              <div role="alert" className="material-inline-notice danger mb-5">
                {error}
              </div>
            )}

            <form onSubmit={submit} className="space-y-5">
              {/* Type */}
              <div>
                <label className="block text-sm font-medium text-ink-soft mb-2">
                  {t("Type")}
                </label>
                <div className="flex flex-wrap gap-2">
                  {TYPE_ORDER.map((rt) => (
                    <button
                      key={rt}
                      type="button"
                      onClick={() => setType(rt)}
                      aria-pressed={type === rt}
                      className={`ui-button text-xs ${
                        type === rt
                          ? "bg-ink text-paper border-ink"
                          : "border-line text-ink-soft hover:bg-bg-alt"
                      }`}
                    >
                      <Icon name={REMINDER_ICONS[rt]} size={15} />
                      {t(TYPE_META[rt].label)}
                    </button>
                  ))}
                </div>
              </div>

              {/* Title */}
              <div>
                <label htmlFor="reminder-title" className="block text-sm font-medium text-ink-soft mb-2">
                  {t("Title")} <span className="text-accent">*</span>
                </label>
                <input id="reminder-title"
                  type="text"
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  placeholder={t("e.g. Quiz 2 — Chapters 3–4")}
                  className="ui-input w-full"
                  maxLength={100}
                  autoFocus
                />
              </div>

              {/* Date + time */}
              <div className="flex gap-3">
                <div className="flex-1">
                  <label htmlFor="reminder-date" className="block text-sm font-medium text-ink-soft mb-2">
                    {t("Date")}{" "}
                    <span className="text-ink-mute font-normal">({t("optional")})</span>
                  </label>
                  <input id="reminder-date"
                    type="date"
                    value={date}
                    onChange={(e) => setDate(e.target.value)}
                    className="ui-input w-full"
                  />
                </div>
                <div className="w-32">
                  <label htmlFor="reminder-time" className="block text-sm font-medium text-ink-soft mb-2">
                    {t("Time")}
                  </label>
                  <input id="reminder-time"
                    type="time"
                    value={time}
                    onChange={(e) => setTime(e.target.value)}
                    className="ui-input w-full"
                  />
                </div>
              </div>

              {/* Notes */}
              <div>
                <label htmlFor="reminder-notes" className="block text-sm font-medium text-ink-soft mb-2">
                  {t("Notes")}{" "}
                  <span className="text-ink-mute font-normal">({t("optional")})</span>
                </label>
                <textarea id="reminder-notes"
                  value={notes}
                  onChange={(e) => setNotes(e.target.value)}
                  placeholder={t("e.g. Closed book, bring calculator")}
                  rows={2}
                  className="ui-input w-full resize-none"
                  maxLength={200}
                />
              </div>

              <div className="flex gap-3 pt-1">
                <button
                  type="button"
                  onClick={closeForm}
                  className="ui-button secondary flex-1"
                >
                  {t("Cancel")}
                </button>
                <button
                  type="submit"
                  disabled={saving}
                  className="ui-button primary flex-1"
                >
                  {editing ? t("Save changes") : t("Add reminder")}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </section>
  );
}
