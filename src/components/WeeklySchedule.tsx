"use client";

import { useEffect, useState, useRef, useCallback } from "react";
import Icon from "@/components/Icon";
import { Course } from "@/lib/firestore-helpers";
import { useLang } from "@/lib/i18n";

import { useOverlayMotion } from "@/lib/use-overlay-motion";
import { apiFetch } from "@/lib/api";
const API_URL =
  process.env.NEXT_PUBLIC_BACKEND_URL || "http://127.0.0.1:8000";

const DAYS = [
  { key: "sunday", label: "Sun" },
  { key: "monday", label: "Mon" },
  { key: "tuesday", label: "Tue" },
  { key: "wednesday", label: "Wed" },
  { key: "thursday", label: "Thu" },
];

const HOUR_PX = 52; // pixels per hour row

interface ScheduleEntry {
  id: string;
  day: string;
  startTime: string;
  endTime: string;
  hall: string;
  courseId?: string;
  title?: string;
}

interface WeeklyScheduleProps {
  userId: string;
  courses: Course[];
}

const toMin = (t: string) => {
  const [h, m] = (t || "").split(":");
  const hh = parseInt(h, 10);
  const mm = parseInt(m, 10);
  if (isNaN(hh) || isNaN(mm)) return null;
  return hh * 60 + mm;
};

const fmt = (mins: number) => {
  const h = Math.floor(mins / 60);
  const m = mins % 60;
  const ampm = h < 12 ? "AM" : "PM";
  const h12 = h % 12 === 0 ? 12 : h % 12;
  return `${h12}${m ? ":" + String(m).padStart(2, "0") : ""} ${ampm}`;
};

