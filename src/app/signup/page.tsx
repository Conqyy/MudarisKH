"use client";

import { useState, FormEvent } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth-context";
import { useLang } from "@/lib/i18n";
import { UNIVERSITIES, ACADEMIC_YEARS } from "@/lib/constants";
import EntryShell, { AuthDivider, EntryError, GoogleButton } from "@/components/entry/EntryShell";
import Icon from "@/components/Icon";

export default function SignUpPage() {
  const router = useRouter();
  const { signUp, signInWithGoogle } = useAuth();
  const { t, dir } = useLang();
  const [step, setStep] = useState<1 | 2>(1);
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [university, setUniversity] = useState("");
  const [major, setMajor] = useState("");
  const [academicYear, setAcademicYear] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const strength = password.length === 0 ? null : password.length < 6 ? "Too short" : password.length < 8 ? "Weak" : password.length < 12 ? "Good" : "Strong";

  const handleStep1Next = (e: FormEvent) => {
    e.preventDefault();
    setError("");
    if (!fullName.trim()) return setError("Full name is required");
    if (!email.includes("@")) return setError("Valid email is required");
    if (password.length < 6) return setError("Password must be at least 6 characters");
    if (password !== confirmPassword) return setError("Passwords do not match");
    setStep(2);
  };

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      await signUp(email, password, fullName, {
        university: university || undefined,
        major: major || undefined,
        academicYear: academicYear || undefined,
      });
      router.push("/dashboard");
    } catch (err: any) {
      console.error(err);
      if (err.code === "auth/email-already-in-use") {
        setError("This email is already registered. Try signing in.");
        setStep(1);
      } else setError(err.message || "Something went wrong. Please try again.");
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
    <EntryShell footer={<>{t("Already have an account?")} <Link href="/signin">{t("Sign in")}</Link></>}>
      <div className="entry-step-indicator" aria-hidden="true"><span className="active" /><span className={step === 2 ? "active" : ""} /></div>
      <p className="entry-step-copy">{t("Step")} {step} {t("of")} 2</p>
      <h1>{step === 1 ? t("Create your account") : t("Tell us about you")}</h1>
      <p className="entry-form-description">{step === 1 ? t("Start with your lectures. Build your own study space.") : t("These details are optional. You can update them in Settings.")}</p>
      <EntryError error={error} />
      {step === 1 ? (
        <>
          <GoogleButton onClick={handleGoogle} disabled={loading} />
          <AuthDivider />
          <form onSubmit={handleStep1Next} className="entry-form">
            <div className="entry-field"><label htmlFor="signup-name">{t("Full Name")}</label><input id="signup-name" type="text" autoComplete="name" value={fullName} onChange={(e) => setFullName(e.target.value)} placeholder={t("Your name")} className="ui-input" required /></div>
            <div className="entry-field"><label htmlFor="signup-email">{t("Email")}</label><input id="signup-email" type="email" autoComplete="email" dir="ltr" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@example.com" className="ui-input" required /></div>
            <div className="entry-field"><label htmlFor="signup-password">{t("Password")}</label><input id="signup-password" type="password" autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder={t("At least 6 characters")} className="ui-input" required aria-describedby={strength ? "signup-strength" : undefined} />{strength && <div id="signup-strength" className="entry-strength">{t(strength)}</div>}</div>
            <div className="entry-field"><label htmlFor="signup-confirm">{t("Confirm Password")}</label><input id="signup-confirm" type="password" autoComplete="new-password" value={confirmPassword} onChange={(e) => setConfirmPassword(e.target.value)} placeholder={t("Re-enter your password")} className="ui-input" required /></div>
            <button type="submit" disabled={loading} className="ui-button primary entry-submit">{t("Continue")}<Icon name={dir === "rtl" ? "arrow-left" : "arrow-right"} size={17} /></button>
          </form>
        </>
      ) : (
        <form onSubmit={handleSubmit} className="entry-form">
          <div className="entry-field"><label htmlFor="signup-university">{t("University")}</label><select id="signup-university" value={university} onChange={(e) => setUniversity(e.target.value)} className="ui-input"><option value="">{t("Select your university")}</option>{UNIVERSITIES.map((u) => <option key={u} value={u}>{t(u)}</option>)}</select></div>
          <div className="entry-field"><label htmlFor="signup-major">{t("Major / Field of Study")}</label><input id="signup-major" type="text" value={major} onChange={(e) => setMajor(e.target.value)} placeholder={t("e.g. Computer Science")} className="ui-input" /></div>
          <div className="entry-field"><label htmlFor="signup-year">{t("Academic Year")}</label><select id="signup-year" value={academicYear} onChange={(e) => setAcademicYear(e.target.value)} className="ui-input"><option value="">{t("Select your year")}</option>{ACADEMIC_YEARS.map((y) => <option key={y} value={y}>{t(y)}</option>)}</select></div>
          <div className="entry-form-actions">
            <button type="button" onClick={() => setStep(1)} disabled={loading} className="ui-button secondary"><Icon name={dir === "rtl" ? "arrow-right" : "arrow-left"} size={17} />{t("Back")}</button>
            <button type="submit" disabled={loading} className="ui-button primary">{loading && <Icon name="loader" size={16} className="animate-spin" />}{loading ? t("Creating...") : t("Create Account")}</button>
          </div>
          <button type="button" onClick={handleSubmit} disabled={loading} className="entry-skip">{t("Skip for now")}</button>
        </form>
      )}
    </EntryShell>
  );
}
