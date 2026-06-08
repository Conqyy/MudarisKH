"use client";

import { useState, FormEvent } from "react";
import { CourseReminder, ReminderType } from "@/lib/firestore-helpers";
import { useLang } from "@/lib/i18n";

interface Props {
  reminders: CourseReminder[];
  /** Persist the full updated list (page wires this to updateCourse). */
  onChange: (reminders: CourseReminder[]) => void | Promise<void>;
}

const TYPE_META: Record<
  ReminderType,
  { label: string; icon: string; chip: string }
> = {
  quiz: { label: "Quiz", icon: "✏️", chip: "bg-gold/10 text-gold" },
  midterm: { label: "Midterm", icon: "📝", chip: "bg-accent/10 text-accent" },
  final: { label: "Final", icon: "🎓", chip: "bg-accent/10 text-accent" },
  assignment: { label: "Assignment", icon: "📌", chip: "bg-sage/10 text-sage" },
  project: { label: "Project", icon: "🧩", chip: "bg-[#3d7a8c]/10 text-[#3d7a8c]" },
  presentation: {
    label: "Presentation",
    icon: "🎤",
    chip: "bg-[#8a6fa7]/10 text-[#8a6fa7]",
  },
  other: { label: "Other", icon: "🔔", chip: "bg-bg-alt text-ink-soft" },
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
  if (d < 0) return { text: `${t("Overdue")} ${Math.abs(d)}${t("d")}`, tone: "text-accent" };
  if (d === 0) return { text: t("Today"), tone: "text-accent" };
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

  const submit = (e: FormEvent) => {
    e.preventDefault();
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
    onChange(next);
    closeForm();
  };

  const toggleDone = (id: string) => {
    onChange(
      reminders.map((r) => (r.id === id ? { ...r, done: !r.done } : r))
    );
  };

  const remove = (r: CourseReminder) => {
    if (!confirm(`Delete reminder "${r.title}"?`)) return;
    onChange(reminders.filter((x) => x.id !== r.id));
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
      <div className="flex items-center justify-between mb-6">
        <h2 className="font-serif text-2xl font-medium tracking-tight flex items-center gap-3">
          {t("Reminders")}
          {openCount > 0 && (
            <span className="text-xs font-mono text-accent bg-accent/10 px-2.5 py-1 rounded-full">
              {openCount} {t("upcoming")}
            </span>
          )}
        </h2>
        <button
          onClick={openAdd}
          className="bg-ink text-paper px-5 py-2.5 rounded-full text-sm font-medium hover:bg-accent transition flex items-center gap-2"
        >
          <span>+</span> {t("Add")}
        </button>
      </div>

      {reminders.length === 0 ? (
        <div className="bg-paper border-2 border-dashed border-line rounded-3xl p-10 text-center">
          <div className="text-4xl mb-3 opacity-60">🔔</div>
          <h3 className="font-serif text-xl font-medium mb-2">
            {t("No reminders yet")}
          </h3>
          <p className="text-ink-soft text-sm mb-5 max-w-md mx-auto">
            {t("Track quizzes, midterms, assignments, and deadlines for this course so nothing slips through.")}
          </p>
          <button
            onClick={openAdd}
            className="bg-ink text-paper px-5 py-2.5 rounded-full text-sm font-medium hover:bg-accent transition"
          >
            + {t("Add your first reminder")}
          </button>
        </div>
      ) : (
        <div className="bg-paper border border-line rounded-3xl overflow-hidden">
          {sorted.map((r, idx) => {
            const meta = TYPE_META[r.type];
            const due = dueLabel(r.date, t);
            return (
              <div
                key={r.id}
                className={`group flex items-center gap-4 p-5 transition ${
                  idx !== 0 ? "border-t border-line" : ""
                } ${r.done ? "opacity-55" : "hover:bg-bg-alt"}`}
              >
                {/* Done toggle */}
                <button
                  onClick={() => toggleDone(r.id)}
                  title={r.done ? t("Mark as not done") : t("Mark as done")}
                  className={`w-6 h-6 rounded-full border flex items-center justify-center text-xs flex-shrink-0 transition ${
                    r.done
                      ? "bg-sage border-sage text-paper"
                      : "border-line hover:border-accent text-transparent hover:text-accent"
                  }`}
                >
                  ✓
                </button>

                {/* Type icon */}
                <div className="w-9 h-9 rounded-xl bg-bg-alt flex items-center justify-center text-base flex-shrink-0">
                  {meta.icon}
                </div>

                {/* Title + meta */}
                <div className="flex-1 min-w-0">
                  <div
                    className={`font-medium truncate ${
                      r.done ? "line-through text-ink-mute" : ""
                    }`}
                  >
                    {r.title}
                  </div>
                  <div className="text-xs text-ink-mute font-mono mt-0.5 flex items-center gap-2 flex-wrap">
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
                      <span className="text-ink-mute/70 truncate">
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
                    className="w-8 h-8 rounded-full text-ink-mute hover:bg-bg-alt hover:text-ink transition flex items-center justify-center text-sm opacity-0 group-hover:opacity-100"
                  >
                    ✎
                  </button>
                  <button
                    onClick={() => remove(r)}
                    title={t("Delete")}
                    className="w-8 h-8 rounded-full text-ink-mute hover:bg-accent hover:text-paper transition flex items-center justify-center text-sm opacity-0 group-hover:opacity-100"
                  >
                    🗑
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Add / Edit modal */}
      {showForm && (
        <div
          className="fixed inset-0 bg-ink/50 backdrop-blur-md z-[100] flex items-center justify-center p-6 animate-fade-in"
          onClick={closeForm}
        >
          <div
            className="bg-paper rounded-3xl p-8 max-w-md w-full shadow-lift relative max-h-[90vh] overflow-y-auto"
            onClick={(e) => e.stopPropagation()}
          >
            <button
              onClick={closeForm}
              className="absolute top-5 right-5 text-2xl text-ink-soft hover:text-ink leading-none w-8 h-8 flex items-center justify-center rounded-full hover:bg-bg-alt transition"
            >
              ×
            </button>

            <h2 className="font-serif text-2xl font-medium mb-1 tracking-tight">
              {editing ? t("Edit reminder") : t("New reminder")}
            </h2>
            <p className="text-ink-soft text-sm mb-6">
              {t("Quizzes, midterms, assignments, deadlines — anything you need to remember for this course.")}
            </p>

            {error && (
              <div className="bg-accent/10 border border-accent text-accent text-sm rounded-xl p-3 mb-5">
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
                      className={`px-3 py-1.5 rounded-full text-xs font-medium border transition flex items-center gap-1.5 ${
                        type === rt
                          ? "bg-ink text-paper border-ink"
                          : "border-line text-ink-soft hover:bg-bg-alt"
                      }`}
                    >
                      <span>{TYPE_META[rt].icon}</span>
                      {t(TYPE_META[rt].label)}
                    </button>
                  ))}
                </div>
              </div>

              {/* Title */}
              <div>
                <label className="block text-sm font-medium text-ink-soft mb-2">
                  {t("Title")} <span className="text-accent">*</span>
                </label>
                <input
                  type="text"
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  placeholder={t("e.g. Quiz 2 — Chapters 3–4")}
                  className="w-full px-4 py-3 border border-line rounded-xl bg-bg focus:outline-none focus:border-accent transition"
                  maxLength={100}
                  autoFocus
                />
              </div>

              {/* Date + time */}
              <div className="flex gap-3">
                <div className="flex-1">
                  <label className="block text-sm font-medium text-ink-soft mb-2">
                    {t("Date")}{" "}
                    <span className="text-ink-mute font-normal">({t("optional")})</span>
                  </label>
                  <input
                    type="date"
                    value={date}
                    onChange={(e) => setDate(e.target.value)}
                    className="w-full px-4 py-3 border border-line rounded-xl bg-bg focus:outline-none focus:border-accent transition"
                  />
                </div>
                <div className="w-32">
                  <label className="block text-sm font-medium text-ink-soft mb-2">
                    {t("Time")}
                  </label>
                  <input
                    type="time"
                    value={time}
                    onChange={(e) => setTime(e.target.value)}
                    className="w-full px-4 py-3 border border-line rounded-xl bg-bg focus:outline-none focus:border-accent transition"
                  />
                </div>
              </div>

              {/* Notes */}
              <div>
                <label className="block text-sm font-medium text-ink-soft mb-2">
                  {t("Notes")}{" "}
                  <span className="text-ink-mute font-normal">({t("optional")})</span>
                </label>
                <textarea
                  value={notes}
                  onChange={(e) => setNotes(e.target.value)}
                  placeholder={t("e.g. Closed book, bring calculator")}
                  rows={2}
                  className="w-full px-4 py-3 border border-line rounded-xl bg-bg focus:outline-none focus:border-accent transition resize-none"
                  maxLength={200}
                />
              </div>

              <div className="flex gap-3 pt-1">
                <button
                  type="button"
                  onClick={closeForm}
                  className="flex-1 border border-line py-3 rounded-full text-sm font-medium hover:bg-bg-alt transition"
                >
                  {t("Cancel")}
                </button>
                <button
                  type="submit"
                  className="flex-1 bg-ink text-paper py-3 rounded-full text-sm font-medium hover:bg-accent transition"
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
