"use client";

import { useEffect, useState, FormEvent } from "react";
import { useRouter } from "next/navigation";
import Navbar from "@/components/Navbar";
import { useAuth } from "@/lib/auth-context";
import { UNIVERSITIES, ACADEMIC_YEARS } from "@/lib/constants";

type Banner = { type: "success" | "error"; text: string } | null;

export default function SettingsPage() {
  const {
    user,
    profile,
    loading,
    hasPasswordProvider,
    updateUserProfile,
    changeEmail,
    changePassword,
    deleteAccount,
    signOut,
  } = useAuth();
  const router = useRouter();

  const usesPassword = hasPasswordProvider();

  // ---- Profile form ----
  const [fullName, setFullName] = useState("");
  const [university, setUniversity] = useState("");
  const [major, setMajor] = useState("");
  const [academicYear, setAcademicYear] = useState("");
  const [photoURL, setPhotoURL] = useState("");
  const [savingProfile, setSavingProfile] = useState(false);
  const [profileBanner, setProfileBanner] = useState<Banner>(null);

  // ---- Email form ----
  const [newEmail, setNewEmail] = useState("");
  const [emailPassword, setEmailPassword] = useState("");
  const [savingEmail, setSavingEmail] = useState(false);
  const [emailBanner, setEmailBanner] = useState<Banner>(null);

  // ---- Password form ----
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [savingPassword, setSavingPassword] = useState(false);
  const [passwordBanner, setPasswordBanner] = useState<Banner>(null);

  // ---- Delete account ----
  const [showDelete, setShowDelete] = useState(false);
  const [deletePassword, setDeletePassword] = useState("");
  const [deleting, setDeleting] = useState(false);
  const [deleteBanner, setDeleteBanner] = useState<Banner>(null);

  // Protect route
  useEffect(() => {
    if (!loading && !user) router.push("/signin");
  }, [user, loading, router]);

  // Hydrate the profile form once data is available
  useEffect(() => {
    if (profile) {
      setFullName(profile.fullName || "");
      setUniversity(profile.university || "");
      setMajor(profile.major || "");
      setAcademicYear(profile.academicYear || "");
      setPhotoURL(profile.photoURL || "");
    } else if (user) {
      setFullName(user.displayName || "");
      setPhotoURL(user.photoURL || "");
    }
  }, [profile, user]);

  const friendlyError = (err: any): string => {
    const code = err?.code as string | undefined;
    switch (code) {
      case "auth/wrong-password":
      case "auth/invalid-credential":
        return "Incorrect current password. Please try again.";
      case "auth/too-many-requests":
        return "Too many attempts. Please wait a moment and try again.";
      case "auth/requires-recent-login":
        return "Please sign in again, then retry this change.";
      case "auth/email-already-in-use":
        return "That email is already in use by another account.";
      case "auth/invalid-email":
        return "That email address is not valid.";
      case "auth/weak-password":
        return "Password is too weak (use at least 6 characters).";
      case "auth/popup-closed-by-user":
      case "auth/cancelled-popup-request":
        return "Verification was cancelled. Please try again.";
      default:
        return err?.message || "Something went wrong. Please try again.";
    }
  };

  // ---- Handlers ----
  const handleSaveProfile = async (e: FormEvent) => {
    e.preventDefault();
    setProfileBanner(null);
    if (!fullName.trim()) {
      setProfileBanner({ type: "error", text: "Full name is required." });
      return;
    }
    setSavingProfile(true);
    try {
      await updateUserProfile({
        fullName: fullName.trim(),
        university: university || "",
        major: major.trim(),
        academicYear: academicYear || "",
        photoURL: photoURL.trim(),
      });
      setProfileBanner({ type: "success", text: "Profile updated successfully." });
    } catch (err: any) {
      setProfileBanner({ type: "error", text: friendlyError(err) });
    } finally {
      setSavingProfile(false);
    }
  };

  const handleChangeEmail = async (e: FormEvent) => {
    e.preventDefault();
    setEmailBanner(null);
    if (!newEmail.includes("@")) {
      setEmailBanner({ type: "error", text: "Please enter a valid email." });
      return;
    }
    if (newEmail.trim().toLowerCase() === (user?.email || "").toLowerCase()) {
      setEmailBanner({ type: "error", text: "That's already your email." });
      return;
    }
    setSavingEmail(true);
    try {
      const result = await changeEmail(newEmail.trim(), emailPassword);
      if (result === "verification_sent") {
        setEmailBanner({
          type: "success",
          text: `Verification link sent to ${newEmail.trim()}. Your email will update once you confirm it.`,
        });
      } else {
        setEmailBanner({ type: "success", text: "Email updated successfully." });
      }
      setEmailPassword("");
      setNewEmail("");
    } catch (err: any) {
      setEmailBanner({ type: "error", text: friendlyError(err) });
    } finally {
      setSavingEmail(false);
    }
  };

  const handleChangePassword = async (e: FormEvent) => {
    e.preventDefault();
    setPasswordBanner(null);
    if (newPassword.length < 6) {
      setPasswordBanner({
        type: "error",
        text: "New password must be at least 6 characters.",
      });
      return;
    }
    if (newPassword !== confirmPassword) {
      setPasswordBanner({ type: "error", text: "Passwords do not match." });
      return;
    }
    setSavingPassword(true);
    try {
      await changePassword(currentPassword, newPassword);
      setPasswordBanner({
        type: "success",
        text: "Password changed successfully.",
      });
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
    } catch (err: any) {
      setPasswordBanner({ type: "error", text: friendlyError(err) });
    } finally {
      setSavingPassword(false);
    }
  };

  const handleDeleteAccount = async () => {
    setDeleteBanner(null);
    setDeleting(true);
    try {
      await deleteAccount(usesPassword ? deletePassword : undefined);
      router.push("/");
    } catch (err: any) {
      setDeleteBanner({ type: "error", text: friendlyError(err) });
      setDeleting(false);
    }
  };

  const handleSignOut = async () => {
    await signOut();
    router.push("/");
  };

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="font-mono text-sm text-ink-mute">Loading…</div>
      </div>
    );
  }
  if (!user) return null;

  const initials =
    (profile?.fullName || user.displayName || user.email || "S")
      .trim()
      .charAt(0)
      .toUpperCase();

  return (
    <>
      <Navbar />

      <main className="pt-20 px-6 md:px-12 pb-24">
        <div className="max-w-2xl mx-auto">
          {/* Header */}
          <div className="my-10">
            <button
              onClick={() => router.push("/dashboard")}
              className="text-xs font-mono text-ink-soft hover:text-accent transition mb-6"
            >
              ← Dashboard
            </button>
            <h1 className="font-serif text-4xl md:text-5xl font-normal tracking-tight leading-tight mb-2">
              Settings
            </h1>
            <p className="text-ink-soft">
              Manage your account, profile, and security.
            </p>
          </div>

          {/* ============ PROFILE ============ */}
          <section className="bg-paper border border-line rounded-3xl p-7 md:p-8 mb-8">
            <div className="flex items-center gap-4 mb-6">
              {photoURL ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={photoURL}
                  alt="Avatar"
                  className="w-14 h-14 rounded-full object-cover border border-line"
                />
              ) : (
                <div className="w-14 h-14 rounded-full bg-ink text-paper flex items-center justify-center font-serif italic text-2xl">
                  {initials}
                </div>
              )}
              <div>
                <h2 className="font-serif text-2xl font-medium tracking-tight">
                  Profile
                </h2>
                <p className="text-sm text-ink-soft">
                  This is how you appear across Mudaris.
                </p>
              </div>
            </div>

            {profileBanner && (
              <Banner banner={profileBanner} />
            )}

            <form onSubmit={handleSaveProfile} className="space-y-5">
              <Field label="Full name" required>
                <input
                  type="text"
                  value={fullName}
                  onChange={(e) => setFullName(e.target.value)}
                  placeholder="Your name"
                  className={inputClass}
                  maxLength={80}
                />
              </Field>

              <Field label="University">
                <select
                  value={university}
                  onChange={(e) => setUniversity(e.target.value)}
                  className={inputClass}
                >
                  <option value="">Select your university</option>
                  {UNIVERSITIES.map((u) => (
                    <option key={u} value={u}>
                      {u}
                    </option>
                  ))}
                </select>
              </Field>

              <Field label="Major / Field of study">
                <input
                  type="text"
                  value={major}
                  onChange={(e) => setMajor(e.target.value)}
                  placeholder="e.g. Computer Science"
                  className={inputClass}
                  maxLength={80}
                />
              </Field>

              <Field label="Academic year">
                <select
                  value={academicYear}
                  onChange={(e) => setAcademicYear(e.target.value)}
                  className={inputClass}
                >
                  <option value="">Select your year</option>
                  {ACADEMIC_YEARS.map((y) => (
                    <option key={y} value={y}>
                      {y}
                    </option>
                  ))}
                </select>
              </Field>

              <Field label="Photo URL" hint="(optional)">
                <input
                  type="url"
                  value={photoURL}
                  onChange={(e) => setPhotoURL(e.target.value)}
                  placeholder="https://…"
                  className={inputClass}
                />
              </Field>

              <button
                type="submit"
                disabled={savingProfile}
                className="bg-ink text-paper px-6 py-3 rounded-full text-sm font-medium hover:bg-accent transition disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {savingProfile ? "Saving…" : "Save changes"}
              </button>
            </form>
          </section>

          {/* ============ EMAIL ============ */}
          <section className="bg-paper border border-line rounded-3xl p-7 md:p-8 mb-8">
            <h2 className="font-serif text-2xl font-medium tracking-tight mb-1">
              Email address
            </h2>
            <p className="text-sm text-ink-soft mb-5">
              Current:{" "}
              <span className="font-mono text-ink">{user.email}</span>
              {user.emailVerified ? (
                <span className="ml-2 text-xs font-mono text-sage">
                  ● verified
                </span>
              ) : (
                <span className="ml-2 text-xs font-mono text-gold">
                  ● unverified
                </span>
              )}
            </p>

            {!usesPassword ? (
              <div className="bg-bg-alt border border-line rounded-2xl p-4 text-sm text-ink-soft">
                Your email is managed by your Google account and can&apos;t be
                changed here.
              </div>
            ) : (
              <>
                {emailBanner && <Banner banner={emailBanner} />}
                <form onSubmit={handleChangeEmail} className="space-y-5">
                  <Field label="New email">
                    <input
                      type="email"
                      value={newEmail}
                      onChange={(e) => setNewEmail(e.target.value)}
                      placeholder="new@example.com"
                      className={inputClass}
                    />
                  </Field>
                  <Field label="Current password" hint="(to confirm it's you)">
                    <input
                      type="password"
                      value={emailPassword}
                      onChange={(e) => setEmailPassword(e.target.value)}
                      placeholder="••••••••"
                      className={inputClass}
                    />
                  </Field>
                  <button
                    type="submit"
                    disabled={savingEmail}
                    className="bg-ink text-paper px-6 py-3 rounded-full text-sm font-medium hover:bg-accent transition disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    {savingEmail ? "Updating…" : "Update email"}
                  </button>
                </form>
              </>
            )}
          </section>

          {/* ============ PASSWORD ============ */}
          <section className="bg-paper border border-line rounded-3xl p-7 md:p-8 mb-8">
            <h2 className="font-serif text-2xl font-medium tracking-tight mb-1">
              Password
            </h2>
            {!usesPassword ? (
              <>
                <p className="text-sm text-ink-soft mb-4">
                  You signed in with Google, so there&apos;s no password to
                  manage here.
                </p>
                <div className="bg-bg-alt border border-line rounded-2xl p-4 text-sm text-ink-soft">
                  Sign in with Google to access your account securely.
                </div>
              </>
            ) : (
              <>
                <p className="text-sm text-ink-soft mb-5">
                  Choose a strong password you don&apos;t use elsewhere.
                </p>
                {passwordBanner && <Banner banner={passwordBanner} />}
                <form onSubmit={handleChangePassword} className="space-y-5">
                  <Field label="Current password">
                    <input
                      type="password"
                      value={currentPassword}
                      onChange={(e) => setCurrentPassword(e.target.value)}
                      placeholder="••••••••"
                      className={inputClass}
                    />
                  </Field>
                  <Field label="New password">
                    <input
                      type="password"
                      value={newPassword}
                      onChange={(e) => setNewPassword(e.target.value)}
                      placeholder="At least 6 characters"
                      className={inputClass}
                    />
                  </Field>
                  <Field label="Confirm new password">
                    <input
                      type="password"
                      value={confirmPassword}
                      onChange={(e) => setConfirmPassword(e.target.value)}
                      placeholder="Re-enter new password"
                      className={inputClass}
                    />
                  </Field>
                  <button
                    type="submit"
                    disabled={savingPassword}
                    className="bg-ink text-paper px-6 py-3 rounded-full text-sm font-medium hover:bg-accent transition disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    {savingPassword ? "Updating…" : "Change password"}
                  </button>
                </form>
              </>
            )}
          </section>

          {/* ============ DANGER ZONE ============ */}
          <section className="bg-paper border border-accent/40 rounded-3xl p-7 md:p-8">
            <h2 className="font-serif text-2xl font-medium tracking-tight mb-1 text-accent">
              Danger zone
            </h2>
            <p className="text-sm text-ink-soft mb-6">
              Sign out of this device or permanently delete your account.
            </p>

            <div className="flex flex-col sm:flex-row gap-3 mb-2">
              <button
                onClick={handleSignOut}
                className="border border-ink text-ink px-6 py-3 rounded-full text-sm font-medium hover:bg-ink hover:text-paper transition"
              >
                Sign out
              </button>
              {!showDelete && (
                <button
                  onClick={() => setShowDelete(true)}
                  className="border border-accent text-accent px-6 py-3 rounded-full text-sm font-medium hover:bg-accent hover:text-paper transition"
                >
                  Delete account
                </button>
              )}
            </div>

            {showDelete && (
              <div className="mt-5 border-t border-line pt-5">
                <p className="text-sm text-ink mb-4">
                  This will permanently delete your account and profile. This
                  action <strong>cannot be undone</strong>.
                </p>
                {deleteBanner && <Banner banner={deleteBanner} />}
                {usesPassword && (
                  <div className="mb-4">
                    <Field label="Enter your password to confirm">
                      <input
                        type="password"
                        value={deletePassword}
                        onChange={(e) => setDeletePassword(e.target.value)}
                        placeholder="••••••••"
                        className={inputClass}
                      />
                    </Field>
                  </div>
                )}
                <div className="flex gap-3">
                  <button
                    onClick={handleDeleteAccount}
                    disabled={deleting || (usesPassword && !deletePassword)}
                    className="bg-accent text-paper px-6 py-3 rounded-full text-sm font-medium hover:bg-ink transition disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    {deleting ? "Deleting…" : "Permanently delete"}
                  </button>
                  <button
                    onClick={() => {
                      setShowDelete(false);
                      setDeletePassword("");
                      setDeleteBanner(null);
                    }}
                    className="border border-line text-ink-soft px-6 py-3 rounded-full text-sm font-medium hover:bg-bg-alt transition"
                  >
                    Cancel
                  </button>
                </div>
              </div>
            )}
          </section>
        </div>
      </main>
    </>
  );
}

// ============ SMALL HELPERS ============

const inputClass =
  "w-full px-4 py-3 border border-line rounded-xl bg-bg focus:outline-none focus:border-accent transition";

function Field({
  label,
  hint,
  required,
  children,
}: {
  label: string;
  hint?: string;
  required?: boolean;
  children: React.ReactNode;
}) {
  return (
    <div>
      <label className="block text-sm font-medium text-ink-soft mb-2">
        {label}
        {required && <span className="text-accent"> *</span>}
        {hint && <span className="text-ink-mute font-normal"> {hint}</span>}
      </label>
      {children}
    </div>
  );
}

function Banner({ banner }: { banner: NonNullable<Banner> }) {
  const isError = banner.type === "error";
  return (
    <div
      className={`text-sm rounded-xl p-3 mb-5 border ${
        isError
          ? "bg-accent/10 border-accent text-accent"
          : "bg-sage/10 border-sage text-sage"
      }`}
    >
      {banner.text}
    </div>
  );
}
