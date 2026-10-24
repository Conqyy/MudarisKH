"use client";

import { useState, useRef, useEffect } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import type { Course } from "@/lib/firestore-helpers";
import { useAuth } from "@/lib/auth-context";
import { useLang } from "@/lib/i18n";
import { useOverlayMotion } from "@/lib/use-overlay-motion";
import Icon, { BrandMark } from "./Icon";

export default function Navbar({ workspace = false, course, courses = [], onOpenNavigation }: {
  workspace?: boolean; course?: Course | null; courses?: Course[]; onOpenNavigation?: () => void;
}) {
  const router = useRouter();
  const { user, profile, signOut, loading } = useAuth();
  const { t, lang, toggle: toggleLanguage } = useLang();
  const [menuOpen, setMenuOpen] = useState(false);
  const { ref: dropdownRef, close: closeMenu, toggle: toggleMenu } = useOverlayMotion(() => setMenuOpen(false), { enabled: menuOpen, kind: "popover", trapFocus: false });
  const menuRef = useRef<HTMLDivElement>(null);
  const accountButton = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (!menuOpen) return;
    const outside = (e: MouseEvent) => { if (!menuRef.current?.contains(e.target as Node)) closeMenu(); };
    const escape = (e: KeyboardEvent) => { if (e.key === "Escape") { closeMenu(); accountButton.current?.focus(); } };
    document.addEventListener("mousedown", outside); document.addEventListener("keydown", escape);
    return () => { document.removeEventListener("mousedown", outside); document.removeEventListener("keydown", escape); };
  }, [menuOpen, closeMenu]);
  const logout = async () => { setMenuOpen(false); await signOut(); router.push("/"); };
  const initial = (profile?.fullName || user?.email || "S").trim().charAt(0).toUpperCase();
  const maskEmail = (email?: string | null) => { if (!email) return ""; const [local, domain] = email.split("@"); return domain ? local.charAt(0) + "••••" + (local.length > 1 ? local.slice(-1) : "") + "@" + domain : email; };
  const availableCourses = course && !courses.some(c => c.id === course.id) ? [course, ...courses] : courses;
  return <nav className={"app-navbar " + (workspace ? "workspace-nav" : "public-nav")} aria-label={t("Main navigation")}>
    <div className="flex items-center gap-3 min-w-0">
      {workspace && <button className="icon-button mobile-nav-toggle" onClick={onOpenNavigation} aria-label={t("Open navigation")}><Icon name="menu" /></button>}
      <Link href={workspace ? "/dashboard" : "/"} className="brand-wordmark" aria-label="Mudaris"><BrandMark /><span>{t("Mudaris")}</span></Link>
    </div>
    {workspace ? <div className="navbar-context"><span>{t("Workspace")}</span><Icon name="chevron-right" size={14} />
      {course ? <select className="navbar-course-select" aria-label={t("Switch course")} value={course.id} onChange={e => router.push("/course/" + e.target.value)}>
        {availableCourses.map(c => <option value={c.id} key={c.id}>{c.code} · {c.title}</option>)}
      </select> : <span className="font-semibold text-ink">{t("My learning space")}</span>}
    </div> : <div className="navbar-links"><Link href="/">{t("Home")}</Link>{user ? <Link href="/dashboard">{t("Dashboard")}</Link> : <Link href="/#features">{t("Features")}</Link>}</div>}
    <div className="navbar-actions">
      <button onClick={toggleLanguage} className="icon-button language-control" aria-label={lang === "en" ? "Switch to Arabic" : "Switch to English"}>{lang === "en" ? "العربية" : "English"}</button>
      {loading ? <div className="w-12 h-10 bg-bg-alt rounded-full animate-pulse" /> : user ? <div className="relative" ref={menuRef}>
        <button ref={accountButton} onClick={() => toggleMenu(() => setMenuOpen(true))} className="icon-button account-control" aria-label={t("Account")} title={t("Account")} aria-expanded={menuOpen} aria-controls="account-links">
          {profile?.photoURL ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={profile.photoURL} alt="" className="account-avatar" />
          ) : <span className="account-avatar">{initial}</span>}
          <span className="account-name text-xs font-semibold max-w-28 truncate">{profile?.fullName?.split(" ")[0] || t("Student")}</span><Icon name="chevron-down" size={13} />
        </button>
        {menuOpen && <div ref={dropdownRef} id="account-links" className="account-dropdown">
          <div className="px-3 py-3 mb-1 border-b border-line"><p className="font-semibold text-sm truncate">{profile?.fullName || t("Student")}</p><p className="text-xs text-ink-soft mt-1 truncate">{maskEmail(user.email)}</p></div>
          <Link href="/dashboard" onClick={() => setMenuOpen(false)}><Icon name="grid" size={17} />{t("Dashboard")}</Link>
          <Link href="/dashboard/recent" onClick={() => setMenuOpen(false)}><Icon name="history" size={17} />{t("Recent")}</Link>
          <Link href="/dashboard/bookmarked" onClick={() => setMenuOpen(false)}><Icon name="bookmark" size={17} />{t("Bookmarked")}</Link>
          <Link href="/settings" onClick={() => setMenuOpen(false)}><Icon name="settings" size={17} />{t("Settings")}</Link>
          <Link href="/" onClick={() => setMenuOpen(false)}><Icon name="home" size={17} />{t("Home")}</Link>
          <button onClick={logout}><Icon name="logout" size={17} />{t("Sign Out")}</button>
        </div>}
      </div> : <><Link href="/signin" className="hidden sm:inline-flex ui-button ghost">{t("Sign In")}</Link><Link href="/signup" className="ui-button primary">{t("Get Started")}</Link></>}
    </div>
  </nav>;
}
