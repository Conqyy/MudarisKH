"use client";

import Link from "next/link";
import { foundationGuidance, type CourseFoundation } from "@/lib/course-foundation";
import { useLang } from "@/lib/i18n";

interface CourseFoundationGateProps {
  courseId: string;
  foundation: CourseFoundation | null;
  loading: boolean;
  error: string | null;
  onRetry: () => void | Promise<unknown>;
}

export function CourseFoundationGate({ courseId, foundation, loading, error, onRetry }: CourseFoundationGateProps) {
  const { t } = useLang();
  if (foundation?.ready && !loading && !error) return null;
  return (
    <section className="mb-6 bg-paper border border-line rounded-2xl p-6" aria-label={t("Lecture document foundation")} aria-busy={loading}>
      <div className="flex items-start gap-3">
        <span aria-hidden="true" className="text-lg">🔒</span>
        <div className="min-w-0 flex-1">
          <h2 className="font-serif text-xl font-medium mb-2">{t("Lecture documents first")}</h2>
          <p className="text-sm text-ink-soft" role="status">{t(foundationGuidance(foundation, loading, error))}</p>
          {foundation && <p className="mt-3 text-xs font-mono text-ink-mute">{foundation.completedCount} / {foundation.documentCount} {t("lecture documents analyzed")} · {foundation.pendingCount} {t("pending")} · {foundation.failedCount} {t("need attention")}</p>}
          {error && <p role="alert" className="mt-3 text-sm text-accent">{t(error)}</p>}
          <div className="mt-4 flex flex-wrap items-center gap-4 text-sm">
            <Link href={`/course/${encodeURIComponent(courseId)}?section=documents`} className="font-medium text-sage underline underline-offset-4">{t("Lecture documents")} →</Link>
            <button onClick={() => void onRetry()} disabled={loading} className="text-ink-soft underline underline-offset-4 disabled:opacity-50">{t("Retry foundation check")}</button>
          </div>
        </div>
      </div>
    </section>
  );
}
