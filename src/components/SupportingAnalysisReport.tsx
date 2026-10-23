"use client";

import SupportingCitation from "@/components/SupportingCitation";
import SourceCitation from "@/components/SourceCitation";
import { useSupportingAnalysis } from "@/hooks/useSupportingAnalysis";
import { useLang } from "@/lib/i18n";
import { MaterialKind, SupportingAlignment, SupportingItem, SupportingReportPage, SupportingTopic } from "@/lib/supporting-materials";

const statusLabels: Record<string, string> = { covered: "Covered", partly_covered: "Partly covered", not_covered: "Not covered", needs_review: "Needs review", nonacademic: "Not academic content" };
const relationLabels: Record<string, string> = { lecture_supported: "Supported by lecture", related_supplementary: "Related supplement", outside_selected_scope: "Outside selected chapters", not_found: "Not found in selected lectures", unverified: "Needs review", conflicting: "Conflicting evidence" };
function coverageCount(value: Record<string, unknown> | undefined, allKey: string, checkedKey: string): string | null {
  const all = value?.[allKey], checked = value?.[checkedKey];
  if (!Array.isArray(all) || !Array.isArray(checked)) return null;
  return `${checked.length} / ${all.length}`;
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
  const extraction = coverageCount(report?.extractionCoverage, "unitIds", "accountedUnitIds");
  const alignment = coverageCount(report?.alignmentCoverage, "itemIds", "checkedItemIds");
  const topics = coverageCount(report?.alignmentCoverage, "topicIds", "checkedTopicIds");
  const canRetry = status && (status.legacy || status.stale || ["failed", "incomplete"].includes(status.status));
  return <section className="material-reader space-y-5" aria-label={t("Supporting material report")}>
    <h3 className="section-heading pe-10">{t("Supporting material report")}</h3>
    {loading && <p>{t("Loading source…")}</p>}
    {status && <p className="text-sm text-ink-soft">{status.progress?.completedUnits ?? 0}{status.progress?.totalUnits != null ? ` / ${status.progress.totalUnits}` : ""} {t("source units")}{["queued", "processing", "preparing", "extracting", "aligning"].includes(status.status) && status.stage ? ` · ${t(status.stage === "extracting" ? "Extracting source content…" : status.stage === "aligning" ? "Comparing with lectures…" : status.stage === "queued" ? "Uploaded; analysis is queued." : "Processing")}` : ""}</p>}
    {statusWarning && <p role="status" className="material-inline-notice warning">{t(statusWarning)}</p>}
    {status?.errorMessage && <p role="alert" className="material-inline-notice danger" dir="auto">{status.errorMessage}</p>}
    {error && <p role="alert" className="text-sm text-accent">{error}</p>}
    {canRetry && <button type="button" className="ui-button secondary" onClick={() => void retry()}>{t(status?.legacy ? "Prepare material" : "Retry analysis")}</button>}
    {report && <>
      <div className="flex flex-wrap gap-x-6 gap-y-2 text-sm text-ink-soft border-y border-line py-4 tabular-nums"><span>{t("Extraction coverage")}: {extraction ?? t("Unknown")}</span><span>{t("Alignment coverage")}: {alignment ?? t("Unknown")}</span><span>{t("Topic coverage")}: {topics ?? t("Unknown")}</span></div>
      {(report.extractionCoverage?.complete === false || report.alignmentCoverage?.complete === false) && <p className="text-sm text-gold">{t("Some source content could not be checked.")}</p>}
      {[...groups].map(([paperId, items]) => {
        const paper = paperById.get(paperId);
        const title = typeof paper?.title === "string" ? paper.title : typeof paper?.printedLabel === "string" ? paper.printedLabel : paperId ? `${t("Paper")} ${paperId}` : t("Items");
        return <section key={paperId || "unassigned"} className="border-t border-line pt-5 space-y-4">
          <h4 className="font-medium" dir="auto">{title}</h4>
          {items.map(item => <ReportItem key={item.id} item={item} alignment={alignmentById.get(item.id)} report={report} courseId={courseId} t={t} />)}
        </section>;
      })}
      {report.topics?.length > 0 && <section className="border-t border-line pt-5 space-y-3"><h4 className="font-medium">{t("Topics")}</h4>{[...new Map(report.topics.map(topic => [topic.id, topic])).values()].map(topic => <ReportTopic key={topic.id} topic={topic} report={report} courseId={courseId} t={t} />)}</section>}
      {report.nextOffset !== null && <button type="button" className="underline text-sm" onClick={() => void loadMore()}>{t("Load more results")}</button>}
    </>}
  </section>;
}

