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
import { useBookmarks } from "@/lib/activity";
import "@/app/entry.css";

export default function BookmarkedPage() {
  const { user, loading } = useAuth();
  const { t } = useLang();
  const router = useRouter();
  const bookmarks = useBookmarks();
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
  const entries = bookmarks.map((b) => ({ ...b, ts: b.addedAt }));

  return (
    <AppShell courses={courses}>
      <main className="workspace-main">
        <header className="page-header"><div><h1 className="page-heading">{t("Bookmarked")}</h1><p className="page-subtitle">{t("Keep the material you want to return to within reach.")}</p></div></header>
        <p className="entry-local-note"><Icon name="bookmark" size={14} />{t("Your bookmarks are stored on this device.")}</p>
        {entries.length === 0 ? (
          <section className="entry-empty-state"><div className="entry-empty-symbol"><Icon name="bookmark" size={26} /></div><h2>{t("No bookmarks yet")}</h2><p>{t("Use the bookmark control on a course, lecture document, recording, or exam to add it here.")}</p><Link href="/dashboard" className="ui-button primary">{t("Browse your courses")}</Link></section>
        ) : <ActivityListView items={entries} mode="bookmark" />}
      </main>
    </AppShell>
  );
}
