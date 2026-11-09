"use client";
import Link from "next/link";
import { useEffect, useRef } from "react";
import { useLang } from "@/lib/i18n";
import { courseTabHref, type CourseTab } from "@/lib/course-navigation";
import Icon, { type IconName } from "./Icon";

const tabs: { key: CourseTab; label: string; icon: IconName }[] = [
  { key: "overview", label: "Overview", icon: "grid" }, { key: "materials", label: "Materials", icon: "folder" },
  { key: "exam", label: "Exams", icon: "exam" }, { key: "flashcards", label: "Flashcards", icon: "cards" },
  { key: "summary", label: "Summaries", icon: "summary" }, { key: "tutor", label: "Tutor", icon: "chat" },
];
export default function CourseNavigation({ courseId, activeTab = "overview" }: { courseId: string; activeTab?: CourseTab }) {
  const { t, lang } = useLang();
  const selected = useRef<HTMLAnchorElement>(null);
  useEffect(() => {
    const revealSelected = () => selected.current?.scrollIntoView?.({ block: "nearest", inline: "nearest", behavior: "auto" });
    revealSelected();
    window.addEventListener("resize", revealSelected);
    return () => window.removeEventListener("resize", revealSelected);
  }, [activeTab, courseId, lang]);
  return <nav className="course-navigation" aria-label={t("Course navigation")}>{tabs.map(tab => <Link key={tab.key} ref={activeTab === tab.key ? selected : undefined} href={courseTabHref(courseId, tab.key)} className={`course-tab ${activeTab === tab.key ? "is-active" : ""}`} aria-current={activeTab === tab.key ? "page" : undefined}><Icon name={tab.icon} size={17} /><span>{t(tab.label)}</span></Link>)}</nav>;
}
