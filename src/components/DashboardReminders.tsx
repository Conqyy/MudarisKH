"use client";

import { useState } from "react";
import Link from "next/link";
import { Course, CourseReminder, ReminderType } from "@/lib/firestore-helpers";
import { useLang } from "@/lib/i18n";

interface Props {
  courses: Course[];
  /** Toggle a reminder's done state (persisted by the parent). */
  onToggle: (courseId: string, reminderId: string) => void | Promise<void>;
}

const TYPE_META: Record<ReminderType, { label: string; icon: string }> = {
  quiz: { label: "Quiz", icon: "✏️" },
  midterm: { label: "Midterm", icon: "📝" },
  final: { label: "Final", icon: "🎓" },
  assignment: { label: "Assignment", icon: "📌" },
  project: { label: "Project", icon: "🧩" },
  presentation: { label: "Presentation", icon: "🎤" },
  other: { label: "Other", icon: "🔔" },
};

interface AggItem extends CourseReminder {
  courseId: string;
  courseCode: string;
  courseColor: string;
}

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
  if (d === null) return { text: t("No date"), tone: "text-ink-mute bg-bg-alt" };
  if (d < 0)
    return { text: `${t("Overdue")} ${Math.abs(d)}${t("d")}`, tone: "text-accent bg-accent/10" };
  if (d === 0) return { text: t("Today"), tone: "text-accent bg-accent/10" };
  if (d === 1) return { text: t("Tomorrow"), tone: "text-gold bg-gold/10" };
  if (d <= 7) return { text: `${t("In")} ${d}${t("d")}`, tone: "text-gold bg-gold/10" };
  return { text: `${t("In")} ${d}${t("d")}`, tone: "text-ink-mute bg-bg-alt" };
}

export default function DashboardReminders({ courses, onToggle }: Props) {
  const { t } = useLang();
  const [showDone, setShowDone] = useState(false);

  const all: AggItem[] = courses.flatMap((c) =>
    (c.reminders || []).map((r) => ({
      ...r,
      courseId: c.id,
      courseCode: c.code,
      courseColor: c.color,
    }))
  );

  const open = all.filter((r) => !r.done);
  const done = all.filter((r) => r.done);

  // Sort open by soonest due (undated last).
  open.sort((a, b) => {
    const da = daysUntil(a.date);
    const db = daysUntil(b.date);
    if (da === null && db === null) return a.createdAt - b.createdAt;
    if (da === null) return 1;
    if (db === null) return -1;
    return da - db;
  });

  const overdueCount = open.filter((r) => {
    const d = daysUntil(r.date);
    return d !== null && d < 0;
  }).length;

  // Don't render the section at all if the user has no reminders anywhere.
  if (all.length === 0) return null;

  const visible = showDone ? [...open, ...done] : open;

  return (
    <section className="mt-12">
      <div className="flex items-center justify-between mb-6">
        <h2 className="font-serif text-2xl font-medium tracking-tight flex items-center gap-3">
          {t("Reminders")}
          {overdueCount > 0 ? (
            <span className="text-xs font-mono text-accent bg-accent/10 px-2.5 py-1 rounded-full">
              {overdueCount} {t("overdue")}
            </span>
          ) : open.length > 0 ? (
            <span className="text-xs font-mono text-gold bg-gold/10 px-2.5 py-1 rounded-full">
              {open.length} {t("upcoming")}
            </span>
          ) : null}
        </h2>
        {done.length > 0 && (
          <button
            onClick={() => setShowDone((s) => !s)}
            className="text-xs text-ink-mute hover:text-accent transition font-mono"
          >
            {showDone ? t("Hide done") : `${t("Show done")} (${done.length})`}
          </button>
        )}
      </div>

      {open.length === 0 && !showDone ? (
        <div className="bg-paper border border-line rounded-3xl p-8 text-center">
          <div className="text-3xl mb-2">🎉</div>
          <p className="text-ink-soft text-sm">
            {t("You're all caught up — no upcoming reminders.")}
          </p>
        </div>
      ) : (
        <div className="bg-paper border border-line rounded-3xl overflow-hidden">
          {visible.map((r, idx) => {
            const meta = TYPE_META[r.type];
            const due = dueLabel(r.date, t);
            return (
              <div
                key={`${r.courseId}-${r.id}`}
                className={`group flex items-center gap-4 p-5 transition ${
                  idx !== 0 ? "border-t border-line" : ""
                } ${r.done ? "opacity-55" : "hover:bg-bg-alt"}`}
              >
                {/* Done toggle */}
                <button
                  onClick={() => onToggle(r.courseId, r.id)}
                  title={r.done ? "Mark as not done" : "Mark as done"}
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

                {/* Title + course */}
                <div className="flex-1 min-w-0">
                  <div
                    className={`font-medium truncate ${
                      r.done ? "line-through text-ink-mute" : ""
                    }`}
                  >
                    {r.title}
                  </div>
                  <Link
                    href={`/course/${r.courseId}`}
                    className="text-xs text-ink-mute font-mono mt-0.5 inline-flex items-center gap-1.5 hover:text-accent transition"
                  >
                    <span
                      className="w-1.5 h-1.5 rounded-full"
                      style={{ background: r.courseColor }}
                    />
                    {r.courseCode}
                    <span className="text-ink-mute/60">· {t(meta.label)}</span>
                  </Link>
                </div>

                {/* Due pill */}
                {due && !r.done && (
                  <span
                    className={`text-[11px] font-mono px-2.5 py-1 rounded-full flex-shrink-0 ${due.tone}`}
                  >
                    {due.text}
                    {r.time ? ` · ${r.time}` : ""}
                  </span>
                )}
                {r.done && (
                  <span className="text-[11px] font-mono text-sage flex-shrink-0">
                    ✓ {t("Done")}
                  </span>
                )}
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}
