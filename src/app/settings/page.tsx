"use client";

import { useEffect, useState, FormEvent } from "react";
import { useRouter } from "next/navigation";
import AppShell from "@/components/AppShell";
import Icon from "@/components/Icon";
import { useLang } from "@/lib/i18n";
import "@/app/entry.css";
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
  const { t, lang, setLang } = useLang();

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
          text: `${t("Verification link sent to")} ${newEmail.trim()}. ${t("Your email will update once you confirm it.")}`,
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

  if (loading) return <div className="entry-loading" role="status"><Icon name="loader" size={18} className="animate-spin" />{t("Loading…")}</div>;
  if (!user) return null;

  const initials = (profile?.fullName || user.displayName || user.email || "S").trim().charAt(0).toUpperCase();

  return (
    <AppShell>
      <main className="workspace-main">
        <div className="account-layout">
          <header className="page-header">
            <div><h1 className="page-heading">{t("Settings")}</h1><p className="page-subtitle">{t("Manage your account, profile, and security.")}</p></div>
          </header>
          <div className="account-profile-summary">
            {photoURL ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={photoURL} alt={t("Avatar")} className="account-profile-avatar" />
            ) : <div className="account-profile-avatar">{initials}</div>}
            <div><strong className="text-sm font-semibold">{profile?.fullName || user.displayName || t("Student")}</strong><p className="text-xs text-ink-soft mt-1 break-all" dir="ltr">{user.email}</p></div>
          </div>

          <section className="account-section" aria-labelledby="language-heading">
            <div className="account-section-intro"><h2 id="language-heading">{t("Language")}</h2><p>{t("Choose the language used across Mudaris.")}</p></div>
            <div className="account-section-content">
              <Field label="Interface language">
                <select value={lang} onChange={event => setLang(event.target.value === "ar" ? "ar" : "en")} className="ui-input">
                  <option value="en">English</option>
                  <option value="ar">العربية</option>
                </select>
              </Field>
              <p className="text-xs text-ink-soft mt-3">{t("Changes are saved automatically.")}</p>
            </div>
          </section>

          <section className="account-section" aria-labelledby="profile-heading">
            <div className="account-section-intro"><h2 id="profile-heading">{t("Profile")}</h2><p>{t("This is how you appear across Mudaris.")}</p></div>
            <div className="account-section-content">
              {profileBanner && <Banner banner={profileBanner} />}
              <form onSubmit={handleSaveProfile} className="entry-form">
                <div className="account-form-grid">
                  <Field label="Full name" required><input type="text" autoComplete="name" value={fullName} onChange={(e) => setFullName(e.target.value)} placeholder={t("Your name")} className="ui-input" maxLength={80} /></Field>
                  <Field label="University"><select value={university} onChange={(e) => setUniversity(e.target.value)} className="ui-input"><option value="">{t("Select your university")}</option>{UNIVERSITIES.map((u) => <option key={u} value={u}>{t(u)}</option>)}</select></Field>
                  <Field label="Major / Field of study"><input type="text" value={major} onChange={(e) => setMajor(e.target.value)} placeholder={t("e.g. Computer Science")} className="ui-input" maxLength={80} /></Field>
                  <Field label="Academic year"><select value={academicYear} onChange={(e) => setAcademicYear(e.target.value)} className="ui-input"><option value="">{t("Select your year")}</option>{ACADEMIC_YEARS.map((y) => <option key={y} value={y}>{t(y)}</option>)}</select></Field>
                  <div className="account-field-wide"><Field label="Photo URL" hint="(optional)"><input type="url" dir="ltr" value={photoURL} onChange={(e) => setPhotoURL(e.target.value)} placeholder="https://…" className="ui-input" /></Field></div>
                </div>
                <button type="submit" disabled={savingProfile} className="ui-button primary">{savingProfile && <Icon name="loader" size={16} className="animate-spin" />}{savingProfile ? t("Saving…") : t("Save changes")}</button>
              </form>
            </div>
          </section>

          <section className="account-section" aria-labelledby="email-heading">
            <div className="account-section-intro"><h2 id="email-heading">{t("Email address")}</h2><p>{t("Keep your sign-in address up to date.")}</p></div>
            <div className="account-section-content">
              <p className="account-current-email">{t("Current:")} <strong dir="ltr">{user.email}</strong><span className="account-verified">{user.emailVerified && <Icon name="check-circle" size={12} />}{user.emailVerified ? t("Verified") : t("Unverified")}</span></p>
              {!usesPassword ? <div className="account-provider-note">{t("Your email is managed by your Google account and can't be changed here.")}</div> : (
                <>
                  {emailBanner && <Banner banner={emailBanner} />}
                  <form onSubmit={handleChangeEmail} className="entry-form">
                    <Field label="New email"><input type="email" autoComplete="email" dir="ltr" value={newEmail} onChange={(e) => setNewEmail(e.target.value)} placeholder="new@example.com" className="ui-input" /></Field>
                    <Field label="Current password" hint="(to confirm it's you)"><input type="password" autoComplete="current-password" value={emailPassword} onChange={(e) => setEmailPassword(e.target.value)} placeholder="••••••••" className="ui-input" /></Field>
                    <button type="submit" disabled={savingEmail} className="ui-button primary">{savingEmail && <Icon name="loader" size={16} className="animate-spin" />}{savingEmail ? t("Updating…") : t("Update email")}</button>
                  </form>
                </>
              )}
            </div>
          </section>

          <section className="account-section" aria-labelledby="password-heading">
            <div className="account-section-intro"><h2 id="password-heading">{t("Password")}</h2><p>{usesPassword ? t("Choose a strong password you don't use elsewhere.") : t("You signed in with Google, so there's no password to manage here.")}</p></div>
            <div className="account-section-content">
              {!usesPassword ? <div className="account-provider-note">{t("Sign in with Google to access your account securely.")}</div> : (
                <>
                  {passwordBanner && <Banner banner={passwordBanner} />}
                  <form onSubmit={handleChangePassword} className="entry-form">
                    <Field label="Current password"><input type="password" autoComplete="current-password" value={currentPassword} onChange={(e) => setCurrentPassword(e.target.value)} placeholder="••••••••" className="ui-input" /></Field>
                    <div className="account-form-grid">
                      <Field label="New password"><input type="password" autoComplete="new-password" value={newPassword} onChange={(e) => setNewPassword(e.target.value)} placeholder={t("At least 6 characters")} className="ui-input" /></Field>
                      <Field label="Confirm new password"><input type="password" autoComplete="new-password" value={confirmPassword} onChange={(e) => setConfirmPassword(e.target.value)} placeholder={t("Re-enter new password")} className="ui-input" /></Field>
                    </div>
                    <button type="submit" disabled={savingPassword} className="ui-button primary">{savingPassword && <Icon name="loader" size={16} className="animate-spin" />}{savingPassword ? t("Updating…") : t("Change password")}</button>
                  </form>
                </>
              )}
            </div>
          </section>

          <section className="account-section account-danger" aria-labelledby="account-heading">
            <div className="account-section-intro"><h2 id="account-heading">{t("Account actions")}</h2><p>{t("Sign out of this device or permanently delete your account.")}</p></div>
            <div className="account-section-content">
              <div className="account-actions"><button onClick={handleSignOut} className="ui-button secondary"><Icon name="logout" size={16} />{t("Sign out")}</button>{!showDelete && <button onClick={() => setShowDelete(true)} className="ui-button danger"><Icon name="trash" size={16} />{t("Delete account")}</button>}</div>
              {showDelete && (
                <div className="account-delete-confirm">
                  <p>{t("This will permanently delete your account, profile, courses, uploaded files, generated study materials, chats, and schedule.")} <strong>{t("This action cannot be undone.")}</strong></p>
                  {deleteBanner && <Banner banner={deleteBanner} />}
                  {usesPassword && <div className="mb-5"><Field label="Enter your password to confirm"><input type="password" autoComplete="current-password" value={deletePassword} onChange={(e) => setDeletePassword(e.target.value)} placeholder="••••••••" className="ui-input" /></Field></div>}
                  {!usesPassword && <p>{t("Google will ask you to verify your identity before deletion.")}</p>}
                  <div className="account-actions">
                    <button onClick={handleDeleteAccount} disabled={deleting || (usesPassword && !deletePassword)} className="ui-button danger">{deleting && <Icon name="loader" size={16} className="animate-spin" />}{deleting ? t("Deleting…") : t("Permanently delete")}</button>
                    <button disabled={deleting} onClick={() => { setShowDelete(false); setDeletePassword(""); setDeleteBanner(null); }} className="ui-button secondary">{t("Cancel")}</button>
                  </div>
                </div>
              )}
            </div>
          </section>
        </div>
      </main>
    </AppShell>
  );
}

function Field({ label, hint, required, children }: { label: string; hint?: string; required?: boolean; children: React.ReactNode }) {
  const { t } = useLang();
  return <div className="entry-field"><label><span className="entry-field-label">{t(label)}{required && <span aria-hidden="true"> *</span>}{hint && <span className="entry-field-hint"> {t(hint)}</span>}</span>{children}</label></div>;
}

function Banner({ banner }: { banner: NonNullable<Banner> }) {
  const { t } = useLang();
  const isError = banner.type === "error";
  return <div className={`entry-notice ${isError ? "error" : "success"}`} role={isError ? "alert" : "status"}><Icon name={isError ? "alert" : "check-circle"} size={18} /><span>{t(banner.text)}</span></div>;
}
