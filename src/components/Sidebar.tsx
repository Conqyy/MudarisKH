"use client";

import { useState, type CSSProperties } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import type { Course } from "@/lib/firestore-helpers";
import { useAuth } from "@/lib/auth-context";
import { useLang } from "@/lib/i18n";
import { useSidebar } from "@/lib/sidebar";
import { useOverlayMotion } from "@/lib/use-overlay-motion";
import { useSidebarLayoutMotion } from "@/lib/use-sidebar-layout-motion";
import Icon, { BrandMark, type IconName } from "./Icon";

export default function Sidebar({ courses, mobileOpen = false, onClose = () => {} }: {
  courses: Course[]; mobileOpen?: boolean; onClose?: () => void;
}) {
  const pathname = usePathname();
  const router = useRouter();
  const { signOut } = useAuth();
  const { t, dir } = useLang();
  const { collapsed, setCollapsed, toggle } = useSidebar();
  const [showArchived, setShowArchived] = useState(false);
  const { ref: dialogRef, close: closeNavigation } = useOverlayMotion(onClose, { enabled: mobileOpen, kind: "drawer" });
  const animateChange = useSidebarLayoutMotion(collapsed, dialogRef);
  const visibleCourses = courses.filter(c => !c.archived);
  const archivedCourses = courses.filter(c => c.archived);
  const links: { href: string; label: string; icon: IconName }[] = [
    { href: "/dashboard", label: "Dashboard", icon: "grid" },
    { href: "/dashboard#courses", label: "Courses", icon: "folder" },
    { href: "/dashboard/recent", label: "Recent", icon: "history" },
    { href: "/dashboard/bookmarked", label: "Bookmarked", icon: "bookmark" },
    { href: "/dashboard#schedule", label: "Weekly schedule", icon: "calendar" },
  ];
  const toggleLabel = collapsed ? t("Expand sidebar") : t("Collapse sidebar");
  const renderCourse = (course: Course) => <Link key={course.id} href={"/course/" + course.id} title={course.code + " · " + course.title} aria-label={course.code + " · " + course.title} onClick={onClose} aria-current={pathname?.startsWith("/course/" + course.id) ? "page" : undefined} className={"sidebar-item " + (pathname?.startsWith("/course/" + course.id) ? "is-active" : "")}>
    <span className="sidebar-course-marker" style={{ "--course-color": course.color } as CSSProperties}>{course.code.slice(0,2)}</span><span className="sidebar-label truncate">{course.code}</span>
  </Link>;
  return <aside className={"sidebar-rail " + (mobileOpen ? "mobile-open" : "")} aria-label={t("Workspace navigation")}>
    {mobileOpen && <button className="mobile-navigation-backdrop" onClick={closeNavigation} aria-label={t("Close navigation")} tabIndex={-1} />}
    <div className="sidebar-panel" ref={dialogRef} role={mobileOpen ? "dialog" : undefined} aria-modal={mobileOpen ? true : undefined} aria-label={mobileOpen ? t("Navigation") : undefined} tabIndex={-1}>
      <div className="sidebar-glass" aria-hidden="true" />
      <div className="sidebar-content">
      <div className="sidebar-mobile-heading"><span className="brand-wordmark"><BrandMark />{t("Mudaris")}</span><button className="icon-button" onClick={closeNavigation} aria-label={t("Close navigation")}><Icon name="close" /></button></div>
      <button onClick={() => animateChange(toggle)} title={toggleLabel} aria-label={toggleLabel} aria-expanded={!collapsed} className="sidebar-item sidebar-collapse-control hidden md:flex"><span className="sidebar-icon"><Icon name={dir === "rtl" ? (collapsed ? "chevron-left" : "chevron-right") : collapsed ? "chevron-right" : "chevron-left"} size={18} /></span><span className="sidebar-label">{toggleLabel}</span></button>
      <nav aria-label={t("Workspace")}><div className="sidebar-heading">{t("Workspace")}</div>{links.map(item => <Link key={item.href} href={item.href} onClick={onClose} title={t(item.label)} aria-label={t(item.label)} aria-current={pathname === item.href ? "page" : undefined} className={"sidebar-item " + (pathname === item.href ? "is-active" : "")}><span className="sidebar-icon"><Icon name={item.icon} size={20} /></span><span className="sidebar-label">{t(item.label)}</span></Link>)}</nav>
      <div className="sidebar-courses"><div className="sidebar-heading">{t("Your courses")}</div>{visibleCourses.map(renderCourse)}
        {archivedCourses.length > 0 && <><button title={t("Archived")} className="sidebar-item" onClick={() => { if (collapsed) animateChange(() => setCollapsed(false)); setShowArchived(v => !v); }} aria-expanded={showArchived}><span className="sidebar-icon"><Icon name="archive" /></span><span className="sidebar-label">{t("Archived")} ({archivedCourses.length})</span></button>{showArchived && archivedCourses.map(renderCourse)}</>}
      </div>
      <div className="sidebar-bottom"><Link href="/settings" onClick={onClose} aria-label={t("Settings")} title={t("Settings")} className={"sidebar-item " + (pathname === "/settings" ? "is-active" : "")}><span className="sidebar-icon"><Icon name="settings" /></span><span className="sidebar-label">{t("Settings")}</span></Link><button onClick={async () => { await signOut(); router.push("/"); }} className="sidebar-item" aria-label={t("Sign Out")} title={t("Sign Out")}><span className="sidebar-icon"><Icon name="logout" /></span><span className="sidebar-label">{t("Sign Out")}</span></button></div>
      </div>
    </div>
  </aside>;
}
