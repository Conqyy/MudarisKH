"use client";

import Link from "next/link";
import { useLang } from "@/lib/i18n";
import { foundationGuidance, type CourseFoundation } from "@/lib/course-foundation";
import Icon, { type IconName } from "./Icon";

interface Props {
  courseId: string; foundation: CourseFoundation | null; loading: boolean; error: string | null; ready: boolean;
  onRetry: () => void | Promise<unknown>; onUpload: () => void; onConfirm: () => void | Promise<unknown>;
  canConfirm: boolean; showConfirmation: boolean; supportCount: number;
}

const tools: { title: string; label: string; icon: IconName; path: string }[] = [
  { title: "AI Coach", label: "Ask the Coach", icon: "chat", path: "tutor" },
  { title: "Practice Exam", label: "Generate Exam", icon: "exam", path: "exam" },
  { title: "Flashcards", label: "Make Flashcards", icon: "cards", path: "flashcards" },
  { title: "Summary", label: "Make Summary", icon: "summary", path: "summary" },
];

export default function CourseJourney({ courseId, foundation, loading, error, ready, onRetry, onUpload, onConfirm, canConfirm, showConfirmation, supportCount }: Props) {
  const { t } = useLang();
  const prepared = !!foundation && foundation.documentCount > 0 && foundation.completedCount === foundation.documentCount && !foundation.failedCount;
  const confirmationLabel = ready ? "Confirmed" : loading ? "Loading…" : error ? "Retry foundation check" : "Waiting for documents";
  return (
    <section className="course-journey" aria-label={t("Your study journey")} aria-busy={loading}>
      <div className="section-heading journey-heading">
        <h2>{t("Your study journey")}</h2>
        <span className={`status-badge journey-overall-status ${ready ? "success" : foundation?.failedCount ? "warning" : "info"}`}><Icon name={ready ? "check-circle" : "layers"} size={14} />{t(ready ? "Ready to study" : "Course setup")}</span>
      </div>
      <div className="journey-nodes">
        <section className="journey-stage" data-complete={prepared}>
          <div className="journey-stage-heading"><span className="journey-stage-marker" aria-hidden="true">01</span><h3>{t("Lecture foundation")}</h3>{prepared && <Icon name="check" size={15} />}</div>
          <div className="journey-node journey-foundation-node">
            <div className="journey-ledger"><span className="journey-node-icon"><Icon name="file" size={23} /></span><div>{foundation ? <><strong>{foundation.completedCount}<span> / {foundation.documentCount}</span></strong><p>{t("Prepared and analyzed")}</p></> : <p>{t(loading ? "Checking your lecture document foundation…" : error ? "Retry foundation check" : "Upload your lecture documents")}</p>}</div></div>
            <Link href={`/course/${courseId}?section=documents`} className="journey-action-row"><span><Icon name="folder" size={17} />{t("View documents")}</span><Icon name="arrow-right" size={16} /></Link>
            <button onClick={onUpload} className="journey-action-row"><span><Icon name="upload" size={17} />{t("Upload lecture documents")}</span><Icon name="plus" size={16} /></button>
          </div>
        </section>
        <div className="journey-connector" aria-hidden="true"><span /><Icon name="arrow-right" size={15} /><span /></div>
        <section className="journey-stage" data-complete={ready}>
          <div className="journey-stage-heading"><span className="journey-stage-marker" aria-hidden="true">02</span><h3>{t("Confirm lectures")}</h3>{ready && <Icon name="check" size={15} />}</div>
          <div className={`journey-node journey-confirm-node ${ready ? "is-confirmed" : ""}`}>
            <span className="journey-confirm-mark"><Icon name={ready ? "check-circle" : "check"} size={27} /></span>
            <p>{t(ready ? "Your lecture foundation is confirmed." : "Confirm when all your lecture documents are ready.")}</p>
            {showConfirmation ? <button disabled={!canConfirm} onClick={() => { if (canConfirm) void onConfirm(); }} className="ui-button primary">{t("I've uploaded all lecture documents")}</button> : <span className={`status-badge journey-confirm-status ${ready ? "success" : ""}`}><Icon name={ready ? "check" : "lock"} size={14} />{t(confirmationLabel)}</span>}
          </div>
        </section>
        <div className="journey-connector" aria-hidden="true"><span /><Icon name="arrow-right" size={15} /><span /></div>
        <section className="journey-stage journey-study-stage" data-complete={ready}>
          <div className="journey-stage-heading"><span className="journey-stage-marker" aria-hidden="true">03</span><h3>{t("Study tools")}</h3><Icon name={ready ? "sparkles" : "lock"} size={16} /></div>
          <div className="journey-tools">{tools.map(tool => {
            const content = <><span className="journey-tool-icon"><Icon name={tool.icon} size={19} /></span><strong>{t(tool.title)}</strong><span className="journey-tool-label">{t(tool.label)}</span><Icon name={ready ? "arrow-right" : "lock"} size={14} className="journey-tool-direction" /></>;
            return ready ? <Link key={tool.path} href={`/course/${courseId}/${tool.path}`} className="journey-tool" aria-label={t(tool.label)}>{content}</Link> : <button key={tool.path} disabled aria-label={t(tool.label)} aria-describedby="foundation-lock-reason" className="journey-tool">{content}</button>;
          })}</div>
        </section>
      </div>
      <div className="journey-support">
        <span className="journey-support-branch" aria-hidden="true" /><span className="journey-support-icon"><Icon name="layers" size={19} /></span><div><strong>{t("Optional supporting materials")}</strong><p>{t("Past exams, tutorials, recordings and notes")}</p></div><span className="journey-support-count">{supportCount}</span><Link href={`/course/${courseId}?view=materials#past-exams`} className="journey-support-link">{t("View materials")}<Icon name="arrow-right" size={16} /></Link>
      </div>
      {!ready && <div className="journey-guidance" aria-label={t("Lecture document foundation")}><Icon name={error || foundation?.failedCount ? "alert" : "info"} size={17} /><div><p>{t(error || foundationGuidance(foundation, loading, error))}</p><p id="foundation-lock-reason" className="mt-1 text-xs">{t("Complete and confirm all lecture documents to unlock.")}</p></div><button onClick={() => void onRetry()} disabled={loading} className="ui-button ghost">{t("Retry foundation check")}</button></div>}
      {showConfirmation && <p className="journey-confirm-note">{t("Upload every lecture document you intend to study before confirming. Adding, deleting, or reanalyzing a document will require confirmation again.")}</p>}
    </section>
  );
}
