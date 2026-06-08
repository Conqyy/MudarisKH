"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { Course } from "@/lib/firestore-helpers";
import { useAuth } from "@/lib/auth-context";
import { useLang } from "@/lib/i18n";

interface SidebarProps {
  courses: Course[];
}

export default function Sidebar({ courses }: SidebarProps) {
  const pathname = usePathname();
  const router = useRouter();
  const { signOut } = useAuth();
  const { t } = useLang();

  const handleSignOut = async () => {
    await signOut();
    router.push("/");
  };

  const isActive = (path: string) => pathname === path;

  return (
    // Outer element reserves the 260px column in the flex row so the main
    // content never slides under the panel. The inner panel is `fixed` (immune
    // to the `overflow-x: hidden` on <body> that breaks `position: sticky`), so
    // it always spans from the navbar to the bottom of the viewport.
    <aside className="w-[260px] flex-shrink-0 hidden md:block">
      <div className="fixed top-20 bottom-0 start-0 w-[260px] bg-paper border-e border-line p-5 flex flex-col overflow-y-auto">
      {/* WORKSPACE */}
      <div className="mb-8">
        <div className="font-mono text-[11px] uppercase tracking-widest text-ink-mute mb-3 px-3">
          {t("Workspace")}
        </div>

        <Link
          href="/dashboard"
          className={`flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition mb-0.5 ${
            isActive("/dashboard")
              ? "bg-ink text-paper"
              : "text-ink-soft hover:bg-bg-alt hover:text-ink"
          }`}
        >
          <span className="text-base opacity-70">⌂</span>
          {t("Dashboard")}
        </Link>

        <Link
          href="/dashboard/recent"
          className={`flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition mb-0.5 ${
            isActive("/dashboard/recent")
              ? "bg-ink text-paper"
              : "text-ink-soft hover:bg-bg-alt hover:text-ink"
          }`}
        >
          <span className="text-base opacity-70">◷</span>
          {t("Recent")}
        </Link>

        <Link
          href="/dashboard/bookmarked"
          className={`flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition ${
            isActive("/dashboard/bookmarked")
              ? "bg-ink text-paper"
              : "text-ink-soft hover:bg-bg-alt hover:text-ink"
          }`}
        >
          <span className="text-base opacity-70">★</span>
          {t("Bookmarked")}
        </Link>
      </div>

      {/* COURSES */}
      <div className="mb-8">
        <div className="font-mono text-[11px] uppercase tracking-widest text-ink-mute mb-3 px-3">
          {t("Courses")}
        </div>

        {courses.length === 0 ? (
          <div className="text-xs text-ink-mute px-3 py-2">{t("No courses yet")}</div>
        ) : (
          courses.map((course) => (
            <Link
              key={course.id}
              href={`/course/${course.id}`}
              className="flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm text-ink-soft hover:bg-bg-alt hover:text-ink transition mb-0.5"
            >
              <span
                className="w-2 h-2 rounded-full flex-shrink-0"
                style={{ background: course.color }}
              />
              <span className="truncate">{course.code}</span>
            </Link>
          ))
        )}
      </div>

      {/* Spacer pushes Account to the bottom and fills the panel */}
      <div className="flex-1 min-h-6" />

      {/* ACCOUNT */}
      <div className="pt-2 border-t border-line">
        <div className="font-mono text-[11px] uppercase tracking-widest text-ink-mute mb-3 px-3 mt-2">
          {t("Account")}
        </div>

        <Link
          href="/settings"
          className="flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm text-ink-soft hover:bg-bg-alt hover:text-ink transition mb-0.5"
        >
          <span className="text-base opacity-70">◉</span>
          {t("Settings")}
        </Link>

        <button
          onClick={handleSignOut}
          className="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm text-ink-soft hover:bg-bg-alt hover:text-ink transition text-start"
        >
          <span className="text-base opacity-70">↩</span>
          {t("Sign Out")}
        </button>
      </div>
      </div>
    </aside>
  );
}