export default function WeeklySchedule({ userId, courses }: WeeklyScheduleProps) {
  const { t } = useLang();
  const [entries, setEntries] = useState<ScheduleEntry[]>([]);
  const [showForm, setShowForm] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [loadError, setLoadError] = useState("");
  const loadRequest = useRef<AbortController | null>(null);

  // A lecture usually repeats on several days (e.g. Sun/Tue/Thu). The user
  // picks all of them at once; each becomes its own calendar entry so it can
  // still be edited or deleted on its own.
  const [days, setDays] = useState<string[]>([]);
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [courseId, setCourseId] = useState("");
  const [title, setTitle] = useState("");
  const [hall, setHall] = useState("");

  // Edit dialog state
  const [editing, setEditing] = useState<ScheduleEntry | null>(null);
  const [ef, setEf] = useState({ day: "sunday", start: "", end: "", courseId: "", title: "", hall: "" });
  const [editSaving, setEditSaving] = useState(false);
  const [editError, setEditError] = useState("");
  const { ref: editDialogRef, close: dismissEditing } = useOverlayMotion(() => setEditing(null), { enabled: !!editing, canClose: !editSaving });

  const load = useCallback(async () => {
    loadRequest.current?.abort();
    const controller = new AbortController();
    loadRequest.current = controller;
    setLoadError("");
    try {
      const res = await apiFetch(API_URL + "/api/schedule/" + userId, { signal: controller.signal });
      if (!res.ok) throw new Error("Could not load schedule (" + res.status + ").");
      const data = await res.json();
      if (!controller.signal.aborted) setEntries(data.entries || []);
    } catch (error: any) {
      if (!controller.signal.aborted) setLoadError(error.message || "Could not load schedule.");
    }
  }, [userId]);
  useEffect(() => { if (userId) load(); return () => loadRequest.current?.abort(); }, [userId, load]);
  const courseOf = (e: ScheduleEntry) => courses.find((c) => c.id === e.courseId);
  const labelOf = (e: ScheduleEntry) => courseOf(e)?.code || e.title || "Lecture";
  const colorOf = (e: ScheduleEntry) => courseOf(e)?.color || "#526BCB";

  // Grid bounds: default 8:00–18:00, expand to fit entries
  let gridStart = 8 * 60;
  let gridEnd = 18 * 60;
  entries.forEach((e) => {
    const s = toMin(e.startTime);
    const en = toMin(e.endTime);
    if (s !== null) gridStart = Math.min(gridStart, s);
    if (en !== null) gridEnd = Math.max(gridEnd, en);
  });
  gridStart = Math.floor(gridStart / 60) * 60;
  gridEnd = Math.ceil(gridEnd / 60) * 60;
  const totalHours = Math.max(1, (gridEnd - gridStart) / 60);
  const hours = Array.from({ length: totalHours + 1 }, (_, i) => gridStart + i * 60);

  const toggleDay = (key: string) =>
    setDays((prev) =>
      prev.includes(key) ? prev.filter((d) => d !== key) : [...prev, key]
    );

  const resetForm = () => {
    setDays([]); setStart(""); setEnd("");
    setCourseId(courses[0]?.id || ""); setTitle(""); setHall(""); setError("");
  };

  const openForm = () => {
    setShowForm((s) => !s);
    setError("");
    setCourseId((cur) => cur || courses[0]?.id || "");
  };

  const handleAdd = async () => {
    setError("");
    if (days.length === 0) { setError("Pick at least one day."); return; }
    if (!courseId) { setError("Please select a course for this lecture."); return; }
    if (!start || !end) { setError("Enter start and end time."); return; }
    if ((toMin(end) ?? 0) <= (toMin(start) ?? 0)) { setError("End time must be after start time."); return; }
    setSaving(true);

    // One request per day, in calendar order. A day can legitimately fail on
    // its own (the backend rejects overlaps per day), so report exactly which
    // ones didn't make it instead of failing the whole batch silently.
    const chosen = DAYS.filter((d) => days.includes(d.key));
    const failures: string[] = [];
    try {
      for (const d of chosen) {
        try {
          const res = await apiFetch(`${API_URL}/api/schedule`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              user_id: userId, day: d.key, start_time: start, end_time: end,
              hall: hall.trim(), courseId, title: title.trim(),
            }),
          });
          if (!res.ok) {
            const err = await res.json().catch(() => null);
            failures.push(`${d.label}: ${err?.detail || `failed (${res.status})`}`);
          }
        } catch {
          failures.push(`${d.label}: network error`);
        }
      }

      await load();

      if (failures.length === chosen.length) {
        setError(failures.join(" · "));
        return;
      }
      if (failures.length > 0) {
        // Some days were added — keep the form open showing what to fix.
        setDays(
          chosen
            .filter((d) => failures.some((f) => f.startsWith(`${d.label}:`)))
            .map((d) => d.key)
        );
        setError(`Added the other days. Not added — ${failures.join(" · ")}`);
        return;
      }
      resetForm();
      setShowForm(false);
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (id: string) => {
    try {
      const res = await apiFetch(`${API_URL}/api/schedule/${id}`, { method: "DELETE" });
      if (!res.ok) throw new Error();
      setEntries((prev) => prev.filter((e) => e.id !== id));
    } catch {
      alert("Failed to delete.");
    }
  };

  const openEdit = (e: ScheduleEntry) => {
    setEditError("");
    setEditing(e);
    setEf({
      day: e.day,
      start: e.startTime,
      end: e.endTime,
      courseId: e.courseId || "",
      title: e.title || "",
      hall: e.hall || "",
    });
  };

  const handleUpdate = async () => {
    if (!editing) return;
    setEditError("");
    if (!ef.courseId) { setEditError("Please select a course for this lecture."); return; }
    if (!ef.start || !ef.end) { setEditError("Enter start and end time."); return; }
    if ((toMin(ef.end) ?? 0) <= (toMin(ef.start) ?? 0)) { setEditError("End time must be after start time."); return; }
    setEditSaving(true);
    try {
      const res = await apiFetch(`${API_URL}/api/schedule/${editing.id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          user_id: userId, day: ef.day, start_time: ef.start, end_time: ef.end,
          hall: ef.hall.trim(), courseId: ef.courseId, title: ef.title.trim(),
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => null);
        throw new Error(err?.detail || "Failed to update.");
      }
      setEditing(null);
      load();
    } catch (e: any) {
      setEditError(e.message || "Failed to update.");
    } finally {
      setEditSaving(false);
    }
  };

  const handleDeleteEditing = async () => {
    if (!editing) return;
    await handleDelete(editing.id);
    setEditing(null);
  };

  return (
    <section className="mb-8" id="weekly-schedule">
      {loadError && <div role="alert" className="text-sm text-accent mb-4">{loadError}<button onClick={load} className="ui-button secondary mt-2">Retry schedule</button></div>}
      <div className="flex flex-wrap items-center justify-between gap-3 mb-5">
        <div>
          <h2 className="section-heading">{t("This week")}</h2>
          <p className="text-sm text-ink-soft mt-0.5">{t("Sunday to Thursday lecture calendar.")}</p>
        </div>
        <button
          onClick={openForm}
          className="ui-button primary"
        >
          <Icon name="plus" size={17} /> {t("Add lecture")}
        </button>
      </div>

      {/* Add form */}
      {showForm && (
        <div className="ui-panel p-5 mb-6">
          {error && (
            <div role="alert" className="material-inline-notice danger mb-4">
              {error}
            </div>
          )}
          {/* Day picker — multi-select: one lecture, repeated on several days */}
          <div className="mb-4">
            <label className="block text-xs tabular-nums text-ink-mute font-medium mb-1.5">
              {t("Days")} <span className="text-accent">*</span>{" "}
              <span className="text-ink-soft font-normal">{t("(pick one or more)")}</span>
            </label>
            <div className="flex flex-wrap gap-2">
              {DAYS.map((d) => {
                const on = days.includes(d.key);
                return (
                  <button
                    key={d.key}
                    type="button"
                    aria-pressed={on}
                    onClick={() => { toggleDay(d.key); setError(""); }}
                    className={`ui-button text-xs ${
                      on
                        ? "bg-ink text-paper border-ink"
                        : "border-line text-ink-soft hover:bg-bg-alt"
                    }`}
                  >
                    {t(d.label)}
                  </button>
                );
              })}
            </div>
          </div>

          <div className="grid grid-cols-2 lg:grid-cols-5 gap-3">
            <div>
              <label htmlFor="schedule-start" className="block text-xs tabular-nums text-ink-mute font-medium mb-1.5">{t("Start")}</label>
              <input id="schedule-start" type="time" value={start} onChange={(e) => setStart(e.target.value)}
                className="ui-input w-full" />
            </div>
            <div>
              <label htmlFor="schedule-end" className="block text-xs tabular-nums text-ink-mute font-medium mb-1.5">{t("Finish")}</label>
              <input id="schedule-end" type="time" value={end} onChange={(e) => setEnd(e.target.value)}
                className="ui-input w-full" />
            </div>
            <div>
              <label htmlFor="schedule-course" className="block text-xs tabular-nums text-ink-mute font-medium mb-1.5">{t("Course")} <span className="text-accent">*</span></label>
              <select id="schedule-course" value={courseId} onChange={(e) => setCourseId(e.target.value)}
                disabled={courses.length === 0}
                className="ui-input w-full disabled:opacity-50">
                {courses.length === 0 ? (
                  <option value="">{t("No courses yet")}</option>
                ) : (
                  <>
                    <option value="">{t("Select a course")}</option>
                    {courses.map((c) => <option key={c.id} value={c.id}>{c.code} · {c.title}</option>)}
                  </>
                )}
              </select>
            </div>
            <div>
              <label htmlFor="schedule-title" className="block text-xs tabular-nums text-ink-mute font-medium mb-1.5">{t("Label")} <span className="text-ink-mute normal-case font-sans">{t("(optional)")}</span></label>
              <input id="schedule-title" type="text" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="e.g. Lab"
                className="ui-input w-full" />
            </div>
            <div>
              <label htmlFor="schedule-hall" className="block text-xs tabular-nums text-ink-mute font-medium mb-1.5">{t("Hall")}</label>
              <input id="schedule-hall" type="text" value={hall} onChange={(e) => setHall(e.target.value)} placeholder="Room 201"
                className="ui-input w-full" />
            </div>
          </div>
          <div className="flex justify-end gap-2 mt-4">
            <button onClick={() => { setShowForm(false); resetForm(); }}
              className="ui-button secondary">{t("Cancel")}</button>
            <button onClick={handleAdd} disabled={saving || days.length === 0}
              className="ui-button primary">
              {saving
                ? t("Adding…")
                : days.length > 1
                ? `${t("Add to calendar")} (${days.length} ${t("days")})`
                : t("Add to calendar")}
            </button>
          </div>
        </div>
      )}

      {/* Calendar grid */}
      <div className="ui-panel overflow-x-auto" role="region" aria-label={t("Weekly lecture calendar")} tabIndex={0}>
        <div className="min-w-[640px]">
          {/* Day header row */}
          <div className="flex border-b border-line">
            <div className="w-14 flex-shrink-0" />
            {DAYS.map((d) => (
              <div key={d.key} className="flex-1 text-center py-3 tabular-nums text-xs text-ink-mute font-medium border-s border-line">
                {t(d.label)}
              </div>
            ))}
          </div>

          {/* Time grid */}
          <div className="flex">
            {/* Time axis */}
            <div className="w-14 flex-shrink-0 relative" style={{ height: totalHours * HOUR_PX }}>
              {hours.slice(0, -1).map((h) => (
                <div key={h} className="absolute end-2 -translate-y-1/2 text-xs tabular-nums text-ink-soft"
                  style={{ top: ((h - gridStart) / 60) * HOUR_PX }}>
                  {fmt(h)}
                </div>
              ))}
            </div>

            {/* Day columns */}
            {DAYS.map((d) => {
              const dayEntries = entries.filter((e) => e.day === d.key);
              return (
                <div key={d.key} className="flex-1 relative border-s border-line"
                  style={{ height: totalHours * HOUR_PX }}>
                  {/* hour gridlines */}
                  {hours.slice(0, -1).map((h) => (
                    <div key={h} className="absolute left-0 right-0 border-t border-line/50"
                      style={{ top: ((h - gridStart) / 60) * HOUR_PX }} />
                  ))}
                  {/* entries */}
                  {dayEntries.map((e) => {
                    const s = toMin(e.startTime);
                    const en = toMin(e.endTime);
                    if (s === null || en === null) return null;
                    const top = ((s - gridStart) / 60) * HOUR_PX;
                    const height = Math.max(22, ((en - s) / 60) * HOUR_PX - 3);
                    return (
                      <div
                        key={e.id}
                        role="button" tabIndex={0} aria-label={"Edit " + labelOf(e)}
                        onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); openEdit(e); } }}
                        onClick={() => openEdit(e)}
                        title={t("Click to edit")}
                        className="material-calendar-entry absolute start-1 end-1 rounded-lg p-1.5 overflow-hidden cursor-pointer"
                        style={{ top: top + 1, height, borderInlineStartColor: colorOf(e) }}
                      >
                        <div className="text-xs tabular-nums opacity-90 leading-tight">
                          {fmt(s)}–{fmt(en)}
                        </div>
                        <div className="text-xs font-semibold leading-tight truncate">
                          {labelOf(e)}
                        </div>
                        {e.hall && height > 44 && (
                          <div className="text-xs text-ink-soft leading-tight truncate" dir="auto">{e.hall}</div>
                        )}
                      </div>
                    );
                  })}
                </div>
              );
            })}
          </div>
        </div>
      </div>

      {/* Edit dialog */}
      {editing && (
        <div
          ref={editDialogRef} role="dialog" aria-modal="true" aria-label="Edit lecture" tabIndex={-1} className="dialog-overlay"
          onClick={dismissEditing}
        >
          <div
            className="dialog-panel material-dialog max-w-lg"
            onClick={(ev) => ev.stopPropagation()}
          >
            <div className="flex items-center justify-between mb-5">
              <h3 className="section-heading">{t("Edit lecture")}</h3>
              <button
                onClick={dismissEditing}
                aria-label={t("Close dialog")}
                className="icon-button"
              >
                <Icon name="close" />
              </button>
            </div>

            {editError && (
              <div role="alert" className="material-inline-notice danger mb-4">
                {editError}
              </div>
            )}

            <div className="grid grid-cols-2 gap-3">
              <div className="col-span-2">
                <label htmlFor="schedule-edit-day" className="block text-xs tabular-nums text-ink-mute font-medium mb-1.5">{t("Day")}</label>
                <select id="schedule-edit-day" value={ef.day} onChange={(e) => setEf({ ...ef, day: e.target.value })}
                  className="ui-input w-full">
                  {DAYS.map((d) => <option key={d.key} value={d.key}>{d.label}</option>)}
                </select>
              </div>
              <div>
                <label htmlFor="schedule-edit-start" className="block text-xs tabular-nums text-ink-mute font-medium mb-1.5">{t("Start")}</label>
                <input id="schedule-edit-start" type="time" value={ef.start} onChange={(e) => setEf({ ...ef, start: e.target.value })}
                  className="ui-input w-full" />
              </div>
              <div>
                <label htmlFor="schedule-edit-end" className="block text-xs tabular-nums text-ink-mute font-medium mb-1.5">{t("Finish")}</label>
                <input id="schedule-edit-end" type="time" value={ef.end} onChange={(e) => setEf({ ...ef, end: e.target.value })}
                  className="ui-input w-full" />
              </div>
              <div className="col-span-2">
                <label htmlFor="schedule-edit-course" className="block text-xs tabular-nums text-ink-mute font-medium mb-1.5">{t("Course")} <span className="text-accent">*</span></label>
                <select id="schedule-edit-course" value={ef.courseId} onChange={(e) => setEf({ ...ef, courseId: e.target.value })}
                  className="ui-input w-full">
                  <option value="">{t("Select a course")}</option>
                  {courses.map((c) => <option key={c.id} value={c.id}>{c.code} · {c.title}</option>)}
                </select>
              </div>
              <div>
                <label htmlFor="schedule-edit-title" className="block text-xs tabular-nums text-ink-mute font-medium mb-1.5">{t("Label")} <span className="text-ink-mute normal-case font-sans">{t("(optional)")}</span></label>
                <input id="schedule-edit-title" type="text" value={ef.title} onChange={(e) => setEf({ ...ef, title: e.target.value })} placeholder="e.g. Lab"
                  className="ui-input w-full" />
              </div>
              <div>
                <label htmlFor="schedule-edit-hall" className="block text-xs tabular-nums text-ink-mute font-medium mb-1.5">{t("Hall")}</label>
                <input id="schedule-edit-hall" type="text" value={ef.hall} onChange={(e) => setEf({ ...ef, hall: e.target.value })} placeholder="Room 201"
                  className="ui-input w-full" />
              </div>
            </div>

            <div className="flex items-center justify-between mt-6">
              <button
                onClick={handleDeleteEditing}
                className="ui-button danger"
              >
                Delete lecture
              </button>
              <div className="flex gap-2">
                <button onClick={dismissEditing}
                  className="ui-button secondary">{t("Cancel")}</button>
                <button onClick={handleUpdate} disabled={editSaving}
                  className="ui-button primary">
                  {editSaving ? t("Saving…") : t("Save changes")}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
