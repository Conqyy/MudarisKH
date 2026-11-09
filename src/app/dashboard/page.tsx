"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import AppShell from "@/components/AppShell";
import Icon from "@/components/Icon";
import CreateCourseModal from "@/components/CreateCourseModal";
import WeeklySchedule from "@/components/WeeklySchedule";
import DashboardReminders from "@/components/DashboardReminders";
import { useAuth } from "@/lib/auth-context";
import { useLang } from "@/lib/i18n";
import { apiFetch } from "@/lib/api";
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
  const [dataError, setDataError] = useState<string | null>(null);
  const [mutationError, setMutationError] = useState<string | null>(null);
  const [statsError, setStatsError] = useState(false);
  const [statsLoading, setStatsLoading] = useState(false);
  const loadVersion = useRef(0);
  const pendingCourses = useRef(new Set<string>());
  const activeUid = useRef(user?.uid);
  activeUid.current = user?.uid;
  const invalidateLoads = useCallback(() => { ++loadVersion.current; }, []);

  // Archived courses are hidden from the active grid, stats, sidebar, and
  // reminders; they live in their own collapsible section below.
  const activeCourses = courses.filter((c) => !c.archived);
  const archivedCourses = courses.filter((c) => c.archived);

  useEffect(() => {
    if (!loading && !user) router.push("/signin");
  }, [user, loading, router]);

  const loadData = useCallback(async () => {
    if (!user || user.uid !== activeUid.current) return;
    const version = ++loadVersion.current;
    setDataLoading(true);
    setDataError(null);
    setStatsError(false);
    try {
      const coursesData = await getUserCourses(user.uid);
      if (version !== loadVersion.current) return;
      setCourses(coursesData);
      setDataLoading(false);
      setStatsLoading(true);

      // Counts enrich the cards after courses are available for navigation.
      let countsFailed = false;
      const readCounts = async (url: string) => {
        const response = await apiFetch(url);
        if (!response.ok) throw new Error("Course statistics could not be loaded.");
        return response.json();
      };
      void Promise.all(
        coursesData.filter((c) => !c.archived).map(async (c) => {
          const [intel, exams] = await Promise.all([
            readCounts(`${API_URL}/api/intelligence/${c.id}`)
              .catch(() => { countsFailed = true; return { counts: {} }; }),
            readCounts(`${API_URL}/api/exams/list/${c.id}`)
              .catch(() => { countsFailed = true; return { exams: [] }; }),
          ]);
          const counts = intel.counts || {};
          return [
            c.id,
            {
              documents: counts.documents || 0,
              audio: counts.audio || 0,
              historical: counts.historical_exams || 0,
              generated: Array.isArray(exams.exams) ? exams.exams.length : 0,
            },
          ] as [string, CourseStats];
        })
      ).then((entries) => {
        if (version !== loadVersion.current) return;
        setStats(Object.fromEntries(entries));
        setStatsError(countsFailed);
        setStatsLoading(false);
      }).catch(() => {
        if (version !== loadVersion.current) return;
        setStatsError(true);
        setStatsLoading(false);
      });
    } catch (error) {
      console.error("Failed to load data:", error);
      if (version === loadVersion.current) {
        setDataError(error instanceof Error ? error.message : "Could not load courses. Please retry.");
      }
    } finally {
      if (version === loadVersion.current) setDataLoading(false);
    }
  }, [user]);

  useEffect(() => {
    setCourses([]);
    setStats({});
    setMutationError(null);
    if (user) void loadData();
    return invalidateLoads;
  }, [user, loadData, invalidateLoads]);

  // Toggle a reminder's done state from the aggregated dashboard list and
  // persist it on the owning course doc.
  const handleToggleReminder = async (courseId: string, reminderId: string) => {
    const course = courses.find((c) => c.id === courseId);
    if (!course || pendingCourses.current.has(courseId)) return;
    pendingCourses.current.add(courseId);
    setMutationError(null);
    const updated = (course.reminders || []).map((r) =>
      r.id === reminderId ? { ...r, done: !r.done } : r
    );
    try {
      const saved = await updateCourse(courseId, { reminders: updated }, { reminders: course.reminders || [] });
      if (user?.uid !== activeUid.current) return;
      setCourses((prev) =>
        prev.map((c) => (c.id === courseId ? { ...c, reminders: saved.reminders } : c))
      );
    } catch (error) {
      console.error("Failed to update reminder:", error);
      if (user?.uid === activeUid.current) setMutationError(error instanceof Error ? error.message : "Could not save reminder. Please retry.");
    } finally {
      pendingCourses.current.delete(courseId);
    }
  };

  const getGreeting = () => {
    const h = new Date().getHours();
    if (h < 12) return t("Good morning");
    if (h < 17) return t("Good afternoon");
    return t("Good evening");
  };

  // Keep the course visible until archive/restore is persisted.
  const handleToggleArchive = async (e: React.MouseEvent, course: Course) => {
    e.preventDefault();
    e.stopPropagation();
    if (pendingCourses.current.has(course.id)) return;
    pendingCourses.current.add(course.id);
    setMutationError(null);
    const next = !course.archived;
    try {
      await updateCourse(course.id, { archived: next });
      if (user?.uid !== activeUid.current) return;
      setCourses((prev) =>
        prev.map((c) => (c.id === course.id ? { ...c, archived: next } : c))
      );
      void loadData();
    } catch (error) {
      console.error("Failed to update archive state:", error);
      if (user?.uid === activeUid.current) setMutationError(error instanceof Error ? error.message : "Could not save archive state. Please retry.");
    } finally {
      pendingCourses.current.delete(course.id);
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

  const getStatusMessage = () => {
    if (activeCourses.length === 0)
      return t("Create a course to start building your exam prep.");
    if (totals.generated > 0)
      return `${t("You've generated")} ${totals.generated} ${t("practice exams. Keep practicing.")}`;
    return t("Upload your lecture documents and past exams to generate practice exams.");
  };

  const handleDeleteCourse = async (e: React.MouseEvent, courseId: string) => {
    e.preventDefault();
    e.stopPropagation();
    if (pendingCourses.current.has(courseId)) return;
    if (
      !confirm(
        "Permanently delete this course and all its uploaded files, study materials, chats, and schedule entries?"
      )
    )
      return;
    pendingCourses.current.add(courseId);
    try {
      await deleteCourse(courseId);
      if (user?.uid !== activeUid.current) return;
      setCourses((prev) => prev.filter((course) => course.id !== courseId));
      await loadData();
    } catch (error) {
      console.error(error);
      if (user?.uid === activeUid.current) alert(error instanceof Error ? error.message : "Failed to delete course. Please retry.");
    } finally {
      pendingCourses.current.delete(courseId);
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
    { label: t("Courses"), value: activeCourses.length, note: t("active subjects"), icon: "folder" as const },
    { label: t("Documents"), value: totals.documents, note: t("analyzed"), icon: "file" as const },
    { label: t("Past Exams"), value: totals.historical, note: t("analyzed"), icon: "exam" as const },
    { label: t("Practice Exams"), value: totals.generated, note: t("generated"), icon: "layers" as const },
  ];
  const courseCard = (course: Course, archived = false) => {
    const statsForCourse = stats[course.id];
    return <article className={"dashboard-course-card ui-panel " + (archived ? "is-archived" : "")} key={course.id}>
      <div className="dashboard-course-top">
        <span className="course-identity-icon" style={{ borderBottomColor: course.color }}><Icon name="book" size={22} /></span>
        <span className="course-code">{course.code}</span>
        <div className="dashboard-course-actions">
          <button onClick={e => handleToggleArchive(e, course)} className="icon-button" title={archived ? t("Unarchive") : t("Archive course")} aria-label={(archived ? t("Unarchive") : t("Archive course")) + " " + course.code}><Icon name={archived ? "refresh" : "archive"} size={17} /></button>
          <button onClick={e => handleDeleteCourse(e, course.id)} className="icon-button" title="Delete course" aria-label={t("Delete course") + " " + course.code}><Icon name="trash" size={17} /></button>
        </div>
      </div>
      <Link href={"/course/" + course.id} className="dashboard-course-link">
        <h3>{course.title}</h3><p>{course.instructor || "—"}</p>
        <div className="dashboard-course-counts">
          <span><Icon name="file" size={14} />{statsForCourse ? statsForCourse.documents : "…"} {t("Documents")}</span>
          <span><Icon name="exam" size={14} />{statsForCourse ? statsForCourse.historical : "…"} {t("Past Exams")}</span>
          <span><Icon name="layers" size={14} />{statsForCourse ? statsForCourse.generated : "…"} {t("Practice Exams")}</span>
        </div>
        <span className="dashboard-course-open">{t("Open course")}<Icon name="arrow-right" size={17} /></span>
      </Link>
    </article>;
  };

  return <>
    <AppShell courses={activeCourses}>
      <main className="workspace-main dashboard-page">
        <header className="page-header">
          <div><h1 className="page-heading">{getGreeting()}, {profile?.fullName?.split(" ")[0] || t("Student")}</h1><p className="page-subtitle">{getStatusMessage()}</p></div>
          <button onClick={() => setShowCreateCourse(true)} className="ui-button primary"><Icon name="plus" size={17} />{t("New Course")}</button>
        </header>
        {(dataError || mutationError || statsError) && <div role="alert" className="ui-notice danger mb-6"><Icon name="alert" size={18} /><div><p>{dataError || mutationError || t("Some course statistics could not be loaded.")}</p>{(dataError || statsError) && <button onClick={() => void loadData()} className="mt-2 underline font-semibold">{t("Retry")}</button>}</div></div>}
        <div className="dashboard-statistics">
          {statCards.map((s, i) => <div className="dashboard-stat" key={s.label}><span className={"dashboard-stat-icon stat-tone-" + i}><Icon name={s.icon} size={21} /></span><div><span className="dashboard-stat-label">{s.label}</span><strong>{dataLoading || (statsLoading && i > 0) ? "…" : s.value}</strong><span className="dashboard-stat-note">{s.note}</span></div></div>)}
        </div>
        <section id="courses" className="dashboard-course-section">
          <div className="section-heading"><h2>{t("Your courses")}</h2><span className="text-xs text-ink-soft">{activeCourses.length} {t("active subjects")}</span></div>
          {dataLoading ? <div className="dashboard-courses">{[0,1,2].map(i => <div key={i} className="ui-panel h-48 animate-pulse" />)}</div>
            : dataError ? null : activeCourses.length === 0 ? <div className="dashboard-empty ui-panel"><span className="course-identity-icon"><Icon name="folder" size={26} /></span><h3>{archivedCourses.length > 0 ? t("No active courses") : t("No courses yet")}</h3><p>{archivedCourses.length > 0 ? t("All your courses are archived. Restore one below, or create a new course.") : t("Create your first course, then upload its lecture documents and past exams to generate AI practice exams.")}</p><button className="ui-button primary" onClick={() => setShowCreateCourse(true)}><Icon name="plus" size={17} />{t("Create your first course")}</button></div>
            : <div className="dashboard-courses">{activeCourses.map(c => courseCard(c))}</div>}
        </section>
        {!dataLoading && archivedCourses.length > 0 && <section className="mt-6"><button onClick={() => setShowArchived(v => !v)} aria-expanded={showArchived} className="ui-button secondary"><Icon name="archive" size={17} />{t("Archived courses")}<span className="status-badge">{archivedCourses.length}</span><Icon name="chevron-down" size={15} /></button>{showArchived && <div className="dashboard-courses mt-4">{archivedCourses.map(c => courseCard(c, true))}</div>}</section>}
        <div className="dashboard-planning">
          <section className="dashboard-reminders">{!dataLoading && <DashboardReminders courses={activeCourses} onToggle={handleToggleReminder} />}</section>
          <section id="schedule" className="dashboard-schedule">{user && <WeeklySchedule userId={user.uid} courses={activeCourses} />}</section>
        </div>
      </main>
    </AppShell>
    {showCreateCourse && <CreateCourseModal existingCoursesCount={courses.length} onClose={() => setShowCreateCourse(false)} onSuccess={loadData} />}
  </>;
}
