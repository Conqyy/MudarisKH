"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import AppShell from "@/components/AppShell";
import Icon from "@/components/Icon";
import { useAuth } from "@/lib/auth-context";
import { useLang } from "@/lib/i18n";
import "@/app/entry.css";

export default function ProcessingPage() {
  const { user, loading } = useAuth();
  const { t } = useLang();
  const router = useRouter();
  useEffect(() => { if (!loading && !user) router.push("/signin"); }, [user, loading, router]);
  if (loading || !user) return null;
  return <AppShell><main className="workspace-main"><section className="entry-empty-state entry-retired"><div className="entry-empty-symbol"><Icon name="folder" size={26} /></div><h1 className="text-2xl font-semibold tracking-tight mb-4">{t("Legacy lecture processing is retired")}</h1><p>{t("Open a course from your dashboard and upload a recording there to transcribe and analyze it.")}</p><Link href="/dashboard" className="ui-button primary">{t("Back to Dashboard")}</Link></section></main></AppShell>;
}