function ReportItem({ item, alignment, report, courseId, t }: { item: SupportingItem; alignment?: SupportingAlignment; report: SupportingReportPage; courseId: string; t: (value: string) => string }) {
  const byRequirement = new Map(alignment?.requirements.map(row => [row.requirementId, row]));
  return <article id={`supporting-item-${item.id}`} className="bg-bg-alt rounded-xl p-4 space-y-3">
    <div className="flex flex-wrap gap-2 items-center"><strong dir="auto">{item.printedLabel || item.itemType}</strong><span className="status-badge info">{t(statusLabels[alignment?.status || "needs_review"] || "Needs review")}</span>{item.printedMarks !== null && typeof item.printedMarks === "number" && <span>{item.printedMarks} {t("marks")}</span>}</div>
    <p dir="auto" className="text-sm whitespace-pre-wrap">{item.text}</p>
    {item.requirements?.length > 0 && <div><h5 className="text-sm font-medium">{t("Required concepts")}</h5>{item.requirements.map(requirement => {
      const finding = byRequirement.get(requirement.id);
      const proofs = finding?.supportingSourceProofs?.map(proof => proof.ref).filter(Boolean) || [];
      return <div key={requirement.id} className="mt-2 text-sm border-s-2 border-line ps-3"><p dir="auto">{requirement.text}</p><p>{t(relationLabels[finding?.relation || "unverified"] || "Needs review")}</p>{finding?.reason && <p dir="auto" className="text-ink-soft">{finding.reason}</p>}
        {finding?.lectureAnchorRefs && finding.lectureAnchorRefs.length > 0 && <div><span>{t("Proof in lecture")}</span><SourceCitation courseId={courseId} sourceRefs={finding.lectureAnchorRefs} /></div>}
        <SupportingCitation courseId={courseId} sourceRefs={proofs.length ? proofs : requirement.supportingSourceRefs} />
      </div>;
    })}</div>}
    {!!alignment?.contextDependencies?.length && <div className="space-y-2"><h5 className="text-sm font-medium">{t("Context dependencies")}</h5>{alignment.contextDependencies.map(dependency => {
      const owner = dependency.ownerType === "shared_context" ? report.sharedContexts.find(row => row.id === dependency.ownerId) : report.items.find(row => row.id === dependency.ownerId);
      const value = owner && dependency.field in owner ? (owner as unknown as Record<string, unknown>)[dependency.field] : null;
      const content = dependency.index === null ? value : Array.isArray(value) ? value[dependency.index] : null;
      const label = dependency.decision === "not_required" ? "Context not required" : dependency.decision === "unresolved" || !dependency.usable ? "Context needs review" : "Required context";
      return <div key={dependency.componentId} className="text-sm border-s-2 border-line ps-3 space-y-1"><p>{t(label)} · {t(relationLabels[dependency.relation] || (dependency.relation === "source_only" ? "Source-only context" : dependency.relation === "not_applicable" ? "Not applicable" : "Needs review"))}</p>{typeof content === "string" && <p dir="auto" className="whitespace-pre-wrap">{content}</p>}{dependency.verification?.reason && <p dir="auto" className="text-ink-soft">{dependency.verification.reason}</p>}{!!dependency.lectureSupportProofs?.length && <SourceCitation courseId={courseId} sourceRefs={dependency.lectureSupportProofs.map(proof => proof.ref)} />}<SupportingCitation courseId={courseId} sourceRefs={dependency.supportingSourceProofs?.map(proof => proof.ref)} /></div>;
    })}</div>}
  </article>;
}

function ReportTopic({ topic, report, courseId, t }: { topic: SupportingTopic; report: SupportingReportPage; courseId: string; t: (value: string) => string }) {
  const originItems = new Map(report.items.map(item => [item.id, item]));
  const requirements = new Map(report.items.flatMap(item => item.requirements).map(requirement => [requirement.id, requirement]));
  const finding = topic.alignment;
  return <article className="border-t border-line pt-4 space-y-3 text-sm"><p dir="auto" className="font-medium">{topic.text}</p><p>{t(relationLabels[finding?.relation || "unverified"] || "Needs review")}</p>{finding?.reason && <p dir="auto" className="text-ink-soft">{finding.reason}</p>}
    <div><span>{t("Origin questions")}: </span>{topic.itemIds.map((id, index) => { const item = originItems.get(id); return <span key={id}>{index > 0 && ", "}{item ? <a className="underline" href={`#supporting-item-${id}`}>{item.printedLabel || item.text}</a> : <span>{t("Origin question on another page")} ({id})</span>}</span>; })}</div>
    <div><span>{t("Origin requirements")}: </span>{topic.requirementIds.map(id => <span key={id} dir="auto" className="me-2">{requirements.get(id)?.text || `${t("Origin requirement on another page")} (${id})`}</span>)}</div>
    {!!finding?.lectureSupportProofs?.length && <SourceCitation courseId={courseId} sourceRefs={finding.lectureSupportProofs.map(proof => proof.ref)} />}
    <SupportingCitation courseId={courseId} sourceRefs={finding?.supportingSourceProofs?.map(proof => proof.ref) || topic.supportingSourceRefs} />
  </article>;
}
