"use client";

import { useState, FormEvent } from "react";
import Link from "next/link";
import { useAuth } from "@/lib/auth-context";

export default function ForgotPasswordPage() {
  const { resetPassword } = useAuth();
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
      if (err.code === "auth/user-not-found") {
        setError("No account found with this email.");
      } else {
        setError(err.message || "Failed to send reset email.");
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="min-h-screen flex items-center justify-center p-6">
      <div className="w-full max-w-md">
        <Link href="/" className="flex items-center gap-3 justify-center mb-10">
          <div className="w-10 h-10 bg-ink text-paper rounded-full flex items-center justify-center font-serif italic font-bold text-lg">
            m
          </div>
          <span className="font-serif text-3xl font-semibold tracking-tight">
            Mudaris
          </span>
        </Link>

        <div className="bg-paper border border-line rounded-3xl p-8 md:p-10 shadow-soft">
          {success ? (
            <div className="text-center">
              <div className="text-5xl mb-4">✉️</div>
              <h1 className="font-serif text-3xl font-medium mb-3">
                Check your inbox
              </h1>
              <p className="text-ink-soft text-sm mb-6">
                We sent a password reset link to <strong>{email}</strong>. Click the
                link to reset your password.
              </p>
              <Link
                href="/signin"
                className="inline-block bg-ink text-paper px-6 py-3 rounded-full text-sm font-medium hover:bg-accent transition"
              >
                Back to sign in
              </Link>
            </div>
          ) : (
            <>
              <h1 className="font-serif text-3xl md:text-4xl font-medium tracking-tight mb-2">
                Forgot password?
              </h1>
              <p className="text-ink-soft text-sm mb-8">
                Enter your email and we&apos;ll send you a reset link.
              </p>

              {error && (
                <div className="bg-accent/10 border border-accent text-accent text-sm rounded-xl p-3 mb-6">
                  {error}
                </div>
              )}

              <form onSubmit={handleSubmit} className="space-y-4">
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

                <button
                  type="submit"
                  disabled={loading}
                  className="w-full bg-ink text-paper py-3.5 rounded-full font-medium hover:bg-accent transition disabled:opacity-50 mt-2"
                >
                  {loading ? "Sending..." : "Send reset link"}
                </button>
              </form>
            </>
          )}
        </div>

        <p className="text-center text-sm text-ink-soft mt-6">
          Remember your password?{" "}
          <Link href="/signin" className="text-accent font-medium hover:underline">
            Sign in
          </Link>
        </p>
      </div>
    </main>
  );
}
