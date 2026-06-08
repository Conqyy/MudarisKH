"use client";

import { useState, FormEvent } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth-context";
import { UNIVERSITIES, ACADEMIC_YEARS } from "@/lib/constants";

export default function SignUpPage() {
  const router = useRouter();
  const { signUp, signInWithGoogle } = useAuth();

  // Step tracking
  const [step, setStep] = useState<1 | 2>(1);

  // Step 1 fields
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");

  // Step 2 fields
  const [university, setUniversity] = useState("");
  const [major, setMajor] = useState("");
  const [academicYear, setAcademicYear] = useState("");

  // UI state
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  // Password strength
  const passwordStrength = () => {
    if (password.length === 0) return null;
    if (password.length < 6) return { label: "Too short", color: "accent" };
    if (password.length < 8) return { label: "Weak", color: "gold" };
    if (password.length < 12) return { label: "Good", color: "sage" };
    return { label: "Strong", color: "sage" };
  };

  // Step 1 validation
  const handleStep1Next = (e: FormEvent) => {
    e.preventDefault();
    setError("");

    if (!fullName.trim()) return setError("Full name is required");
    if (!email.includes("@")) return setError("Valid email is required");
    if (password.length < 6)
      return setError("Password must be at least 6 characters");
    if (password !== confirmPassword)
      return setError("Passwords do not match");

    setStep(2);
  };

  // Final submission
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
      } else {
        setError(err.message || "Something went wrong. Please try again.");
      }
    } finally {
      setLoading(false);
    }
  };

  const handleGoogle = async () => {
    setError("");
    setLoading(true);
    try {
      await signInWithGoogle();
      router.push("/dashboard");
    } catch (err: any) {
      setError(err.message || "Google sign-in failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="min-h-screen flex items-center justify-center p-6">
      <div className="w-full max-w-md">
        {/* Logo */}
        <Link href="/" className="flex items-center gap-3 justify-center mb-10">
          <div className="w-10 h-10 bg-ink text-paper rounded-full flex items-center justify-center font-serif italic font-bold text-lg">
            m
          </div>
          <span className="font-serif text-3xl font-semibold tracking-tight">
            Mudaris
          </span>
        </Link>

        {/* Card */}
        <div className="bg-paper border border-line rounded-3xl p-8 md:p-10 shadow-soft">
          {/* Progress indicator */}
          <div className="flex items-center gap-2 mb-8">
            <div
              className={`flex-1 h-1 rounded-full ${
                step >= 1 ? "bg-accent" : "bg-bg-alt"
              }`}
            />
            <div
              className={`flex-1 h-1 rounded-full ${
                step >= 2 ? "bg-accent" : "bg-bg-alt"
              }`}
            />
          </div>

          <div className="font-mono text-xs text-ink-mute uppercase tracking-widest mb-2">
            Step {step} of 2
          </div>

          <h1 className="font-serif text-3xl md:text-4xl font-medium tracking-tight mb-2">
            {step === 1 ? "Create your account" : "Tell us about you"}
          </h1>

          <p className="text-ink-soft text-sm mb-8">
            {step === 1
              ? "Start turning lectures into learning."
              : "Help us personalize your experience (optional)."}
          </p>

          {/* Error message */}
          {error && (
            <div className="bg-accent/10 border border-accent text-accent text-sm rounded-xl p-3 mb-6">
              {error}
            </div>
          )}

          {/* ============ STEP 1 ============ */}
          {step === 1 && (
            <>
              {/* Google button */}
              <button
                onClick={handleGoogle}
                disabled={loading}
                className="w-full flex items-center justify-center gap-3 border border-line bg-bg hover:bg-bg-alt py-3 rounded-xl text-sm font-medium transition disabled:opacity-50 mb-6"
              >
                <svg className="w-5 h-5" viewBox="0 0 24 24">
                  <path
                    fill="#4285F4"
                    d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"
                  />
                  <path
                    fill="#34A853"
                    d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"
                  />
                  <path
                    fill="#FBBC05"
                    d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"
                  />
                  <path
                    fill="#EA4335"
                    d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"
                  />
                </svg>
                Continue with Google
              </button>

              <div className="flex items-center gap-3 mb-6">
                <div className="flex-1 h-px bg-line"></div>
                <span className="text-xs text-ink-mute font-mono uppercase">
                  or
                </span>
                <div className="flex-1 h-px bg-line"></div>
              </div>

              <form onSubmit={handleStep1Next} className="space-y-4">
                <div>
                  <label className="block text-sm font-medium text-ink-soft mb-2">
                    Full Name
                  </label>
                  <input
                    type="text"
                    value={fullName}
                    onChange={(e) => setFullName(e.target.value)}
                    placeholder="Sultan Al-Zahrani"
                    className="w-full px-4 py-3 border border-line rounded-xl bg-bg focus:outline-none focus:border-accent transition"
                    required
                  />
                </div>

                <div>
                  <label className="block text-sm font-medium text-ink-soft mb-2">
                    Email
                  </label>
                  <input
                    type="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder="you@example.com"
                    className="w-full px-4 py-3 border border-line rounded-xl bg-bg focus:outline-none focus:border-accent transition"
                    required
                  />
                </div>

                <div>
                  <label className="block text-sm font-medium text-ink-soft mb-2">
                    Password
                  </label>
                  <input
                    type="password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    placeholder="At least 6 characters"
                    className="w-full px-4 py-3 border border-line rounded-xl bg-bg focus:outline-none focus:border-accent transition"
                    required
                  />
                  {passwordStrength() && (
                    <div
                      className={`text-xs mt-1.5 font-mono text-${
                        passwordStrength()!.color
                      }`}
                    >
                      {passwordStrength()!.label}
                    </div>
                  )}
                </div>

                <div>
                  <label className="block text-sm font-medium text-ink-soft mb-2">
                    Confirm Password
                  </label>
                  <input
                    type="password"
                    value={confirmPassword}
                    onChange={(e) => setConfirmPassword(e.target.value)}
                    placeholder="Re-enter your password"
                    className="w-full px-4 py-3 border border-line rounded-xl bg-bg focus:outline-none focus:border-accent transition"
                    required
                  />
                </div>

                <button
                  type="submit"
                  className="w-full bg-ink text-paper py-3.5 rounded-full font-medium hover:bg-accent transition mt-2"
                >
                  Continue →
                </button>
              </form>
            </>
          )}

          {/* ============ STEP 2 ============ */}
          {step === 2 && (
            <form onSubmit={handleSubmit} className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-ink-soft mb-2">
                  University
                </label>
                <select
                  value={university}
                  onChange={(e) => setUniversity(e.target.value)}
                  className="w-full px-4 py-3 border border-line rounded-xl bg-bg focus:outline-none focus:border-accent transition"
                >
                  <option value="">Select your university</option>
                  {UNIVERSITIES.map((u) => (
                    <option key={u} value={u}>
                      {u}
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label className="block text-sm font-medium text-ink-soft mb-2">
                  Major / Field of Study
                </label>
                <input
                  type="text"
                  value={major}
                  onChange={(e) => setMajor(e.target.value)}
                  placeholder="e.g. Computer Science"
                  className="w-full px-4 py-3 border border-line rounded-xl bg-bg focus:outline-none focus:border-accent transition"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-ink-soft mb-2">
                  Academic Year
                </label>
                <select
                  value={academicYear}
                  onChange={(e) => setAcademicYear(e.target.value)}
                  className="w-full px-4 py-3 border border-line rounded-xl bg-bg focus:outline-none focus:border-accent transition"
                >
                  <option value="">Select your year</option>
                  {ACADEMIC_YEARS.map((y) => (
                    <option key={y} value={y}>
                      {y}
                    </option>
                  ))}
                </select>
              </div>

              <div className="flex gap-3 pt-4">
                <button
                  type="button"
                  onClick={() => setStep(1)}
                  className="flex-1 border border-line py-3.5 rounded-full text-sm font-medium hover:bg-bg-alt transition"
                >
                  ← Back
                </button>
                <button
                  type="submit"
                  disabled={loading}
                  className="flex-1 bg-ink text-paper py-3.5 rounded-full text-sm font-medium hover:bg-accent transition disabled:opacity-50"
                >
                  {loading ? "Creating..." : "Create Account"}
                </button>
              </div>

              <button
                type="button"
                onClick={handleSubmit}
                disabled={loading}
                className="w-full text-xs text-ink-mute hover:text-ink-soft transition pt-2"
              >
                Skip for now
              </button>
            </form>
          )}
        </div>

        {/* Already have account */}
        <p className="text-center text-sm text-ink-soft mt-6">
          Already have an account?{" "}
          <Link href="/signin" className="text-accent font-medium hover:underline">
            Sign in
          </Link>
        </p>
      </div>
    </main>
  );
}
