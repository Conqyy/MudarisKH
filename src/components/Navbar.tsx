"use client";

import { useState, useRef, useEffect } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth-context";
import { useLang } from "@/lib/i18n";
import { useTheme } from "@/lib/theme";

// 👉 PASTE YOUR GOOGLE FORM LINK HERE (between the quotes) once it's ready.
//    Example: const FEEDBACK_URL = "https://forms.gle/xxxxxxxx";
//    While it's empty, the Feedback link still shows but does nothing.
const FEEDBACK_URL = "";

export default function Navbar() {
  const router = useRouter();
  const { user, profile, signOut, loading } = useAuth();
  const { t } = useLang();
  const { theme, toggle: toggleTheme } = useTheme();

  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  // Close the account menu on outside-click / Escape.
  useEffect(() => {
    if (!menuOpen) return;
    const onClick = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setMenuOpen(false);
      }
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setMenuOpen(false);
    };
    document.addEventListener("mousedown", onClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [menuOpen]);

  const handleSignOut = async () => {
    setMenuOpen(false);
    await signOut();
    router.push("/");
  };

  const initial = (profile?.fullName || user?.email || "S")
    .trim()
    .charAt(0)
    .toUpperCase();

  // Mask the email for privacy (shoulder-surfing) — keep first + last char of
  // the local part and the full domain, e.g. "student.name@example.com" → "s••••e@example.com".
  const maskEmail = (email?: string | null): string => {
    if (!email) return "";
    const at = email.lastIndexOf("@");
    if (at < 1) return email;
    const local = email.slice(0, at);
    const domain = email.slice(at);
    if (local.length <= 2) return `${local[0]}•${domain}`;
    const dots = "•".repeat(Math.min(local.length - 2, 4));
    return `${local[0]}${dots}${local[local.length - 1]}${domain}`;
  };

  return (
    <nav className="fixed top-0 left-0 right-0 z-50 bg-bg/85 backdrop-blur-xl border-b border-line px-6 md:px-12 h-20 flex items-center justify-between">
      {/* Logo */}
      <Link href="/" className="flex items-center gap-3">
        <div className="w-8 h-8 bg-ink text-paper rounded-full flex items-center justify-center font-serif italic font-bold">
          m
        </div>
        <span className="font-serif text-2xl font-semibold tracking-tight">
          {t("Mudaris")}
        </span>
      </Link>

      {/* Nav Links - Desktop only */}
      <ul className="hidden md:flex gap-9 items-center list-none">
        <li>
          <Link
            href="/"
            className="text-ink-soft hover:text-accent text-sm font-medium transition"
          >
            {t("Home")}
          </Link>
        </li>
        {user ? (
          <li>
            <Link
              href="/dashboard"
              className="text-ink-soft hover:text-accent text-sm font-medium transition"
            >
              {t("Dashboard")}
            </Link>
          </li>
        ) : (
          <li>
            <a
              href="#features"
              className="text-ink-soft hover:text-accent text-sm font-medium transition"
            >
              {t("Features")}
            </a>
          </li>
        )}
        <li>
          <a
            href={FEEDBACK_URL || undefined}
            target="_blank"
            rel="noopener noreferrer"
            onClick={(e) => {
              if (!FEEDBACK_URL) e.preventDefault();
            }}
            className={`text-sm font-medium transition inline-flex items-center gap-1.5 ${
              FEEDBACK_URL
                ? "text-ink-soft hover:text-accent cursor-pointer"
                : "text-ink-mute cursor-default"
            }`}
            title={FEEDBACK_URL ? "Share your feedback" : "Feedback form coming soon"}
          >
            {t("Feedback")}
            <span className="text-[10px] opacity-60">↗</span>
          </a>
        </li>
      </ul>

      {/* CTA Section */}
      <div className="flex items-center gap-3">
        {/* Theme toggle (light ⇄ dark) */}
        <button
          onClick={toggleTheme}
          className="w-8 h-8 rounded-full border border-line hover:bg-bg-alt text-sm text-ink-soft transition flex items-center justify-center"
          title={theme === "dark" ? t("Switch to light mode") : t("Switch to dark mode")}
        >
          {theme === "dark" ? "☀" : "☾"}
        </button>
        {loading ? (
          <div className="w-28 h-10 bg-bg-alt rounded-full animate-pulse"></div>
        ) : user ? (
          <div className="relative" ref={menuRef}>
            {/* Account chip */}
            <button
              onClick={() => setMenuOpen((o) => !o)}
              className={`flex items-center gap-2.5 ps-1.5 pe-3 py-1.5 rounded-full border transition ${
                menuOpen
                  ? "border-accent bg-bg-alt"
                  : "border-line hover:bg-bg-alt"
              }`}
              title={t("Account")}
            >
              {profile?.photoURL ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={profile.photoURL}
                  alt=""
                  className="w-7 h-7 rounded-full object-cover"
                />
              ) : (
                <div className="w-7 h-7 rounded-full bg-ink text-paper flex items-center justify-center font-serif italic text-sm">
                  {initial}
                </div>
              )}
              <span className="hidden md:block text-sm text-ink font-medium max-w-[120px] truncate">
                {profile?.fullName?.split(" ")[0] || t("Student")}
              </span>
              <svg
                width="12"
                height="12"
                viewBox="0 0 12 12"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.5"
                className={`text-ink-mute transition-transform ${
                  menuOpen ? "rotate-180" : ""
                }`}
              >
                <path d="M3 4.5L6 7.5L9 4.5" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </button>

            {/* Dropdown */}
            {menuOpen && (
              <div className="absolute end-0 mt-2 w-64 bg-paper border border-line rounded-2xl shadow-lift overflow-hidden animate-fade-in z-50">
                {/* Header */}
                <div className="px-4 py-4 border-b border-line flex items-center gap-3">
                  {profile?.photoURL ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img
                      src={profile.photoURL}
                      alt=""
                      className="w-10 h-10 rounded-full object-cover flex-shrink-0"
                    />
                  ) : (
                    <div className="w-10 h-10 rounded-full bg-ink text-paper flex items-center justify-center font-serif italic flex-shrink-0">
                      {initial}
                    </div>
                  )}
                  <div className="min-w-0">
                    <div className="font-medium text-sm truncate">
                      {profile?.fullName || t("Student")}
                    </div>
                    <div className="text-xs text-ink-mute truncate" title="Email hidden for privacy">
                      {maskEmail(user.email)}
                    </div>
                  </div>
                </div>

                {/* Links */}
                <div className="p-1.5">
                  <Link
                    href="/dashboard"
                    onClick={() => setMenuOpen(false)}
                    className="flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm text-ink-soft hover:bg-bg-alt hover:text-ink transition"
                  >
                    <span className="opacity-70">⌂</span> {t("Dashboard")}
                  </Link>
                  <Link
                    href="/settings"
                    onClick={() => setMenuOpen(false)}
                    className="flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm text-ink-soft hover:bg-bg-alt hover:text-ink transition"
                  >
                    <span className="opacity-70">◉</span> {t("Settings")}
                  </Link>
                </div>

                <div className="p-1.5 border-t border-line">
                  <button
                    onClick={handleSignOut}
                    className="w-full flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm text-ink-soft hover:bg-accent hover:text-paper transition text-start"
                  >
                    <span className="opacity-70">↩</span> {t("Sign Out")}
                  </button>
                </div>
              </div>
            )}
          </div>
        ) : (
          <>
            <Link
              href="/signin"
              className="text-ink-soft hover:text-ink text-sm font-medium transition hidden md:block"
            >
              {t("Sign In")}
            </Link>
            <Link
              href="/signup"
              className="bg-ink text-paper px-5 py-2.5 rounded-full text-xs font-medium hover:bg-accent transition-all hover:-translate-y-0.5"
            >
              {t("Get Started")} →
            </Link>
          </>
        )}
      </div>
    </nav>
  );
}