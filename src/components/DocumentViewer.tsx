"use client";

import { useState, useRef, useEffect } from "react";
import { CourseDocument } from "@/lib/firestore-helpers";
import BookmarkButton from "@/components/BookmarkButton";
import { useTrackRecent } from "@/lib/activity";

import { apiJson } from "@/lib/api";
import { useObjectUrl } from "@/lib/use-object-url";
import { useDialog } from "@/lib/use-dialog";
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

  const [activeTab, setActiveTab] = useState<"content" | "analysis">(
    doc.analysis ? "analysis" : "content"
  );
  const [activeChapter, setActiveChapter] = useState(0);
  const [extractedText, setExtractedText] = useState(doc.extractedText || "");
  const [loadingText, setLoadingText] = useState(false);
  const [textError, setTextError] = useState("");
  const [textAttempt, setTextAttempt] = useState(0);
  const dialogRef = useDialog(onClose);
  const chapterRefs = useRef<(HTMLDivElement | null)[]>([]);

  useEffect(() => {
    if (doc.fileType === "pdf") return;
    const controller = new AbortController();
    setExtractedText(doc.extractedText || "");
    setTextError("");
    if (doc.extractedText) { setLoadingText(false); return; }
    setLoadingText(true);
    apiJson(API_URL + "/api/documents/detail/" + doc.id, { signal: controller.signal })
      .then(data => { if (!controller.signal.aborted) setExtractedText(data.document?.extractedText || ""); })
      .catch(error => { if (!controller.signal.aborted) setTextError(error.message || "Could not load content."); })
      .finally(() => { if (!controller.signal.aborted) setLoadingText(false); });
    return () => controller.abort();
  }, [doc.id, doc.fileType, doc.extractedText, textAttempt]);

  const scrollToChapter = (idx: number) => {
    setActiveChapter(idx);
    chapterRefs.current[idx]?.scrollIntoView({
      behavior: "smooth",
      block: "start",
    });
  };

  const chapters = doc.analysis?.chapterMapping || [];
  const topics = doc.analysis?.topics || [];
  const definitions = doc.analysis?.definitions || [];
  const formulas = doc.analysis?.formulas || [];

  const pdfStoragePath = doc.storagePath;
  const isPdf = doc.fileType === "pdf";

  // The PDF endpoint needs an Authorization header, which <iframe src> and
  // <a href> cannot send, so fetch the bytes and hand the browser a blob URL.
  const pdf = useObjectUrl(isPdf ? pdfStoragePath : null, true);
  const pdfUrl = pdf.url;

  return (
    <div ref={dialogRef} role="dialog" aria-modal="true" aria-label={doc.title} tabIndex={-1} className="fixed inset-0 z-[100] flex">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-ink/30 backdrop-blur-sm"
        onClick={onClose}
      />

      {/* Panel */}
      <div className="relative ml-auto w-full max-w-5xl bg-paper shadow-2xl flex flex-col animate-slide-in-right">
        {/* Header */}
        <div className="border-b border-line px-6 py-4 flex items-center gap-4 flex-shrink-0">
          <button
            onClick={onClose}
            aria-label="Close document"
            className="w-8 h-8 rounded-full border border-line flex items-center justify-center text-ink-mute hover:bg-bg-alt transition text-sm"
          >
            &times;
          </button>
          <div className="flex-1 min-w-0">
            <h2 className="font-serif text-xl font-medium truncate">
              {doc.title}
            </h2>
            <div className="text-xs text-ink-mute font-mono mt-0.5 flex items-center gap-3">
              <span className="uppercase">{doc.fileType}</span>
              <span>
                {(doc.fileSize / 1024).toFixed(0)} KB
              </span>
              <span>
                {new Date(doc.uploadedAt).toLocaleDateString()}
              </span>
              {doc.analysis && (
                <span className="text-sage">
                  {doc.analysis.keyConceptCount} concepts
                </span>
              )}
            </div>
          </div>
          <BookmarkButton item={bookmarkItem} size="sm" />
          {isPdf && pdfStoragePath && pdfUrl && (
            <a
              href={pdfUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="border border-line px-4 py-2 rounded-full text-xs font-medium hover:bg-bg-alt transition flex-shrink-0"
            >
              Open PDF
            </a>
          )}
        </div>

        {/* Tabs */}
        <div className="border-b border-line px-6 flex gap-1 flex-shrink-0">
          {doc.analysis && (
            <button
              onClick={() => setActiveTab("analysis")}
              className={`px-4 py-3 text-sm font-medium border-b-2 transition ${
                activeTab === "analysis"
                  ? "border-accent text-accent"
                  : "border-transparent text-ink-mute hover:text-ink"
              }`}
            >
              Analysis
            </button>
          )}
          <button
            onClick={() => setActiveTab("content")}
            className={`px-4 py-3 text-sm font-medium border-b-2 transition ${
              activeTab === "content"
                ? "border-accent text-accent"
                : "border-transparent text-ink-mute hover:text-ink"
            }`}
          >
            Content
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-hidden flex">
          {activeTab === "analysis" && doc.analysis ? (
            <>
              {/* Chapter Navigation Sidebar */}
              {chapters.length > 0 && (
                <nav className="hidden sm:block w-56 border-r border-line overflow-y-auto flex-shrink-0 p-4">
                  <div className="text-xs font-mono text-ink-mute uppercase tracking-widest mb-3">
                    Chapters
                  </div>
                  <div className="space-y-1">
                    {chapters.map((ch, idx) => (
                      <button
                        key={idx}
                        onClick={() => scrollToChapter(idx)}
                        className={`w-full text-left px-3 py-2 rounded-lg text-sm transition ${
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
                      <div className="text-xs font-mono text-ink-mute uppercase tracking-widest mt-6 mb-3">
                        Topics
                      </div>
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
              <div className="flex-1 overflow-y-auto p-6 space-y-8">
                {/* Chapters */}
                {chapters.length > 0 && (
                  <section>
                    <h3 className="font-serif text-lg font-medium mb-4">
                      Chapter Breakdown
                    </h3>
                    <div className="space-y-4">
                      {chapters.map((ch, idx) => (
                        <div
                          key={idx}
                          ref={(el) => { chapterRefs.current[idx] = el; }}
                          className="bg-bg rounded-2xl p-5 border border-line"
                        >
                          <h4 className="font-medium text-sm mb-2 flex items-center gap-2">
                            <span className="w-6 h-6 rounded-full bg-accent/10 text-accent text-xs flex items-center justify-center font-mono">
                              {idx + 1}
                            </span>
                            {ch.chapter}
                          </h4>
                          <p className="text-sm text-ink-soft leading-relaxed">
                            {ch.content}
                          </p>
                        </div>
                      ))}
                    </div>
                  </section>
                )}

                {/* Definitions */}
                {definitions.length > 0 && (
                  <section>
                    <h3 className="font-serif text-lg font-medium mb-4">
                      Definitions ({definitions.length})
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
                    <h3 className="font-serif text-lg font-medium mb-4">
                      Formulas ({formulas.length})
                    </h3>
                    <div className="space-y-2">
                      {formulas.map((f, idx) => (
                        <div
                          key={idx}
                          className="bg-bg border border-line rounded-xl px-4 py-3 font-mono text-sm text-ink-soft"
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
            /* Content Tab — shows extracted text or PDF */
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
                    {!pdfStoragePath ? "PDF file is unavailable for this document." : pdf.error ? <div role="alert" className="text-center"><p>{pdf.error}</p><button onClick={pdf.retry} className="mt-3 underline">Retry PDF</button></div> : "Loading PDF..."}
                  </div>
                )
              ) : loadingText ? (
                <div className="flex items-center justify-center h-full text-ink-mute text-sm">
                  Loading content...
                </div>
              ) : extractedText ? (
                <pre className="p-6 text-sm font-mono text-ink-soft leading-relaxed whitespace-pre-wrap">
                  {extractedText}
                </pre>
              ) : (
                <div className="flex items-center justify-center h-full text-ink-mute text-sm">
                  {textError ? <p role="alert">{textError}</p> : <p>No content available for this document.</p>}
                  <button onClick={() => setTextAttempt(n => n + 1)} className="ms-3 underline">Retry content</button>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
