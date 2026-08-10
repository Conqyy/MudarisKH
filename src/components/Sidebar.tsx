"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { Course } from "@/lib/firestore-helpers";
import { useAuth } from "@/lib/auth-context";
import { useLang } from "@/lib/i18n";
import { useSidebar } from "@/lib/sidebar";

interface SidebarProps {
  courses: Course[];
}

export default function Sidebar({ courses }: SidebarProps) {
  const pathname = usePathname();
  const router = useRouter();
  const { signOut } = useAuth();
  const { t, dir } = useLang();
  const { collapsed, setCollapsed, toggle } = useSidebar();

  // Archived courses are hidden from the main list, but reachable through a
  // collapsed "Archived" toggle below it.
  const visibleCourses = courses.filter((c) => !c.archived);
  const archivedCourses = courses.filter((c) => c.archived);
  const [showArchived, setShowArchived] = useState(false);

  const handleSignOut = async () => {
    await signOut();
    router.push("/");
  };

  // The archived list has no room on a collapsed rail, so opening it opens the
  // rail too.
  const handleArchived = () => {
    if (collapsed) {
      setCollapsed(false);
      setShowArchived(true);
      return;
    }
    setShowArchived((v) => !v);
  };

  const isActive = (path: string) => pathname === path;

  // The chevron points at the edge the rail moves toward, which flips in RTL
  // (the panel sits on the right).
  const chevron =
    dir === "rtl" ? (collapsed ? "«" : "»") : collapsed ? "»" : "«";
  const toggleLabel = collapsed ? t("Expand sidebar") : t("Collapse sidebar");

  const itemBase =
    "sidebar-item flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition";

  return (
    // Outer element reserves the rail's column in the flex row so the main
    // content never slides under the panel. The inner panel is `fixed` (immune
    // to the `overflow-x: hidden` on <body> that breaks `position: sticky`), so
    // it always spans from the navbar to the bottom of the viewport. Both are
    // sized by .sidebar-rail — see globals.css.
    <aside className="sidebar-rail flex-shrink-0 hidden md:block">
      <div className="sidebar-rail sidebar-panel fixed top-20 bottom-0 start-0 bg-paper border-e border-line flex flex-col overflow-y-auto overflow-x-hidden">
      {/* COLLAPSE TOGGLE — a full labelled row, so it reads as a control rather
          than decoration; collapsing shrinks it to a centered chevron button. */}
      <button
        onClick={toggle}
        title={toggleLabel}
        aria-label={toggleLabel}
        aria-expanded={!collapsed}
        className={`${itemBase} w-full mb-4 border border-line bg-bg-alt text-ink-soft hover:border-accent hover:text-ink`}
      >
        <span className="text-base">{chevron}</span>
        <span className="sidebar-label font-medium">{toggleLabel}</span>
      </button>

      {/* WORKSPACE */}
      <div className="mb-8">
        <div className="sidebar-heading font-mono text-[11px] uppercase tracking-widest text-ink-mute mb-3 px-3">
          <span className="sidebar-label">{t("Workspace")}</span>
        </div>

        <Link
          href="/dashboard"
          title={t("Dashboard")}
          className={`${itemBase} mb-0.5 ${
            isActive("/dashboard")
              ? "bg-ink text-paper"
              : "text-ink-soft hover:bg-bg-alt hover:text-ink"
          }`}
        >
          <span className="text-base opacity-70">⌂</span>
          <span className="sidebar-label">{t("Dashboard")}</span>
        </Link>

        <Link
          href="/dashboard/recent"
          title={t("Recent")}
          className={`${itemBase} mb-0.5 ${
            isActive("/dashboard/recent")
              ? "bg-ink text-paper"
              : "text-ink-soft hover:bg-bg-alt hover:text-ink"
          }`}
        >
          <span className="text-base opacity-70">◷</span>
          <span className="sidebar-label">{t("Recent")}</span>
        </Link>

        <Link
          href="/dashboard/bookmarked"
          title={t("Bookmarked")}
          className={`${itemBase} ${
            isActive("/dashboard/bookmarked")
              ? "bg-ink text-paper"
              : "text-ink-soft hover:bg-bg-alt hover:text-ink"
          }`}
        >
          <span className="text-base opacity-70">★</span>
          <span className="sidebar-label">{t("Bookmarked")}</span>
        </Link>

        {/* Archived courses — collapsed toggle, muted list */}
        {archivedCourses.length > 0 && (
          <>
            <button
              onClick={handleArchived}
              title={t("Archived")}
              className={`${itemBase} w-full text-ink-soft hover:bg-bg-alt hover:text-ink mt-0.5`}
            >
              <span className="text-base opacity-70">🗄</span>
              <span className="sidebar-label flex-1 text-start truncate">
                {t("Archived")}
              </span>
              <span className="sidebar-label font-mono text-[10px] bg-bg-alt px-1.5 py-0.5 rounded-full">
                {archivedCourses.length}
              </span>
              <span
                className={`sidebar-label text-[10px] transition-transform ${
                  showArchived ? "rotate-180" : ""
                }`}
              >
                ▾
              </span>
            </button>

            {showArchived &&
              archivedCourses.map((course) => (
                <Link
                  key={course.id}
                  href={`/course/${course.id}`}
                  title={course.code}
                  className={`${itemBase} ps-6 text-ink-mute hover:bg-bg-alt hover:text-ink mb-0.5 opacity-70 hover:opacity-100`}
                >
                  <span
                    className="w-2 h-2 rounded-full flex-shrink-0 opacity-50"
                    style={{ background: course.color }}
                  />
                  <span className="sidebar-label truncate">{course.code}</span>
                </Link>
              ))}
          </>
        )}
      </div>

      {/* COURSES */}
      <div className="mb-8">
        <div className="sidebar-heading font-mono text-[11px] uppercase tracking-widest text-ink-mute mb-3 px-3">
          <span className="sidebar-label">{t("Courses")}</span>
        </div>

        {visibleCourses.length === 0 ? (
          <div className="sidebar-label text-xs text-ink-mute px-3 py-2">
            {t("No courses yet")}
          </div>
        ) : (
          visibleCourses.map((course) => (
            <Link
              key={course.id}
              href={`/course/${course.id}`}
              title={course.code}
              className={`${itemBase} text-ink-soft hover:bg-bg-alt hover:text-ink mb-0.5`}
            >
              <span
                className="w-2 h-2 rounded-full flex-shrink-0"
                style={{ background: course.color }}
              />
              <span className="sidebar-label truncate">{course.code}</span>
            </Link>
          ))
        )}

      </div>

      {/* Spacer pushes Account to the bottom and fills the panel */}
      <div className="flex-1 min-h-6" />

      {/* ACCOUNT */}
      <div className="pt-2 border-t border-line">
        {/* No .sidebar-heading here — the wrapper's border-t is already the
            divider this group gets when collapsed. */}
        <div className="font-mono text-[11px] uppercase tracking-widest text-ink-mute mb-3 px-3 mt-2">
          <span className="sidebar-label">{t("Account")}</span>
        </div>

        <Link
          href="/settings"
          title={t("Settings")}
          className={`${itemBase} text-ink-soft hover:bg-bg-alt hover:text-ink mb-0.5`}
        >
          <span className="text-base opacity-70">◉</span>
          <span className="sidebar-label">{t("Settings")}</span>
        </Link>

        <button
          onClick={handleSignOut}
          title={t("Sign Out")}
          className={`${itemBase} w-full text-ink-soft hover:bg-bg-alt hover:text-ink text-start`}
        >
          <span className="text-base opacity-70">↩</span>
          <span className="sidebar-label">{t("Sign Out")}</span>
        </button>
      </div>
      </div>
    </aside>
  );
}
