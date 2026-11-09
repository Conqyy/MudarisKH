"use client";

import Icon from "@/components/Icon";

import { useState, useRef, useEffect } from "react";
import { CourseDocument } from "@/lib/firestore-helpers";
import SourceCitation from "@/components/SourceCitation";
import { useAuth } from "@/lib/auth-context";
import { useLang } from "@/lib/i18n";
import BookmarkButton from "@/components/BookmarkButton";
import { useTrackRecent } from "@/lib/activity";

import { apiJson } from "@/lib/api";
import { useObjectUrl } from "@/lib/use-object-url";
import { useOverlayMotion } from "@/lib/use-overlay-motion";
const API_URL =
  process.env.NEXT_PUBLIC_BACKEND_URL || "http://127.0.0.1:8000";

interface DocumentViewerProps {
  document: CourseDocument;
  onClose: () => void;
  courseCode?: string;
  courseColor?: string;
}

export default function DocumentViewer({
  document: doc,
  onClose,
  courseCode,
  courseColor,
}: DocumentViewerProps) {
  const { user } = useAuth();
  const { t } = useLang();
  // Record this document as recently opened.
  const courseId = (doc as any).courseId as string | undefined;
  const bookmarkItem = {
    kind: "document" as const,
    id: doc.id,
    title: doc.title,
    href: courseId ? `/course/${courseId}?doc=${doc.id}` : `#`,
    courseCode,
    courseColor,
  };
  useTrackRecent(bookmarkItem);

  const defaultTab = doc.guide || doc.analysis ? "analysis" : doc.fileType !== "pdf" && doc.sourceRevision ? "sources" : "content";
  const [activeTab, setActiveTab] = useState<"content" | "analysis" | "sources">(defaultTab);
  const [activeChapter, setActiveChapter] = useState(0);
  const { ref: dialogRef, close: closeDialog } = useOverlayMotion(onClose, { kind: "drawer" });
  const [sourceAttempt, setSourceAttempt] = useState(0);
  const [sourceState, setSourceState] = useState<{ key: string; units: { unitId: string; label: string; kind: string }[]; warnings: string[]; error?: string } | null>(null);
  const sourceKey = JSON.stringify([user?.uid, doc.courseId, doc.id, doc.sourceRevision]);
  useEffect(() => {
    setActiveTab(defaultTab);
    setActiveChapter(0);
  }, [defaultTab, doc.id, user?.uid]);
  useEffect(() => {
    if (!doc.sourceRevision || !user?.uid) return;
    const controller = new AbortController();
    setSourceState(null);
    apiJson(`${API_URL}/api/documents/${encodeURIComponent(doc.id)}/sources`, { signal: controller.signal })
      .then(data => {
        if (controller.signal.aborted) return;
        if (!data.source?.available || data.source.sourceRevision !== doc.sourceRevision) throw new Error(t("This source version is unavailable."));
        setSourceState({ key: sourceKey, units: data.source.units || [], warnings: data.source.warnings || [] });
      })
      .catch(error => { if (!controller.signal.aborted) setSourceState({ key: sourceKey, units: [], warnings: [], error: error.message || t("Could not load source. Retry.") }); });
    return () => controller.abort();
  }, [sourceKey, sourceAttempt, doc.sourceRevision, doc.id, user?.uid, t]);
  const sources = sourceState?.key === sourceKey ? sourceState : null;
  const chapterRefs = useRef<(HTMLDivElement | null)[]>([]);

  const scrollToChapter = (idx: number) => {
    setActiveChapter(idx);
    chapterRefs.current[idx]?.scrollIntoView({
      behavior: "auto",
      block: "start",
    });
  };

  const chapters = doc.guide ? doc.guide.sections.map(section => ({ chapter: section.label, content: section.purpose })) : doc.analysis?.chapterMapping || [];
  const topics = doc.guide ? doc.guide.concepts.map(concept => concept.name) : doc.analysis?.topics || [];
  const definitions = doc.guide ? [] : doc.analysis?.definitions || [];
  const formulas = doc.guide ? [] : doc.analysis?.formulas || [];

  const pdfOriginalRoute = `${API_URL}/api/documents/${encodeURIComponent(doc.id)}/original`;
  const isPdf = doc.fileType === "pdf";

  // The PDF endpoint needs an Authorization header, which <iframe src> and
  // <a href> cannot send, so fetch the bytes and hand the browser a blob URL.
  const pdf = useObjectUrl(isPdf && user?.uid ? pdfOriginalRoute : null, false, `${user?.uid}:${doc.courseId}:${doc.id}`);
  const pdfUrl = pdf.url;

  return (
    <div ref={dialogRef} role="dialog" aria-modal="true" aria-label={doc.title} tabIndex={-1} className="material-viewer">
      {/* Backdrop */}
      <div
        className="material-viewer-backdrop"
        onClick={closeDialog}
      />

      {/* Panel */}
      <div className="material-viewer-panel">
        {/* Header */}
        <div className="material-viewer-header">
          <button
            onClick={closeDialog}
            aria-label={t("Close document")}
            className="icon-button"
          ><Icon name="close" /></button>
          <div className="material-viewer-title">
            <h2 dir="auto" className="font-sans text-xl font-semibold break-words">
              {doc.title}
            </h2>
            <div className="text-xs text-ink-soft tabular-nums mt-1 flex flex-wrap items-center gap-x-3 gap-y-1">
              <span className="uppercase">{doc.fileType}</span>
              <span>
                {(doc.fileSize / 1024).toFixed(0)} KB
              </span>
              <span>
                {new Date(doc.uploadedAt).toLocaleDateString()}
              </span>
              {!doc.guide && doc.analysis && <span className="text-sage">{doc.analysis.keyConceptCount} {t("concepts")}</span>}
              {doc.guide && (
                <span className="text-sage">
                  {doc.unitCount ?? "—"} {t("source units")} · {doc.guide.sections.length} {t("guide sections")}
                </span>
              )}
            </div>
          </div>
          <BookmarkButton item={bookmarkItem} size="sm" />
          {isPdf && pdfUrl && (
            <a
              href={pdfUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="ui-button secondary"
            >{t("Open PDF")}</a>
          )}
        </div>

        {/* Tabs */}
        <div className="material-viewer-tabs">
          {(doc.guide || doc.analysis) && (
            <button
              onClick={() => setActiveTab("analysis")}
              className={`ui-button ${
                activeTab === "analysis"
                  ? "primary"
                  : "ghost"
              }`}
            >
              {t(doc.guide ? "Lightweight analysis" : "Analysis")}
            </button>
          )}
          {isPdf && <button
            onClick={() => setActiveTab("content")}
            className={`ui-button ${
              activeTab === "content"
                ? "primary"
                : "ghost"
            }`}
          >
            {t("Content")}
          </button>}
          {doc.sourceRevision && <button onClick={() => setActiveTab("sources")} className={`ui-button ${activeTab === "sources" ? "primary" : "ghost"}`}>{t("Source units")}</button>}
        </div>

        {/* Body */}
        <div className="flex-1 overflow-hidden flex">
          {activeTab === "sources" ? (
            <div className="flex-1 overflow-y-auto p-6 space-y-4">
              {!sources ? <p>{t("Loading source…")}</p> : sources.error ? <div role="alert"><p>{sources.error}</p><button className="ui-button secondary mt-2" onClick={() => setSourceAttempt(n => n + 1)}>{t("Retry source")}</button></div> : <>
                {sources.warnings.length > 0 && <details className="material-warning-disclosure"><summary><Icon name="alert" size={16} />{t("Source notices")}<span>{sources.warnings.length}</span><Icon name="chevron-down" size={15} /></summary><div>{sources.warnings.map((warning, i) => <p key={i} className="material-inline-notice warning" dir="auto">{warning}</p>)}</div></details>}
                {sources.units.map(unit => <div key={unit.unitId} className="border-b border-line pb-4"><SourceCitation courseId={doc.courseId} sourceRefs={[{ documentId: doc.id, sourceRevision: doc.sourceRevision, unitId: unit.unitId, label: unit.label }]} /></div>)}
              </>}
            </div>
          ) : activeTab === "analysis" && (doc.guide || doc.analysis) ? (
            <>
              {/* Chapter Navigation Sidebar */}
              {chapters.length > 0 && (
                <nav aria-label={t("Document sections")} className="hidden sm:block w-56 border-e border-line overflow-y-auto flex-shrink-0 p-4">
                  <div className="text-xs font-semibold text-ink-soft mb-3">
                    {t(doc.guide ? "Guide sections" : "Chapters")}
                  </div>
                  <div className="space-y-1">
                    {chapters.map((ch, idx) => (
                      <button
                        key={idx}
                        onClick={() => scrollToChapter(idx)}
                        aria-current={activeChapter === idx ? "location" : undefined}
                        dir="auto" className={`w-full min-h-11 text-start px-3 py-2 rounded-lg text-sm transition ${
                          activeChapter === idx
                            ? "bg-accent/10 text-accent font-medium"
                            : "text-ink-soft hover:bg-bg-alt"
                        }`}
                      >
                        {ch.chapter}
                      </button>
                    ))}
                  </div>

                  {topics.length > 0 && (
                    <>
                      <div className="text-xs font-semibold text-ink-soft mt-6 mb-3">{t("Topics")}</div>
                      <div className="flex flex-wrap gap-1.5">
                        {topics.map((t, i) => (
                          <span
                            key={i}
                            className="bg-sage/10 text-sage text-xs px-2 py-0.5 rounded-full"
                          >
                            {t}
                          </span>
                        ))}
                      </div>
                    </>
                  )}
                </nav>
              )}

              {/* Analysis Content */}
              <div className="material-reader flex-1 overflow-y-auto p-5 md:p-7 space-y-8">
                {!!doc.guide?.warnings.length && <details className="material-warning-disclosure"><summary><Icon name="alert" size={16} />{t("Source notices")}<span>{doc.guide.warnings.length}</span><Icon name="chevron-down" size={15} /></summary><div>{doc.guide.warnings.map((warning, i) => <p key={i} className="material-inline-notice warning" dir="auto">{warning}</p>)}</div></details>}
                {/* Chapters */}
                {chapters.length > 0 && (
                  <section>
                    <h3 className="section-heading mb-4">
                      {t(doc.guide ? "Guide sections" : "Chapter Breakdown")}
                    </h3>
                    <div className="space-y-4">
                      {chapters.map((ch, idx) => (
                        <div
                          key={idx}
                          ref={(el) => { chapterRefs.current[idx] = el; }}
                          className="bg-bg-alt rounded-2xl p-5"
                        >
                          <h4 dir="auto" className="font-semibold text-sm mb-2 flex items-start gap-2">
                            <span className="w-6 h-6 rounded-full bg-accent/10 text-accent text-xs flex items-center justify-center tabular-nums">
                              {idx + 1}
                            </span>
                            {ch.chapter}
                          </h4>
                          <p dir="auto" className="text-sm text-ink-soft leading-relaxed">
                            {ch.content}
                          </p>
                          {doc.guide && <SourceCitation courseId={doc.courseId} sourceRefs={doc.guide.sections[idx].unitIds.map(unitId => ({ documentId: doc.id, sourceRevision: doc.guide?.sourceRevision, unitId }))} />}
                        </div>
                      ))}
                    </div>
                  </section>
                )}

                {doc.guide && doc.guide.concepts.length > 0 && <section><h3 className="section-heading mb-4">{t("Guide concepts")}</h3><div className="space-y-3">{doc.guide.concepts.map((concept, i) => <div key={i} className="border border-line rounded-xl p-4"><p>{concept.name}</p><SourceCitation courseId={doc.courseId} sourceRefs={concept.unitIds.map(unitId => ({ documentId: doc.id, sourceRevision: doc.guide?.sourceRevision, unitId }))} /></div>)}</div></section>}
                {/* Definitions */}
                {definitions.length > 0 && (
                  <section>
                    <h3 className="section-heading mb-4">
                      {t("Definitions")} ({definitions.length})
                    </h3>
                    <div className="bg-bg rounded-2xl border border-line overflow-hidden">
                      {definitions.map((def, idx) => (
                        <div
                          key={idx}
                          className={`px-5 py-4 ${
                            idx !== 0 ? "border-t border-line" : ""
                          }`}
                        >
                          <div className="font-medium text-sm text-accent">
                            {def.term}
                          </div>
                          <div className="text-sm text-ink-soft mt-1">
                            {def.definition}
                          </div>
                        </div>
                      ))}
                    </div>
                  </section>
                )}

                {/* Formulas */}
                {formulas.length > 0 && (
                  <section>
                    <h3 className="section-heading mb-4">
                      {t("Formulas")} ({formulas.length})
                    </h3>
                    <div className="space-y-2">
                      {formulas.map((f, idx) => (
                        <div
                          key={idx}
                          className="bg-bg border border-line rounded-xl px-4 py-3 tabular-nums text-sm text-ink-soft"
                        >
                          {f}
                        </div>
                      ))}
                    </div>
                  </section>
                )}
              </div>
            </>
          ) : (
            /* Original PDF or preparation guidance for legacy Office files. */
            <div className="flex-1 overflow-y-auto">
              {isPdf ? (
                pdfUrl ? (
                  <iframe
                    src={pdfUrl}
                    className="w-full h-full border-0"
                    title={doc.title}
                  />
                ) : (
                  <div className="flex items-center justify-center h-full text-ink-mute text-sm">
                    {pdf.error ? <div role="alert" className="text-center"><p>{pdf.error}</p><button onClick={pdf.retry} className="ui-button secondary mt-3">{t("Retry PDF")}</button></div> : t("Loading PDF...")}
                  </div>
                )
              ) : (
                <div className="flex items-center justify-center h-full text-ink-mute text-sm">
                  <p>{t("Prepare this document from the course page to view its original source units.")}</p>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
