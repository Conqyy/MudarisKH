"use client";

import { AudioRecording } from "@/lib/firestore-helpers";
import BookmarkButton from "@/components/BookmarkButton";
import { useTrackRecent } from "@/lib/activity";

const API_URL =
  process.env.NEXT_PUBLIC_BACKEND_URL || "http://127.0.0.1:8000";

interface AudioViewerProps {
  recording: AudioRecording;
  onClose: () => void;
  courseCode?: string;
  courseColor?: string;
}

export default function AudioViewer({
  recording,
  onClose,
  courseCode,
  courseColor,
}: AudioViewerProps) {
  const insights = recording.insights;

  const courseId = (recording as any).courseId as string | undefined;
  const bookmarkItem = {
    kind: "audio" as const,
    id: recording.id,
    title: recording.title,
    href: courseId ? `/course/${courseId}?audio=${recording.id}` : "#",
    courseCode,
    courseColor,
  };
  useTrackRecent(bookmarkItem);

  const examHints = insights?.examHints || [];
  const keyEmphasis = insights?.keyEmphasis || [];
  const chapters = insights?.chapterMapping || [];

  const emphasisColor = (level: string) =>
    level === "high"
      ? "text-accent bg-accent/10"
      : level === "medium"
      ? "text-gold bg-gold/10"
      : "text-ink-mute bg-bg-alt";

  return (
    <div className="fixed inset-0 z-50 flex">
      <div
        className="absolute inset-0 bg-ink/30 backdrop-blur-sm"
        onClick={onClose}
      />

      <div className="relative ml-auto w-full max-w-4xl bg-paper shadow-2xl flex flex-col animate-slide-in-right">
        {/* Header */}
        <div className="border-b border-line px-6 py-4 flex items-center gap-4 flex-shrink-0">
          <button
            onClick={onClose}
            className="w-8 h-8 rounded-full border border-line flex items-center justify-center text-ink-mute hover:bg-bg-alt transition text-sm"
          >
            &times;
          </button>
          <div className="flex-1 min-w-0">
            <h2 className="font-serif text-xl font-medium truncate flex items-center gap-2">
              <span>🎙️</span> {recording.title}
            </h2>
            <div className="text-xs text-ink-mute font-mono mt-0.5 flex items-center gap-3">
              <span>{new Date(recording.uploadedAt).toLocaleDateString()}</span>
              {examHints.length > 0 && (
                <span className="text-gold">{examHints.length} exam hints</span>
              )}
            </div>
          </div>
          {insights && (
            <a
              href={`${API_URL}/api/audio/${recording.id}/pdf`}
              target="_blank"
              rel="noopener noreferrer"
              className="flex-shrink-0 bg-accent text-paper px-4 py-2 rounded-full text-sm font-medium hover:bg-ink transition flex items-center gap-2"
              title="Download analysis & transcript as PDF"
            >
              <span>↓</span> PDF
            </a>
          )}
          <BookmarkButton item={bookmarkItem} size="sm" />
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto">
          {insights ? (
            <div className="p-6 space-y-8">
              {/* Lecture summary — what the professor said */}
              {insights.summary && (
                <section>
                  <h3 className="font-serif text-lg font-medium mb-3">
                    Lecture Summary
                  </h3>
                  <div className="text-sm text-ink-soft leading-relaxed bg-bg rounded-2xl border border-line p-5 space-y-3">
                    {insights.summary
                      .split(/\n\n+/)
                      .filter((p) => p.trim())
                      .map((para, i) => (
                        <p key={i} dir="auto" className="text-start">
                          {para.trim()}
                        </p>
                      ))}
                  </div>
                </section>
              )}

              {/* Exam hints */}
              {examHints.length > 0 && (
                <section>
                  <h3 className="font-serif text-lg font-medium mb-4">
                    Exam Hints ({examHints.length})
                  </h3>
                  <div className="space-y-2">
                    {examHints.map((h, i) => (
                      <div
                        key={i}
                        className="bg-bg border border-line rounded-xl p-4 flex items-start gap-3"
                      >
                        <span className="text-gold flex-shrink-0 mt-0.5">●</span>
                        <div className="flex-1">
                          <div dir="auto" className="text-sm text-ink text-start">
                            {h.hint}
                          </div>
                          {h.source && (
                            <div
                              dir="auto"
                              className="text-xs text-ink-mute mt-1 italic text-start"
                            >
                              &ldquo;{h.source}&rdquo;
                            </div>
                          )}
                        </div>
                        <span className="text-[11px] font-mono text-ink-mute flex-shrink-0">
                          {Math.round((h.confidence || 0) * 100)}%
                        </span>
                      </div>
                    ))}
                  </div>
                </section>
              )}

              {/* Key emphasis */}
              {keyEmphasis.length > 0 && (
                <section>
                  <h3 className="font-serif text-lg font-medium mb-4">
                    Key Emphasis
                  </h3>
                  <div className="space-y-2">
                    {keyEmphasis.map((e, i) => (
                      <div
                        key={i}
                        className="bg-bg border border-line rounded-xl p-4"
                      >
                        <div className="flex items-center gap-2 mb-1">
                          <span
                            className={`text-[10px] font-mono uppercase px-2 py-0.5 rounded-full ${emphasisColor(
                              e.emphasisLevel
                            )}`}
                          >
                            {e.emphasisLevel}
                          </span>
                          <span dir="auto" className="text-sm font-medium">
                            {e.topic}
                          </span>
                        </div>
                        {e.quote && (
                          <p
                            dir="auto"
                            className="text-xs text-ink-soft italic mt-1 text-start"
                          >
                            &ldquo;{e.quote}&rdquo;
                          </p>
                        )}
                      </div>
                    ))}
                  </div>
                </section>
              )}

              {/* Chapter mapping */}
              {chapters.length > 0 && (
                <section>
                  <h3 className="font-serif text-lg font-medium mb-4">
                    Chapter Breakdown
                  </h3>
                  <div className="space-y-3">
                    {chapters.map((ch, i) => (
                      <div
                        key={i}
                        className="bg-bg border border-line rounded-2xl p-5"
                      >
                        <h4
                          dir="auto"
                          className="font-medium text-sm mb-2 text-start"
                        >
                          {ch.chapter}
                        </h4>
                        <ul className="space-y-1">
                          {(ch.segments || []).map((seg, j) => (
                            <li
                              key={j}
                              dir="auto"
                              className="text-sm text-ink-soft flex items-start gap-2 text-start"
                            >
                              <span className="text-ink-mute flex-shrink-0">
                                –
                              </span>
                              <span>{seg}</span>
                            </li>
                          ))}
                        </ul>
                      </div>
                    ))}
                  </div>
                </section>
              )}
            </div>
          ) : (
            <div className="text-center text-ink-mute text-sm py-16 px-6">
              Insights aren&apos;t ready yet — this recording is still being
              processed.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
