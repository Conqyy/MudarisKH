"use client";
import { useState, type ReactNode } from "react";
import type { Course } from "@/lib/firestore-helpers";
import type { CourseTab } from "@/lib/course-navigation";
import { useLang } from "@/lib/i18n";
import Navbar from "./Navbar";
import Sidebar from "./Sidebar";
import CourseNavigation from "./CourseNavigation";

export default function AppShell({ children, courses = [], course, courseId, activeTab, fullWidth = false, className = "" }: {
  children: ReactNode; courses?: Course[]; course?: Course | null; courseId?: string; activeTab?: CourseTab; fullWidth?: boolean; className?: string;
}) {
  const [navigationOpen, setNavigationOpen] = useState(false);
  const { t } = useLang();
  return <div className={`app-shell ${fullWidth ? "app-shell-wide" : ""} ${className}`}>
    <a className="skip-link" href="#workspace-content">{t("Skip to content")}</a>
    <Navbar workspace course={course} courses={courses} onOpenNavigation={() => setNavigationOpen(true)} />
    <div className="app-shell-body"><Sidebar courses={courses} mobileOpen={navigationOpen} onClose={() => setNavigationOpen(false)} />
      <div className="app-workspace" id="workspace-content" tabIndex={-1}><div className="app-workspace-inner">
        {courseId && <CourseNavigation courseId={courseId} activeTab={activeTab} />}
        {children}
      </div></div>
    </div>
  </div>;
}
