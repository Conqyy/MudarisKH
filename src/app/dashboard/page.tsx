"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import Navbar from "@/components/Navbar";
import Sidebar from "@/components/Sidebar";
import CreateCourseModal from "@/components/CreateCourseModal";
import WeeklySchedule from "@/components/WeeklySchedule";
import DashboardReminders from "@/components/DashboardReminders";
import { useAuth } from "@/lib/auth-context";
import { useLang } from "@/lib/i18n";
import {
  getUserCourses,
  deleteCourse,
  updateCourse,
  Course,
} from "@/lib/firestore-helpers";

const API_URL =
  process.env.NEXT_PUBLIC_BACKEND_URL || "http://127.0.0.1:8000";

interface CourseStats {
  documents: number;
  audio: number;
  historical: number;
  generated: number;
}

export default function DashboardPage() {
  const { user, profile, loading } = useAuth();
  const { t } = useLang();
  const router = useRouter();

  const [courses, setCourses] = useState<Course[]>([]);
  const [stats, setStats] = useState<Record<string, CourseStats>>({});
  const [dataLoading, setDataLoading] = useState(true);
  const [showCreateCourse, setShowCreateCourse] = useState(false);
  const [showArchived, setShowArchived] = useState(false);

  // Archived courses are hidden from the active grid, stats, sidebar, and
  // reminders; they live in their own collapsible section below.
  const activeCourses = courses.filter((c) => !c.archived);
  const archivedCourses = courses.filter((c) => c.archived);

  useEffect(() => {
    if (!loading && !user) router.push("/signin");
  }, [user, loading, router]);

  useEffect(() => {
    if (!user) return;
    loadData();
  }, [user]);

  const loadData = async () => {
    if (!user) return;
    setDataLoading(true);
    try {
      const coursesData = await getUserCourses(user.uid);
      setCourses(coursesData);

      // Fetch per-course material counts from the backend (non-blocking)
      const entries = await Promise.all(
        coursesData.map(async (c) => {
          const [intel, exams] = await Promise.all([
            fetch(`${API_URL}/api/intelligence/${c.id}`)
              .then((r) => r.json())
              .catch(() => ({ counts: {} })),
            fetch(`${API_URL}/api/exams/list/${c.id}`)
              .then((r) => r.json())
              .catch(() => ({ exams: [] })),
          ]);
          const counts = intel.counts || {};
          return [
            c.id,
            {
              documents: counts.documents || 0,
              audio: counts.audio || 0,
              historical: counts.historical_exams || 0,
              generated: (exams.exams || []).length,
            },
          ] as [string, CourseStats];
        })
      );
      setStats(Object.fromEntries(entries));
    } catch (error) {
      console.error("Failed to load data:", error);
    } finally {
      setDataLoading(false);
    }
  };

  // Toggle a reminder's done state from the aggregated dashboard list and
  // persist it on the owning course doc.
  const handleToggleReminder = async (courseId: string, reminderId: string) => {
    const course = courses.find((c) => c.id === courseId);
    if (!course) return;
    const updated = (course.reminders || []).map((r) =>
      r.id === reminderId ? { ...r, done: !r.done } : r
    );
    setCourses((prev) =>
      prev.map((c) => (c.id === courseId ? { ...c, reminders: updated } : c))
    );
    try {
      await updateCourse(courseId, { reminders: updated });
    } catch (error) {
      console.error("Failed to update reminder:", error);
    }
  };

  const getGreeting = () => {
    const h = new Date().getHours();
    if (h < 12) return t("Good morning");
    if (h < 17) return t("Good afternoon");
    return t("Good evening");
  };

  // Archive / restore a course from its card. Optimistic update; reconcile on error.
  const handleToggleArchive = async (e: React.MouseEvent, course: Course) => {
    e.preventDefault();
    e.stopPropagation();
    const next = !course.archived;
    setCourses((prev) =>
      prev.map((c) => (c.id === course.id ? { ...c, archived: next } : c))
    );
    try {
      await updateCourse(course.id, { archived: next });
    } catch (error) {
      console.error("Failed to update archive state:", error);
      loadData();
    }
  };

  const totals = activeCourses.reduce(
    (acc, c) => {
      const s = stats[c.id];
      if (s) {
        acc.documents += s.documents;
        acc.historical += s.historical;
        acc.generated += s.generated;
      }
      return acc;
    },
    { documents: 0, historical: 0, generated: 0 }
  );

  const getDaysUntilExam = (examDate?: string) => {
    if (!examDate) return null;
    const days = Math.ceil(
      (new Date(examDate).getTime() - Date.now()) / (1000 * 60 * 60 * 24)
    );
    return days > 0 ? days : null;
  };

  // Soonest upcoming exam, for the status line
  const upcomingExam = activeCourses
    .map((c) => ({ c, d: getDaysUntilExam(c.examDate) }))
    .filter((x) => x.d !== null)
    .sort((a, b) => (a.d! - b.d!))[0];

  const getStatusMessage = () => {
    if (activeCourses.length === 0)
      return t("Create a course to start building your exam prep.");
    if (upcomingExam)
      return `${upcomingExam.c.code} — ${t("exam in")} ${upcomingExam.d} ${t("days")}`;
    if (totals.generated > 0)
      return `${t("You've generated")} ${totals.generated} ${t("practice exams. Keep practicing.")}`;
    return t("Upload your lecture documents and past exams to generate practice exams.");
  };

  const handleDeleteCourse = async (e: React.MouseEvent, courseId: string) => {
    e.preventDefault();
    e.stopPropagation();
    if (
      !confirm(
        "Delete this course? Uploaded materials for it will remain on the server."
      )
    )
      return;
    try {
      await deleteCourse(courseId);
      loadData();
    } catch (error) {
      console.error(error);
      alert("Failed to delete course.");
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="font-mono text-sm text-ink-mute">{t("Loading…")}</div>
      </div>
    );
  }

  if (!user) return null;

  const statCards = [
    { label: t("Courses"), value: activeCourses.length, accent: "text-ink", note: t("active subjects") },
    { label: t("Documents"), value: totals.documents, accent: "text-sage", note: t("analyzed") },
    { label: t("Past Exams"), value: totals.historical, accent: "text-gold", note: t("analyzed") },
    { label: t("Practice Exams"), value: totals.generated, accent: "text-accent", note: t("generated") },
  ];

  return (
    <>
      <Navbar />

      <div className="pt-20 flex">
        <Sidebar courses={activeCourses} />

        <main className="flex-1 px-6 md:px-10 lg:px-12 pb-20 max-w-7xl mx-auto w-full">
          {/* Header */}
          <div className="flex flex-col md:flex-row md:items-start md:justify-between gap-6 my-10">
            <div>
              <h1 className="font-serif text-4xl md:text-5xl font-normal tracking-tight leading-tight mb-2">
                {getGreeting()},{" "}
                <em className="italic text-accent">
                  {profile?.fullName?.split(" ")[0] || t("Student")}
                </em>
              </h1>
              <p className="text-ink-soft">{getStatusMessage()}</p>
            </div>

            <div className="flex gap-3 flex-shrink-0">
              <button
                onClick={() => setShowCreateCourse(true)}
                className="bg-accent text-paper px-5 py-3 rounded-full text-sm font-medium hover:bg-ink transition flex items-center gap-2"
              >
                <span>+</span> {t("New Course")}
              </button>
            </div>
          </div>

          {/* Stats */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-12">
            {statCards.map((s) => (
              <div key={s.label} className="bg-paper border border-line rounded-2xl p-7">
                <div className="font-mono text-xs text-ink-mute uppercase tracking-widest mb-3">
                  {s.label}
                </div>
                <div className={`font-serif text-5xl font-medium tracking-tight ${s.accent}`}>
                  {s.value}
                </div>
                <div className="text-sm text-ink-mute mt-2 font-mono">{s.note}</div>
              </div>
            ))}
          </div>

          {/* Courses */}
          <section>
            <h2 className="font-serif text-2xl font-medium mb-6 tracking-tight">
              {t("Your courses")}
            </h2>

            {dataLoading ? (
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
                {[0, 1, 2].map((i) => (
                  <div
                    key={i}
                    className="bg-paper border border-line rounded-3xl p-7 animate-pulse h-44"
                  />
                ))}
              </div>
            ) : activeCourses.length === 0 ? (
              <div className="bg-paper border-2 border-dashed border-line rounded-3xl p-16 text-center">
                <div className="text-5xl mb-4">📚</div>
                <h3 className="font-serif text-2xl font-medium mb-2">
                  {archivedCourses.length > 0
                    ? t("No active courses")
                    : t("No courses yet")}
                </h3>
                <p className="text-ink-soft mb-6 max-w-md mx-auto">
                  {archivedCourses.length > 0
                    ? t("All your courses are archived. Restore one below, or create a new course.")
                    : t("Create your first course, then upload its lecture documents and past exams to generate AI practice exams.")}
                </p>
                <button
                  onClick={() => setShowCreateCourse(true)}
                  className="bg-accent text-paper px-6 py-3 rounded-full text-sm font-medium hover:bg-ink transition"
                >
                  + {t("Create your first course")}
                </button>
              </div>
            ) : (
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
                {activeCourses.map((course) => {
                  const daysUntilExam = getDaysUntilExam(course.examDate);
                  const s = stats[course.id] || {
                    documents: 0,
                    audio: 0,
                    historical: 0,
                    generated: 0,
                  };
                  const ready = s.documents > 0 && s.historical > 0;
                  return (
                    <Link
                      key={course.id}
                      href={`/course/${course.id}`}
                      className="group bg-paper border border-line rounded-3xl p-7 hover:-translate-y-1 hover:shadow-lift transition-all relative overflow-hidden block"
                      style={{ borderTop: `4px solid ${course.color}` }}
                    >
                      <button
                        onClick={(e) => handleDeleteCourse(e, course.id)}
                        className="absolute top-4 right-4 w-7 h-7 rounded-full bg-bg-alt text-ink-mute opacity-0 group-hover:opacity-100 hover:bg-accent hover:text-paper transition flex items-center justify-center text-sm"
                        title="Delete course"
                      >
                        ×
                      </button>
                      <button
                        onClick={(e) => handleToggleArchive(e, course)}
                        className="absolute top-4 right-12 w-7 h-7 rounded-full bg-bg-alt text-ink-mute opacity-0 group-hover:opacity-100 hover:bg-ink hover:text-paper transition flex items-center justify-center text-xs"
                        title={t("Archive course")}
                      >
                        ⤓
                      </button>

                      <div className="flex items-center gap-2 mb-2">
                        <span className="font-mono text-xs text-ink-mute uppercase tracking-widest">
                          {course.code}
                        </span>
                        {ready && (
                          <span className="text-[10px] font-mono bg-sage/10 text-sage px-2 py-0.5 rounded-full">
                            {t("exam-ready")}
                          </span>
                        )}
                      </div>
                      <h3 className="font-serif text-xl font-medium mb-1.5 tracking-tight pr-6">
                        {course.title}
                      </h3>
                      <p className="text-sm text-ink-soft mb-5">
                        {course.instructor}
                      </p>

                      {/* Material chips */}
                      <div className="flex flex-wrap gap-1.5 mb-5">
                        <span className="text-[11px] font-mono bg-sage/10 text-sage px-2.5 py-1 rounded-full">
                          {s.documents} doc{s.documents === 1 ? "" : "s"}
                        </span>
                        <span className="text-[11px] font-mono bg-gold/10 text-gold px-2.5 py-1 rounded-full">
                          {s.historical} past exam{s.historical === 1 ? "" : "s"}
                        </span>
                        <span className="text-[11px] font-mono bg-accent/10 text-accent px-2.5 py-1 rounded-full">
                          {s.generated} practice
                        </span>
                      </div>

                      <div className="flex justify-between items-end pt-4 border-t border-line">
                        <span className="text-xs text-accent font-medium opacity-0 group-hover:opacity-100 transition">
                          {t("Open course")} →
                        </span>
                        {daysUntilExam !== null && (
                          <div className="text-right">
                            <div
                              className={`font-serif text-xl font-medium ${
                                daysUntilExam <= 7 ? "text-accent" : ""
                              }`}
                            >
                              {daysUntilExam}d
                            </div>
                            <div className="text-[10px] text-ink-mute font-mono uppercase tracking-wider mt-0.5">
                              {t("Until exam")}
                            </div>
                          </div>
                        )}
                      </div>
                    </Link>
                  );
                })}
              </div>
            )}
          </section>

          {/* Archived courses — collapsed by default, restorable */}
          {!dataLoading && archivedCourses.length > 0 && (
            <section className="mt-12">
              <button
                onClick={() => setShowArchived((v) => !v)}
                className="w-full flex items-center justify-between bg-bg-alt/60 border border-line rounded-2xl px-6 py-4 hover:bg-bg-alt transition"
              >
                <span className="flex items-center gap-3">
                  <span className="text-lg">🗄</span>
                  <span className="font-serif text-lg font-medium tracking-tight">
                    {t("Archived courses")}
                  </span>
                  <span className="text-xs font-mono bg-paper border border-line text-ink-mute px-2 py-0.5 rounded-full">
                    {archivedCourses.length}
                  </span>
                </span>
                <span
                  className={`text-ink-mute transition-transform ${
                    showArchived ? "rotate-180" : ""
                  }`}
                >
                  ▾
                </span>
              </button>

              {showArchived && (
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5 mt-5">
                  {archivedCourses.map((course) => (
                    <Link
                      key={course.id}
                      href={`/course/${course.id}`}
                      className="group bg-paper/70 border border-line rounded-3xl p-6 hover:shadow-soft transition-all relative block opacity-75 hover:opacity-100"
                      style={{ borderTop: `4px solid ${course.color}55` }}
                    >
                      <button
                        onClick={(e) => handleDeleteCourse(e, course.id)}
                        className="absolute top-4 right-4 w-7 h-7 rounded-full bg-bg-alt text-ink-mute opacity-0 group-hover:opacity-100 hover:bg-accent hover:text-paper transition flex items-center justify-center text-sm"
                        title="Delete course"
                      >
                        ×
                      </button>

                      <div className="flex items-center gap-2 mb-2">
                        <span className="font-mono text-xs text-ink-mute uppercase tracking-widest">
                          {course.code}
                        </span>
                        <span className="text-[10px] font-mono bg-bg-alt text-ink-mute px-2 py-0.5 rounded-full">
                          {t("Archived")}
                        </span>
                      </div>
                      <h3 className="font-serif text-lg font-medium mb-1 tracking-tight pr-6">
                        {course.title}
                      </h3>
                      <p className="text-sm text-ink-mute mb-4">
                        {course.instructor}
                      </p>

                      <button
                        onClick={(e) => handleToggleArchive(e, course)}
                        className="text-xs font-medium border border-line px-4 py-2 rounded-full hover:bg-ink hover:text-paper hover:border-ink transition"
                      >
                        ↩ {t("Unarchive")}
                      </button>
                    </Link>
                  ))}
                </div>
              )}
            </section>
          )}

          {/* Reminders — aggregated across active courses */}
          {!dataLoading && (
            <DashboardReminders
              courses={activeCourses}
              onToggle={handleToggleReminder}
            />
          )}

          {/* Weekly schedule */}
          <div className="mt-12">
            {user && <WeeklySchedule userId={user.uid} courses={activeCourses} />}
          </div>
        </main>
      </div>

      {showCreateCourse && (
        <CreateCourseModal
          existingCoursesCount={courses.length}
          onClose={() => setShowCreateCourse(false)}
          onSuccess={loadData}
        />
      )}
    </>
  );
}
