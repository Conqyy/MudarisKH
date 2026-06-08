"use client";

import { useState, useRef, useEffect } from "react";
import { CourseDocument } from "@/lib/firestore-helpers";
import BookmarkButton from "@/components/BookmarkButton";
import { useTrackRecent } from "@/lib/activity";

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
  const chapterRefs = useRef<(HTMLDivElement | null)[]>([]);

  useEffect(() => {
    if (activeTab === "content" && !extractedText && !loadingText && doc.fileType !== "pdf") {
      setLoadingText(true);
      fetch(`${API_URL}/api/documents/detail/${doc.id}`)
        .then((r) => r.json())
        .then((data) => {
          if (data.document?.extractedText) {
            setExtractedText(data.document.extractedText);
          }
        })
        .catch(() => {})
        .finally(() => setLoadingText(false));
    }
  }, [activeTab, extractedText, loadingText, doc.id, doc.fileType]);

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

  return (
    <div className="fixed inset-0 z-50 flex">
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
          {isPdf && pdfStoragePath && (
            <a
              href={`${API_URL}/api/files/serve?path=${encodeURIComponent(pdfStoragePath)}`}
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
                <nav className="w-56 border-r border-line overflow-y-auto flex-shrink-0 p-4">
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
              {isPdf && pdfStoragePath ? (
                <iframe
                  src={`${API_URL}/api/files/serve?path=${encodeURIComponent(pdfStoragePath)}`}
                  className="w-full h-full border-0"
                  title={doc.title}
                />
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
                  No content available for this document.
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
