"use client";

import { useState } from "react";
import Icon from "@/components/Icon";
import { useOverlayMotion } from "@/lib/use-overlay-motion";
import SupportingAnalysisReport from "@/components/SupportingAnalysisReport";
import { useSupportingAnalysis } from "@/hooks/useSupportingAnalysis";
import { useLang } from "@/lib/i18n";
import { MaterialKind } from "@/lib/supporting-materials";

export default function SupportingMaterialAction({ kind, materialId, courseId }: { kind: MaterialKind; materialId: string; courseId: string }) {
  const { t } = useLang();
  const [open, setOpen] = useState(false);
  const { ref: dialogRef, close: dismissReport } = useOverlayMotion(() => setOpen(false), { enabled: open });
  const { status, error, retry } = useSupportingAnalysis({ kind, materialId, courseId });
  const active = status && ["queued", "processing", "preparing", "extracting", "aligning"].includes(status.status);
  const retryable = status && (status.legacy || status.stale || ["failed", "incomplete"].includes(status.status));
  const stage = status?.legacy ? "Legacy analysis is unverified." : status?.stale ? "Report is out of date. Reanalyze this material." : status?.status === "failed" ? "Failed" : status?.status === "incomplete" ? "Analysis incomplete" : status?.status === "completed" ? "Analyzed" : status?.stage === "extracting" ? "Extracting source content…" : status?.stage === "aligning" ? "Comparing with lectures…" : status?.stage === "queued" ? "Uploaded; analysis is queued." : active ? "Processing" : "Unknown";
  return <div className="inline-flex flex-wrap gap-2 items-center text-xs" onClick={event => event.stopPropagation()}>
    {status && <span className={"status-badge " + (retryable ? "warning" : active ? "info" : "success")}>{active && <Icon name="loader" size={14} className="animate-spin" />}{t(stage)}{status.progress?.totalUnits != null ? ` · ${status.progress.completedUnits}/${status.progress.totalUnits}` : ""}</span>}
    {error && <span role="alert" className="text-accent">{error}</span>}
    {retryable && <button type="button" className="ui-button ghost" onClick={() => void retry()}><Icon name="refresh" size={15} />{t(status?.legacy ? "Prepare material" : "Retry analysis")}</button>}
    {status?.reportRevision && <button type="button" className="ui-button ghost" onClick={() => setOpen(true)}><Icon name="file" size={15} />{t("Supporting material report")}</button>}
    {open && <div ref={dialogRef} role="dialog" tabIndex={-1} aria-modal="true" aria-label={t("Supporting material report")} className="dialog-overlay z-[110]" onClick={dismissReport}><div className="dialog-panel material-dialog max-w-4xl" onClick={event => event.stopPropagation()}><button type="button" aria-label={t("Close source")} className="icon-button material-dialog-close" onClick={dismissReport}><Icon name="close" /></button><SupportingAnalysisReport kind={kind} materialId={materialId} courseId={courseId} /></div></div>}
  </div>;
}
