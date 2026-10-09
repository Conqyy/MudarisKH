"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import Navbar from "@/components/Navbar";
import { useAuth } from "@/lib/auth-context";

export default function ProcessingPage() {
  const { user, loading } = useAuth();
  const router = useRouter();
  useEffect(() => { if (!loading && !user) router.push("/signin"); }, [user, loading, router]);
  if (loading || !user) return null;
  return <><Navbar /><main className="pt-28 px-6 max-w-xl mx-auto text-center">
    <h1 className="font-serif text-3xl mb-4">Legacy lecture processing is retired</h1>
    <p className="text-ink-soft mb-6">Open a course from your dashboard and upload a recording there to transcribe and analyze it.</p>
    <Link href="/dashboard" className="inline-block bg-ink text-paper px-6 py-3 rounded-full">Back to Dashboard</Link>
  </main></>;
}
