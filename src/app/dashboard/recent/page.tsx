"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Navbar from "@/components/Navbar";
import Sidebar from "@/components/Sidebar";
import ActivityListView from "@/components/ActivityListView";
import { useAuth } from "@/lib/auth-context";
import { getUserCourses, Course } from "@/lib/firestore-helpers";
import { clearRecents, useRecents } from "@/lib/activity";

export default function RecentPage() {
  const { user, loading } = useAuth();
  const router = useRouter();
  const recents = useRecents();
  const [courses, setCourses] = useState<Course[]>([]);

  useEffect(() => {
    if (!loading && !user) router.push("/signin");
  }, [user, loading, router]);

  useEffect(() => {
    if (!user) return;
    getUserCourses(user.uid).then(setCourses).catch(console.error);
  }, [user]);

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="font-mono text-sm text-ink-mute">Loading…</div>
      </div>
    );
  }
  if (!user) return null;

  const handleClear = () => {
    if (!confirm("Clear your entire Recent list? Bookmarks are kept.")) return;
    clearRecents(user.uid);
  };

  const entries = recents.map((r) => ({ ...r, ts: r.lastAt }));

  return (
    <>
      <Navbar />
      <div className="pt-20 flex">
        <Sidebar courses={courses} />
        <main className="flex-1 px-6 md:px-10 lg:px-12 pb-20 max-w-6xl mx-auto w-full">
          <div className="my-10">
            <h1 className="font-serif text-4xl md:text-5xl font-normal tracking-tight leading-tight mb-2">
              Recent
            </h1>
            <p className="text-ink-soft">
              Everything you&apos;ve opened lately — picks back up where you
              left off.
            </p>
          </div>

          {entries.length === 0 ? (
            <div className="bg-paper border-2 border-dashed border-line rounded-3xl p-16 text-center">
              <div className="text-5xl mb-4 opacity-60">◷</div>
              <h3 className="font-serif text-2xl font-medium mb-2">
                Nothing recent yet
              </h3>
              <p className="text-ink-soft max-w-md mx-auto">
                Open a course, a chapter, a recording, or a practice exam, and
                it&apos;ll show up here for quick access.
              </p>
            </div>
          ) : (
            <ActivityListView
              items={entries}
              mode="recent"
              onClear={handleClear}
            />
          )}
        </main>
      </div>
    </>
  );
}
