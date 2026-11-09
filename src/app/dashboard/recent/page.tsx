"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import AppShell from "@/components/AppShell";
import Icon from "@/components/Icon";
import ActivityListView from "@/components/ActivityListView";
import { useAuth } from "@/lib/auth-context";
import { useLang } from "@/lib/i18n";
import { getUserCourses, Course } from "@/lib/firestore-helpers";
import { clearRecents, useRecents } from "@/lib/activity";
import "@/app/entry.css";

export default function RecentPage() {
  const { user, loading } = useAuth();
  const { t } = useLang();
  const router = useRouter();
  const recents = useRecents();
  const [courses, setCourses] = useState<Course[]>([]);

  useEffect(() => { if (!loading && !user) router.push("/signin"); }, [user, loading, router]);
  useEffect(() => {
    let cancelled = false;
    setCourses([]);
    if (user) getUserCourses(user.uid).then((items) => { if (!cancelled) setCourses(items); }).catch(console.error);
    return () => { cancelled = true; };
  }, [user]);

  if (loading) return <div className="entry-loading" role="status"><Icon name="loader" size={18} className="animate-spin" />{t("Loading…")}</div>;
  if (!user) return null;

  const handleClear = () => {
    if (!confirm(t("Clear your entire Recent list? Bookmarks are kept."))) return;
    clearRecents(user.uid);
  };
  const entries = recents.map((r) => ({ ...r, ts: r.lastAt }));

  return (
    <AppShell courses={courses}>
      <main className="workspace-main">
        <header className="page-header"><div><h1 className="page-heading">{t("Recent")}</h1><p className="page-subtitle">{t("Return to the courses and study materials you've opened.")}</p></div></header>
        <p className="entry-local-note"><Icon name="history" size={14} />{t("Your recent activity is stored on this device.")}</p>
        {entries.length === 0 ? (
          <section className="entry-empty-state"><div className="entry-empty-symbol"><Icon name="history" size={26} /></div><h2>{t("Nothing recent yet")}</h2><p>{t("Open a course, lecture document, recording, or practice exam to find it here next time.")}</p><Link href="/dashboard" className="ui-button primary">{t("Browse your courses")}</Link></section>
        ) : <ActivityListView items={entries} mode="recent" onClear={handleClear} />}
      </main>
    </AppShell>
  );
}
