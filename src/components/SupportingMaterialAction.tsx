"use client";

import { useState } from "react";
import SupportingAnalysisReport from "@/components/SupportingAnalysisReport";
import { useSupportingAnalysis } from "@/hooks/useSupportingAnalysis";
import { useLang } from "@/lib/i18n";
import { MaterialKind } from "@/lib/supporting-materials";

export default function SupportingMaterialAction({ kind, materialId, courseId }: { kind: MaterialKind; materialId: string; courseId: string }) {
  const { t } = useLang();
  const [open, setOpen] = useState(false);
  const { status, error, retry } = useSupportingAnalysis({ kind, materialId, courseId });
  const active = status && ["queued", "processing", "preparing", "extracting", "aligning"].includes(status.status);
  const retryable = status && (status.legacy || status.stale || ["failed", "incomplete"].includes(status.status));
  const stage = status?.stage === "extracting" ? "Extracting source content…" : status?.stage === "aligning" ? "Comparing with lectures…" : status?.stage === "queued" ? "Uploaded; analysis is queued." : status?.status === "completed" ? "Analyzed" : "Processing";
  return <span className="inline-flex flex-wrap gap-2 items-center text-xs" onClick={event => event.stopPropagation()}>
    {status && <span className={retryable ? "text-accent" : active ? "text-gold" : "text-sage"}>{t(stage)}{status.progress?.totalUnits !== null ? ` · ${status.progress.completedUnits}/${status.progress.totalUnits}` : ""}</span>}
    {status?.stale && <span className="text-gold">{t("Report is out of date. Reanalyze this material.")}</span>}
    {status?.status === "incomplete" && <span className="text-gold">{t("Analysis incomplete")}</span>}
    {error && <span role="alert" className="text-accent">{error}</span>}
    {retryable && <button type="button" className="underline" onClick={() => void retry()}>{t(status?.legacy ? "Prepare material" : "Retry analysis")}</button>}
    {status?.reportRevision && <button type="button" className="underline" onClick={() => setOpen(true)}>{t("Supporting material report")}</button>}
    {open && <div role="dialog" aria-modal="true" aria-label={t("Supporting material report")} className="fixed inset-0 z-[110] bg-ink/40 flex justify-center items-center p-4" onClick={() => setOpen(false)}><div className="bg-paper rounded-2xl p-6 max-w-4xl max-h-[90vh] overflow-y-auto w-full" onClick={event => event.stopPropagation()}><button type="button" className="float-end underline" onClick={() => setOpen(false)}>{t("Close source")}</button><SupportingAnalysisReport kind={kind} materialId={materialId} courseId={courseId} /></div></div>}
  </span>;
}
