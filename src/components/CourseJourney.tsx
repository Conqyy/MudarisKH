"use client";
import Link from "next/link";
import { useLang } from "@/lib/i18n";
import { foundationGuidance, type CourseFoundation } from "@/lib/course-foundation";
import Icon, { type IconName } from "./Icon";

export default function CourseJourney({ courseId, foundation, loading, error, ready, onRetry, onUpload, onConfirm, canConfirm, showConfirmation, supportCount }: {
  courseId: string; foundation: CourseFoundation | null; loading: boolean; error: string | null; ready: boolean;
  onRetry: () => void | Promise<unknown>; onUpload: () => void; onConfirm: () => void | Promise<unknown>;
  canConfirm: boolean; showConfirmation: boolean; supportCount: number;
}) {
  const { t } = useLang();
  const tools: { title: string; label: string; icon: IconName; path: string }[] = [
    { title: "AI Coach", label: "Ask the Coach", icon: "chat", path: "tutor" },
    { title: "Practice Exam", label: "Generate Exam", icon: "exam", path: "exam" },
    { title: "Flashcards", label: "Make Flashcards", icon: "cards", path: "flashcards" },
    { title: "Summary", label: "Make Summary", icon: "summary", path: "summary" },
  ];
  return <section className="course-journey" aria-label={t("Your study journey")} aria-busy={loading}>
    <div className="section-heading"><h2>{t("Your study journey")}</h2><span className={`status-badge ${ready ? "success" : foundation?.failedCount ? "warning" : "info"}`}><Icon name={ready ? "check-circle" : "layers"} size={14} />{ready ? t("Ready to study") : t("Course setup")}</span></div>
    <div className="journey-nodes">
      <div className="journey-node"><span className="journey-node-icon"><Icon name="file" size={22} /></span><span className="journey-step">01</span><h3>{t("Lecture foundation")}</h3><p>{foundation ? `${foundation.completedCount} / ${foundation.documentCount} ${t("Prepared and analyzed")}` : t(loading ? "Checking your lecture document foundation…" : error ? "Retry foundation check" : "Upload your lecture documents")}</p>
        <Link href={`/course/${courseId}?section=documents`} className="journey-doc-link">{t("View documents")}<Icon name="arrow-right" size={14} /></Link>
        <button onClick={onUpload} className="ui-button secondary"><Icon name="plus" size={15} />{t("Upload lecture documents")}</button>
      </div>
      <div className="journey-connector" aria-hidden="true"><Icon name="arrow-right" size={18} /></div>
      <div className="journey-node"><span className="journey-node-icon"><Icon name={ready ? "check-circle" : "check"} size={22} /></span><span className="journey-step">02</span><h3>{t("Confirm lectures")}</h3><p>{ready ? t("Your lecture foundation is confirmed.") : t("Confirm when all your lecture documents are ready.")}</p>
        {showConfirmation ? <button disabled={!canConfirm} onClick={() => { if (canConfirm) void onConfirm(); }} className="ui-button primary">{t("I've uploaded all lecture documents")}</button> : <span className={`status-badge ${ready ? "success" : ""}`}><Icon name={ready ? "check" : "lock"} size={14} />{ready ? t("Confirmed") : t(loading ? "Loading…" : error ? "Retry foundation check" : "Waiting for documents")}</span>}
      </div>
      <div className="journey-connector" aria-hidden="true"><Icon name="arrow-right" size={18} /></div>
      <div className="journey-node journey-study-node"><span className="journey-node-icon"><Icon name="sparkles" size={22} /></span><span className="journey-step">03</span><h3>{t("Study tools")}</h3><div className="journey-tools">{tools.map(tool => <div className="journey-tool" key={tool.path}><span><Icon name={tool.icon} size={17} /><strong>{t(tool.title)}</strong></span>{ready ? <Link href={`/course/${courseId}/${tool.path}`} className="journey-tool-action">{t(tool.label)}<Icon name="arrow-right" size={14} /></Link> : <button disabled aria-describedby="foundation-lock-reason" className="journey-tool-action"><Icon name="lock" size={12} />{t(tool.label)}</button>}</div>)}</div></div>
    </div>
    <div className="journey-support"><span className="journey-support-branch" aria-hidden="true" /><Icon name="layers" size={18} /><div><strong>{t("Optional supporting materials")}</strong><p>{t("Past exams, tutorials, recordings and notes")}</p></div><span className="status-badge">{supportCount}</span><Link href={`/course/${courseId}?view=materials#past-exams`} className="ui-button ghost">{t("View materials")}<Icon name="arrow-right" size={15} /></Link></div>
    {!ready && <div className="journey-guidance" aria-label={t("Lecture document foundation")}><Icon name={error || foundation?.failedCount ? "alert" : "info"} size={17} /><div><p>{t(error || foundationGuidance(foundation, loading, error))}</p><p id="foundation-lock-reason" className="mt-1 text-xs">{t("Complete and confirm all lecture documents to unlock.")}</p></div><button onClick={() => void onRetry()} disabled={loading} className="ui-button ghost">{t("Retry foundation check")}</button></div>}
    {showConfirmation && <p className="journey-confirm-note">{t("Upload every lecture document you intend to study before confirming. Adding, deleting, or reanalyzing a document will require confirmation again.")}</p>}
  </section>;
}
