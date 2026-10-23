"use client";

import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { useLang } from "@/lib/i18n";

/** The same documents remain mounted while the compact reader changes panes. */
export default function ExamComparison({ left, right, leftTitle, rightTitle, singleRight = false, initiallyRight = false, focusInitially = false }: { left: ReactNode; right: ReactNode; leftTitle: string; rightTitle: string; singleRight?: boolean; initiallyRight?: boolean; focusInitially?: boolean }) {
  const { t } = useLang();
  const [active, setActive] = useState(initiallyRight ? 1 : 0);
  const tabRefs = useRef<(HTMLButtonElement | null)[]>([]);
  const paneRefs = useRef<(HTMLElement | null)[]>([]);
  const id = useId();
  useEffect(() => {
    if (focusInitially) paneRefs.current[initiallyRight ? 1 : 0]?.focus();
  }, [focusInitially, initiallyRight]);
  return (
    <div className={`exam-comparison ${singleRight ? "exam-comparison-single" : ""}`}>
      <div className="exam-document-tabs" role="tablist" aria-label={t("Exam documents")}>
        {[leftTitle, rightTitle].map((title, index) => <button key={title} type="button" role="tab" id={`${id}-tab-${index}`} aria-controls={`${id}-pane-${index}`} aria-selected={active === index} tabIndex={active === index ? 0 : -1} ref={(element) => { tabRefs.current[index] = element; }} className={`ui-button ${active === index ? "primary" : "ghost"}`} onClick={() => setActive(index)} onKeyDown={(event) => {
          const target = event.key === "Home" ? 0 : event.key === "End" ? 1 : ["ArrowLeft", "ArrowRight"].includes(event.key) ? 1 - index : null;
          if (target !== null) { event.preventDefault(); setActive(target); tabRefs.current[target]?.focus(); }
        }}>{t(title)}</button>)}
      </div>
      <div className="study-exam-grid exam-comparison-grid">
        {[left, right].map((pane, index) => <section key={index} id={`${id}-pane-${index}`} role="tabpanel" aria-labelledby={`${id}-tab-${index}`} tabIndex={-1} ref={(element) => { paneRefs.current[index] = element; }} className={`exam-document-pane ${active === index ? "is-active" : ""}`}>{pane}</section>)}
      </div>
    </div>
  );
}
