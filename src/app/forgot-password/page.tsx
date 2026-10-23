"use client";

import { useState, FormEvent } from "react";
import Link from "next/link";
import { useAuth } from "@/lib/auth-context";
import { useLang } from "@/lib/i18n";
import EntryShell, { EntryError } from "@/components/entry/EntryShell";
import Icon from "@/components/Icon";

export default function ForgotPasswordPage() {
  const { resetPassword } = useAuth();
  const { t } = useLang();
  const [email, setEmail] = useState("");
  const [loading, setLoading] = useState(false);
  const [success, setSuccess] = useState(false);
  const [error, setError] = useState("");

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      await resetPassword(email);
      setSuccess(true);
    } catch (err: any) {
      console.error(err);
      if (err.code === "auth/user-not-found") setError("No account found with this email.");
      else setError(err.message || "Failed to send reset email.");
    } finally { setLoading(false); }
  };

  return (
    <EntryShell footer={<>{t("Remember your password?")} <Link href="/signin">{t("Sign in")}</Link></>}>
      {success ? (
        <div role="status">
          <div className="entry-success-icon"><Icon name="check-circle" size={25} /></div>
          <h1>{t("Check your inbox")}</h1>
          <p className="entry-form-description">{t("We sent a password reset link to")}<strong className="entry-success-email" dir="ltr">{email}</strong>{t("Open the link to choose a new password.")}</p>
          <Link href="/signin" className="ui-button primary entry-submit">{t("Back to sign in")}</Link>
        </div>
      ) : (
        <>
          <h1>{t("Forgot password?")}</h1>
          <p className="entry-form-description">{t("Enter your email and we'll send you a reset link.")}</p>
          <EntryError error={error} />
          <form onSubmit={handleSubmit} className="entry-form">
            <div className="entry-field"><label htmlFor="reset-email">{t("Email")}</label><input id="reset-email" type="email" autoComplete="email" dir="ltr" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@example.com" className="ui-input" required /></div>
            <button type="submit" disabled={loading} className="ui-button primary entry-submit">{loading && <Icon name="loader" size={17} className="animate-spin" />}{loading ? t("Sending...") : t("Send reset link")}</button>
          </form>
        </>
      )}
    </EntryShell>
  );
}
