"use client";

import { useState, FormEvent } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth-context";
import { useLang } from "@/lib/i18n";
import EntryShell, { AuthDivider, EntryError, GoogleButton } from "@/components/entry/EntryShell";
import Icon from "@/components/Icon";

export default function SignInPage() {
  const router = useRouter();
  const { signIn, signInWithGoogle } = useAuth();
  const { t } = useLang();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      await signIn(email, password);
      router.push("/dashboard");
    } catch (err: any) {
      console.error(err);
      if (err.code === "auth/invalid-credential" || err.code === "auth/wrong-password") setError("Incorrect email or password.");
      else if (err.code === "auth/user-not-found") setError("No account found with this email.");
      else if (err.code === "auth/too-many-requests") setError("Too many attempts. Please try again later.");
      else setError(err.message || "Sign-in failed.");
    } finally { setLoading(false); }
  };

  const handleGoogle = async () => {
    setError("");
    setLoading(true);
    try {
      await signInWithGoogle();
      router.push("/dashboard");
    } catch (err: any) { setError(err.message || "Google sign-in failed"); }
    finally { setLoading(false); }
  };

  return (
    <EntryShell footer={<>{t("Don't have an account?")} <Link href="/signup">{t("Sign up")}</Link></>}>
      <h1>{t("Welcome back")}</h1>
      <p className="entry-form-description">{t("Sign in to your study workspace.")}</p>
      <EntryError error={error} />
      <GoogleButton onClick={handleGoogle} disabled={loading} />
      <AuthDivider />
      <form onSubmit={handleSubmit} className="entry-form">
        <div className="entry-field">
          <label htmlFor="signin-email">{t("Email")}</label>
          <input id="signin-email" type="email" autoComplete="email" dir="ltr" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@example.com" className="ui-input" required />
        </div>
        <div className="entry-field">
          <div className="entry-field-row">
            <label htmlFor="signin-password">{t("Password")}</label>
            <Link href="/forgot-password">{t("Forgot password?")}</Link>
          </div>
          <input id="signin-password" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder={t("Your password")} className="ui-input" required />
        </div>
        <button type="submit" disabled={loading} className="ui-button primary entry-submit">
          {loading && <Icon name="loader" size={17} className="animate-spin" />}
          {loading ? t("Signing in...") : t("Sign In")}
        </button>
      </form>
    </EntryShell>
  );
}
