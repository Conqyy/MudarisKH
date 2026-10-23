"use client";

import Icon from "@/components/Icon";

import { useDialog } from "@/lib/use-dialog";

import { useEffect, useState } from "react";
import { AudioRecording } from "@/lib/firestore-helpers";
import BookmarkButton from "@/components/BookmarkButton";
import { useTrackRecent } from "@/lib/activity";
import { fetchObjectUrl } from "@/lib/api";
import { getLegacySupportingAnalysis } from "@/lib/supporting-materials";
import SupportingAnalysisReport from "@/components/SupportingAnalysisReport";
import { useAuth } from "@/lib/auth-context";
import { useLang } from "@/lib/i18n";

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
  const dialogRef = useDialog(onClose);
  const { user } = useAuth();
  const { t } = useLang();
  const [legacy, setLegacy] = useState<{ insights?: AudioRecording["insights"]; transcript?: string } | null>(null);
  const [legacyError, setLegacyError] = useState("");
  const isLegacy = recording.legacy === true;
  const kind = recording.sourceType === "notes" ? "notes" : "audio";
  useEffect(() => {
    if (!isLegacy || !recording.courseId || !user?.uid) return;
    const controller = new AbortController();
    setLegacy(null);
    setLegacyError("");
    getLegacySupportingAnalysis(kind, recording.id, recording.courseId, controller.signal).then(value => {
      if (!controller.signal.aborted) setLegacy({ insights: value.insights as AudioRecording["insights"], transcript: typeof value.transcript === "string" ? value.transcript : undefined });
    }).catch(error => { if (!controller.signal.aborted) setLegacyError((error as Error).message); });
    return () => controller.abort();
  }, [isLegacy, kind, recording.courseId, recording.id, user?.uid]);
  const insights = isLegacy ? legacy?.insights : recording.insights;

  // The analysis endpoint needs an Authorization header, which <a href> cannot
  // send, so fetch the bytes on click and hand the browser a blob instead.
  const [pdfBusy, setPdfBusy] = useState(false);
  const downloadPdf = async () => {
    setPdfBusy(true);
    try {
      const url = await fetchObjectUrl(`${API_URL}/api/audio/${recording.id}/pdf`);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${recording.title || "recording"}.pdf`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      alert("Could not download the analysis PDF.");
    } finally {
      setPdfBusy(false);
    }
  };

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
    <div ref={dialogRef} role="dialog" aria-modal="true" aria-label={t("Audio recording")} tabIndex={-1} className="material-viewer">
      <div
        className="material-viewer-backdrop"
        onClick={onClose}
      />

      <div className="material-viewer-panel">
        {/* Header */}
        <div className="material-viewer-header">
          <button
            onClick={onClose}
          aria-label={t("Close dialog")}
            className="icon-button"
          ><Icon name="close" /></button>
          <div className="material-viewer-title">
            <h2 dir="auto" className="font-sans text-xl font-semibold break-words flex items-center gap-2">
              <Icon name="audio" size={22} className="shrink-0" /> {recording.title}
            </h2>
            <div className="text-xs text-ink-soft tabular-nums mt-1 flex flex-wrap items-center gap-x-3 gap-y-1">
              <span>{new Date(recording.uploadedAt).toLocaleDateString()}</span>
              {examHints.length > 0 && (
                <span className="text-gold">{examHints.length} {t("exam hints")}</span>
              )}
            </div>
          </div>
          {insights && (
            <button
              onClick={downloadPdf}
              disabled={pdfBusy}
              className="ui-button secondary"
              title={t("Download analysis & transcript as PDF")}
            >
              <Icon name="download" size={17} /> {pdfBusy ? t("Preparing…") : "PDF"}
            </button>
          )}
          <BookmarkButton item={bookmarkItem} size="sm" />
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto">
          {recording.reportRevision && <div className="p-6"><SupportingAnalysisReport kind={kind} materialId={recording.id} courseId={recording.courseId} /></div>}
          {isLegacy && <p className="px-6 pt-4 text-sm text-gold">{t("Legacy analysis is unverified.")}</p>}
          {recording.sourceType === "notes" && <p className="px-6 pt-4 text-sm text-ink-soft">{t("Student-typed notes")}</p>}
          {legacyError && <p className="px-6 pt-4 text-sm text-accent" role="alert">{legacyError}</p>}
          {legacy?.transcript && <section className="px-6 pt-4"><h3 className="section-heading mb-4">{t(recording.sourceType === "notes" ? "Student-typed notes" : "Transcript")}</h3><pre dir="auto" className="mt-3 whitespace-pre-wrap font-sans text-sm text-ink-soft">{legacy.transcript}</pre></section>}
          {insights ? (
            <div className="material-reader p-5 md:p-7 space-y-8">
                  {/* Legacy reading stays clearly labeled as unverified. */}
              {insights.summary && (
                <section>
                  <h3 className="section-heading mb-4">{t("Lecture Summary")}</h3>
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
                  <h3 className="section-heading mb-4">
                    {t("Exam Hints")} ({examHints.length})
                  </h3>
                  <div className="space-y-2">
                    {examHints.map((h, i) => (
                      <div
                        key={i}
                        className="bg-bg border border-line rounded-xl p-4 flex items-start gap-3"
                      >
                        <span className="text-gold flex-shrink-0 mt-0.5"><Icon name="info" size={16} /></span>
                        <div className="flex-1">
                          <div dir="auto" className="text-sm text-ink text-start">
                            {h.hint}
                          </div>
                          {h.source && recording.sourceType !== "notes" && (
                            <div
                              dir="auto"
                              className="text-xs text-ink-mute mt-1 italic text-start"
                            >
                              &ldquo;{h.source}&rdquo;
                            </div>
                          )}
                        </div>
                        <span className="text-xs tabular-nums text-ink-mute flex-shrink-0">
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
                  <h3 className="section-heading mb-4">{t("Key Emphasis")}</h3>
                  <div className="space-y-2">
                    {keyEmphasis.map((e, i) => (
                      <div
                        key={i}
                        className="bg-bg border border-line rounded-xl p-4"
                      >
                        <div className="flex items-center gap-2 mb-1">
                          <span
                            className={`text-xs tabular-nums uppercase px-2 py-0.5 rounded-full ${emphasisColor(
                              e.emphasisLevel
                            )}`}
                          >
                            {e.emphasisLevel}
                          </span>
                          <span dir="auto" className="text-sm font-medium">
                            {e.topic}
                          </span>
                        </div>
                        {e.quote && recording.sourceType !== "notes" && (
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
                  <h3 className="section-heading mb-4">{t("Chapter Breakdown")}</h3>
                  <div className="space-y-3">
                    {chapters.map((ch, i) => (
                      <div
                        key={i}
                        className="bg-bg-alt rounded-2xl p-5"
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
          ) : !recording.reportRevision && (
            <div className="text-center text-ink-mute text-sm py-16 px-6">
              {t(isLegacy ? "Loading saved analysis…" : "Analysis is still processing.")}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
