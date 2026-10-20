"use client";

import SupportingCitation from "@/components/SupportingCitation";
import SourceCitation from "@/components/SourceCitation";
import { useSupportingAnalysis } from "@/hooks/useSupportingAnalysis";
import { useLang } from "@/lib/i18n";
import { MaterialKind, SupportingAlignment, SupportingItem } from "@/lib/supporting-materials";

const statusLabels: Record<string, string> = { covered: "Covered", partly_covered: "Partly covered", not_covered: "Not covered", needs_review: "Needs review", nonacademic: "Not academic content" };
const relationLabels: Record<string, string> = { lecture_supported: "Supported by lecture", related_supplementary: "Related supplement", outside_selected_scope: "Outside selected chapters", not_found: "Not found in selected lectures", unverified: "Needs review", conflicting: "Conflicting evidence" };
function coverageCount(value: Record<string, unknown> | undefined, allKey: string, unresolvedKey: string): string | null {
  const all = value?.[allKey], unresolved = value?.[unresolvedKey];
  if (!Array.isArray(all) || !Array.isArray(unresolved)) return null;
  return `${all.length - unresolved.length} / ${all.length}`;
}

export default function SupportingAnalysisReport({ kind, materialId, courseId }: { kind: MaterialKind; materialId: string; courseId: string }) {
  const { t } = useLang();
  const { status, report, loading, error, retry, loadMore } = useSupportingAnalysis({ kind, materialId, courseId });
  const alignmentById = new Map(report?.alignments.map(row => [row.itemId, row]));
  const paperById = new Map(report?.papers.map(row => [row.paperId, row]));
  const groups = new Map<string, SupportingItem[]>();
  for (const item of report?.items || []) {
    const key = item.paperId || "";
    groups.set(key, [...(groups.get(key) || []), item]);
  }
  const statusWarning = status?.stale ? "Report is out of date. Reanalyze this material." : status?.legacy ? "This material needs preparation before use." : status?.status === "incomplete" ? "Analysis incomplete" : null;
  const extraction = coverageCount(report?.extractionCoverage, "unitIds", "unresolvedUnitIds");
  const alignment = coverageCount(report?.alignmentCoverage, "itemIds", "unresolvedItemIds");
  const canRetry = status && (status.legacy || status.stale || ["failed", "incomplete"].includes(status.status));
  return <section className="space-y-4" aria-label={t("Supporting material report")}>
    <h3 className="font-serif text-lg font-medium">{t("Supporting material report")}</h3>
    {loading && <p>{t("Loading source…")}</p>}
    {status && <p className="text-sm text-ink-soft">{status.progress?.completedUnits ?? 0}{status.progress?.totalUnits !== null ? ` / ${status.progress.totalUnits}` : ""} {t("source units")}{status.stage ? ` · ${t(status.stage === "extracting" ? "Extracting source content…" : status.stage === "aligning" ? "Comparing with lectures…" : status.stage === "queued" ? "Uploaded; analysis is queued." : "Processing")}` : ""}</p>}
    {statusWarning && <p role="status" className="text-sm text-gold">{t(statusWarning)}</p>}
    {status?.errorMessage && <p role="alert" className="text-sm text-accent" dir="auto">{status.errorMessage}</p>}
    {error && <p role="alert" className="text-sm text-accent">{error}</p>}
    {canRetry && <button type="button" className="underline text-sm" onClick={() => void retry()}>{t(status?.legacy ? "Prepare material" : "Retry analysis")}</button>}
    {report && <>
      <div className="text-sm text-ink-soft flex flex-wrap gap-4"><span>{t("Extraction coverage")}: {extraction ?? t("Unknown")}</span><span>{t("Alignment coverage")}: {alignment ?? t("Unknown")}</span></div>
      {(report.extractionCoverage?.complete === false || report.alignmentCoverage?.complete === false) && <p className="text-sm text-gold">{t("Some source content could not be checked.")}</p>}
      {[...groups].map(([paperId, items]) => {
        const paper = paperById.get(paperId);
        const title = typeof paper?.title === "string" ? paper.title : typeof paper?.printedLabel === "string" ? paper.printedLabel : paperId ? `${t("Paper")} ${paperId}` : t("Items");
        return <section key={paperId || "unassigned"} className="border border-line rounded-xl p-4 space-y-4">
          <h4 className="font-medium" dir="auto">{title}</h4>
          {items.map(item => <ReportItem key={item.id} item={item} alignment={alignmentById.get(item.id)} courseId={courseId} t={t} />)}
        </section>;
      })}
      {report.nextOffset !== null && <button type="button" className="underline text-sm" onClick={() => void loadMore()}>{t("Load more results")}</button>}
    </>}
  </section>;
}

function ReportItem({ item, alignment, courseId, t }: { item: SupportingItem; alignment?: SupportingAlignment; courseId: string; t: (value: string) => string }) {
  const byRequirement = new Map(alignment?.requirements.map(row => [row.requirementId, row]));
  return <article className="bg-bg border border-line rounded-xl p-3 space-y-2">
    <div className="flex flex-wrap gap-2 items-center"><strong dir="auto">{item.printedLabel || item.itemType}</strong><span className="text-xs text-ink-soft">{t(statusLabels[alignment?.status || "needs_review"] || "Needs review")}</span>{item.printedMarks !== null && typeof item.printedMarks === "number" && <span>{item.printedMarks} {t("marks")}</span>}</div>
    <p dir="auto" className="text-sm whitespace-pre-wrap">{item.text}</p>
    {item.requirements?.length > 0 && <div><h5 className="text-sm font-medium">{t("Required concepts")}</h5>{item.requirements.map(requirement => {
      const finding = byRequirement.get(requirement.id);
      const proofs = finding?.supportingSourceProofs?.map(proof => proof.ref).filter(Boolean) || [];
      return <div key={requirement.id} className="mt-2 text-sm border-s-2 border-line ps-3"><p dir="auto">{requirement.text}</p><p>{t(relationLabels[finding?.relation || "unverified"] || "Needs review")}</p>{finding?.reason && <p dir="auto" className="text-ink-soft">{finding.reason}</p>}
        {finding?.lectureAnchorRefs && finding.lectureAnchorRefs.length > 0 && <div><span>{t("Proof in lecture")}</span><SourceCitation courseId={courseId} sourceRefs={finding.lectureAnchorRefs} /></div>}
        <SupportingCitation courseId={courseId} sourceRefs={proofs.length ? proofs : requirement.supportingSourceRefs} />
      </div>;
    })}</div>}
  </article>;
}
