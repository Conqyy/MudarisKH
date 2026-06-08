"use client";

import {
  useState,
  useRef,
  useEffect,
  ChangeEvent,
  DragEvent,
} from "react";
import { useAuth } from "@/lib/auth-context";
import { useLang } from "@/lib/i18n";

const API_URL =
  process.env.NEXT_PUBLIC_BACKEND_URL || "http://127.0.0.1:8000";

const MAX_SIZE_MB = 50;

export interface Step {
  id: string;
  label: string;
  duration: number;
}

interface Props {
  courseId: string;
  onClose: () => void;
  onSuccess: () => void;
  /** Backend upload endpoint, e.g. "/api/documents/upload". */
  endpoint: string;
  /** Accent color as a 6-digit hex, e.g. "#c8472f". */
  accent: string;
  /** Emoji shown on the dropzone / file rows. */
  icon: string;
  /** Allowed extensions (lowercase, no dot), e.g. ["pdf","pptx","docx"]. */
  acceptExts: string[];
  /** `accept` attribute for the file input. */
  acceptAttr: string;
  heading: string;
  subtitle: string;
  /** Singular noun, e.g. "document", "past exam", "tutorial". */
  fileNoun: string;
  /** Per-file processing steps (animated while each file is analyzed). */
  steps: Step[];
  footerNote?: string;
}

type Phase = "select" | "processing" | "done";
type FileStatus = "queued" | "processing" | "done" | "failed";

interface FileItem {
  file: File;
  status: FileStatus;
  error?: string;
}

export default function MultiUploadModal({
  courseId,
  onClose,
  onSuccess,
  endpoint,
  accent,
  icon,
  acceptExts,
  acceptAttr,
  heading,
  subtitle,
  fileNoun,
  steps,
  footerNote,
}: Props) {
  const { user } = useAuth();
  const { t } = useLang();
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [items, setItems] = useState<FileItem[]>([]);
  const [dragActive, setDragActive] = useState(false);
  const [error, setError] = useState("");

  const [phase, setPhase] = useState<Phase>("select");
  const [currentIndex, setCurrentIndex] = useState(0);

  // Per-current-file step animation
  const [currentStep, setCurrentStep] = useState(0);
  const [completed, setCompleted] = useState<Set<string>>(new Set());

  const cancelledRef = useRef(false);

  useEffect(() => {
    return () => {
      cancelledRef.current = true;
    };
  }, []);

  const validateFile = (f: File): string | null => {
    const sizeMB = f.size / 1024 / 1024;
    if (sizeMB > MAX_SIZE_MB)
      return `"${f.name}" is too large (${sizeMB.toFixed(1)}MB). Max is ${MAX_SIZE_MB}MB.`;
    const ext = f.name.split(".").pop()?.toLowerCase();
    if (!ext || !acceptExts.includes(ext))
      return `"${f.name}" is not a supported type (${acceptExts
        .join(", ")
        .toUpperCase()}).`;
    return null;
  };

  const addFiles = (incoming: FileList | File[]) => {
    setError("");
    const next: FileItem[] = [];
    let firstError = "";
    Array.from(incoming).forEach((f) => {
      const err = validateFile(f);
      if (err) {
        if (!firstError) firstError = err;
        return;
      }
      // De-dupe by name + size
      const dup =
        items.some((it) => it.file.name === f.name && it.file.size === f.size) ||
        next.some((it) => it.file.name === f.name && it.file.size === f.size);
      if (!dup) next.push({ file: f, status: "queued" });
    });
    if (firstError) setError(firstError);
    if (next.length) setItems((prev) => [...prev, ...next]);
  };

  const handleFileChange = (e: ChangeEvent<HTMLInputElement>) => {
    if (e.target.files?.length) addFiles(e.target.files);
    if (fileInputRef.current) fileInputRef.current.value = "";
  };

  const handleDrag = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === "dragenter" || e.type === "dragover") setDragActive(true);
    else if (e.type === "dragleave") setDragActive(false);
  };

  const handleDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);
    if (e.dataTransfer.files?.length) addFiles(e.dataTransfer.files);
  };

  const removeFile = (idx: number) => {
    setItems((prev) => prev.filter((_, i) => i !== idx));
  };

  const setItemStatus = (idx: number, status: FileStatus, err?: string) => {
    setItems((prev) =>
      prev.map((it, i) => (i === idx ? { ...it, status, error: err } : it))
    );
  };

  const uploadOne = async (file: File) => {
    const formData = new FormData();
    formData.append("file", file);
    formData.append("user_id", user!.uid);
    formData.append("course_id", courseId);
    formData.append("title", file.name.replace(/\.[^/.]+$/, ""));

    const res = await fetch(`${API_URL}${endpoint}`, {
      method: "POST",
      body: formData,
    });
    if (!res.ok) {
      const e = await res.json().catch(() => null);
      throw new Error(e?.detail || `Upload failed (${res.status})`);
    }
    return res;
  };

  // Process ONE file: animate the steps while the real request runs, resolve
  // when the request finishes. Returns whether it succeeded.
  const processOne = async (file: File): Promise<{ ok: boolean; error?: string }> => {
    setCurrentStep(0);
    setCompleted(new Set());

    let finished = false;
    const uploadPromise = uploadOne(file);

    // Cosmetic step animation (all but the last step, which holds until done)
    (async () => {
      for (let i = 0; i < steps.length; i++) {
        if (cancelledRef.current || finished) return;
        setCurrentStep(i);
        if (i === steps.length - 1) return;
        await new Promise((r) => setTimeout(r, steps[i].duration));
        if (cancelledRef.current || finished) return;
        setCompleted((prev) => new Set(prev).add(steps[i].id));
      }
    })();

    try {
      await uploadPromise;
      finished = true;
      if (!cancelledRef.current) {
        setCompleted(new Set(steps.map((s) => s.id)));
        setCurrentStep(steps.length);
      }
      return { ok: true };
    } catch (e: any) {
      finished = true;
      return { ok: false, error: e?.message || "Upload failed" };
    }
  };

  const startProcessing = async () => {
    if (!user) return;
    if (items.length === 0) {
      setError(`Please add at least one ${fileNoun}.`);
      return;
    }
    setError("");
    cancelledRef.current = false;
    setPhase("processing");

    // Process strictly one at a time — never all at once.
    for (let idx = 0; idx < items.length; idx++) {
      if (cancelledRef.current) return;
      setCurrentIndex(idx);
      setItemStatus(idx, "processing");

      const result = await processOne(items[idx].file);
      if (cancelledRef.current) return;

      if (result.ok) setItemStatus(idx, "done");
      else setItemStatus(idx, "failed", result.error);
    }

    if (cancelledRef.current) return;
    setPhase("done");
    // Give the user a beat to read the final counter, then refresh + close.
    setTimeout(() => {
      if (cancelledRef.current) return;
      onSuccess();
      onClose();
    }, 1600);
  };

  const formatFileSize = (bytes: number) => {
    const mb = bytes / 1024 / 1024;
    if (mb < 1) return `${(bytes / 1024).toFixed(0)} KB`;
    return `${mb.toFixed(1)} MB`;
  };

  const doneCount = items.filter((it) => it.status === "done").length;
  const failedCount = items.filter((it) => it.status === "failed").length;
  const finishedCount = doneCount + failedCount;
  const total = items.length;

  const isBusy = phase === "processing";
  const isDone = phase === "done";

  const statusBadge = (s: FileStatus) => {
    if (s === "done") return <span className="text-sage">● {t("Done")}</span>;
    if (s === "failed") return <span className="text-accent">● {t("Failed")}</span>;
    if (s === "processing")
      return (
        <span style={{ color: accent }} className="flex items-center gap-1.5">
          <span
            className="w-3 h-3 border-2 rounded-full animate-spin"
            style={{ borderColor: `${accent}40`, borderTopColor: accent }}
          />
          {t("Analyzing…")}
        </span>
      );
    return <span className="text-ink-mute">● {t("Queued")}</span>;
  };

  return (
    <div
      className="fixed inset-0 bg-ink/50 backdrop-blur-md z-[100] flex items-center justify-center p-6 animate-fade-in"
      style={{ ["--accent" as any]: accent }}
      onClick={() => {
        if (phase === "select") onClose();
      }}
    >
      <div
        className="bg-paper rounded-3xl p-8 md:p-10 max-w-lg w-full shadow-lift relative max-h-[90vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <button
          onClick={onClose}
          disabled={isBusy}
          className="absolute top-5 right-5 text-2xl text-ink-soft hover:text-ink leading-none w-8 h-8 flex items-center justify-center rounded-full hover:bg-bg-alt transition disabled:opacity-30 disabled:cursor-not-allowed"
        >
          &times;
        </button>

        {/* ============ SELECT PHASE ============ */}
        {phase === "select" && (
          <>
            <h2 className="font-serif text-3xl font-medium mb-2 tracking-tight">
              {t(heading)}
            </h2>
            <p className="text-ink-soft text-sm mb-7">{t(subtitle)}</p>

            {error && (
              <div
                className="text-sm rounded-xl p-3 mb-5"
                style={{ backgroundColor: `${accent}1a`, color: accent }}
              >
                {error}
              </div>
            )}

            <div
              onDragEnter={handleDrag}
              onDragOver={handleDrag}
              onDragLeave={handleDrag}
              onDrop={handleDrop}
              onClick={() => fileInputRef.current?.click()}
              className="border-2 border-dashed rounded-2xl p-7 text-center cursor-pointer transition mb-5"
              style={{
                borderColor: dragActive ? accent : undefined,
                backgroundColor: dragActive ? `${accent}0d` : undefined,
              }}
            >
              <div className="text-4xl mb-3 opacity-50">
                {dragActive ? "📥" : icon}
              </div>
              <div className="font-serif text-lg mb-1">
                {dragActive
                  ? t("Drop your files here")
                  : t("Drop files or click to browse")}
              </div>
              <div className="text-xs text-ink-mute">
                {acceptExts.join(", ").toUpperCase()} · {MAX_SIZE_MB}MB ·{" "}
                {t("select multiple")}
              </div>

              <input
                ref={fileInputRef}
                type="file"
                multiple
                accept={acceptAttr}
                onChange={handleFileChange}
                className="hidden"
              />
            </div>

            {items.length > 0 && (
              <div className="border border-line rounded-2xl divide-y divide-line mb-5 max-h-56 overflow-y-auto">
                {items.map((it, idx) => (
                  <div
                    key={`${it.file.name}-${idx}`}
                    className="flex items-center gap-3 px-4 py-3"
                  >
                    <div
                      className="w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0"
                      style={{ backgroundColor: `${accent}1a` }}
                    >
                      {icon}
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="text-sm font-medium truncate">
                        {it.file.name}
                      </div>
                      <div className="text-xs text-ink-mute">
                        {formatFileSize(it.file.size)}
                      </div>
                    </div>
                    <button
                      type="button"
                      onClick={() => removeFile(idx)}
                      className="text-ink-mute hover:text-accent text-lg leading-none px-1"
                      aria-label="Remove"
                    >
                      &times;
                    </button>
                  </div>
                ))}
              </div>
            )}

            <button
              type="button"
              onClick={startProcessing}
              disabled={items.length === 0}
              className="w-full bg-[var(--accent)] text-paper py-3.5 rounded-full font-medium hover:bg-ink transition disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {items.length > 0
                ? `${t("Upload & Analyze")} (${items.length}) →`
                : `${t("Upload & Analyze")} →`}
            </button>

            <p className="text-xs text-ink-mute text-center pt-3">
              {t(
                footerNote ||
                  "Files are analyzed one at a time — about 15–30 seconds each."
              )}
            </p>
          </>
        )}

        {/* ============ PROCESSING / DONE PHASE ============ */}
        {(phase === "processing" || phase === "done") && (
          <div className="text-center py-1">
            {/* Counter ring */}
            <div className="w-24 h-24 mx-auto mb-6 relative">
              <div
                className={`w-24 h-24 border-[3px] rounded-full ${
                  isDone ? "" : "animate-spin-slow"
                }`}
                style={
                  isDone
                    ? { borderColor: "#6b7d5b" }
                    : {
                        borderColor: "#e9e4da",
                        borderTopColor: accent,
                      }
                }
              />
              <div
                className="absolute inset-0 flex items-center justify-center font-mono font-semibold text-2xl"
                style={{ color: isDone ? "#6b7d5b" : accent }}
              >
                {finishedCount}/{total}
              </div>
            </div>

            <h2 className="font-serif text-2xl md:text-3xl font-medium mb-2 tracking-tight">
              {isDone
                ? failedCount > 0
                  ? t("Finished with some issues")
                  : t("All files analyzed!")
                : t("Mudaris is analyzing…")}
            </h2>
            <p className="text-ink-soft text-sm mb-2 px-2">
              <span className="font-medium text-ink">{doneCount}</span> /{" "}
              <span className="font-medium text-ink">{total}</span> {t("done")}
              {failedCount > 0 && (
                <span className="text-accent"> · {failedCount} {t("failed")}</span>
              )}
            </p>
            {!isDone && items[currentIndex] && (
              <p className="text-ink-mute text-xs mb-6 px-2 truncate">
                {t("Now")}: &ldquo;{items[currentIndex].file.name}&rdquo; (
                {currentIndex + 1}/{total})
              </p>
            )}
            {isDone && <div className="mb-4" />}

            {/* Current-file step pipeline */}
            {!isDone && (
              <div className="bg-bg border border-line rounded-2xl p-4 text-left mb-5">
                {steps.map((step, i) => {
                  const stepDone = completed.has(step.id);
                  const isActive = i === currentStep && !stepDone;
                  const isPending = i > currentStep;
                  return (
                    <div
                      key={step.id}
                      className={`flex items-center gap-3 py-2 ${
                        i < steps.length - 1 ? "border-b border-line" : ""
                      } ${isPending ? "opacity-40" : "opacity-100"}`}
                    >
                      <div
                        className="w-7 h-7 rounded-full flex items-center justify-center font-mono text-xs font-semibold flex-shrink-0 transition-all"
                        style={
                          stepDone
                            ? { backgroundColor: "#6b7d5b", color: "#faf7f2" }
                            : isActive
                            ? { backgroundColor: accent, color: "#faf7f2" }
                            : { backgroundColor: "#e9e4da", color: "#6b6256" }
                        }
                      >
                        {stepDone ? "✓" : i + 1}
                      </div>
                      <div className="flex-1 text-sm font-medium">
                        {t(step.label)}
                      </div>
                      <div className="font-mono text-[11px] text-ink-mute flex-shrink-0">
                        {stepDone
                          ? t("done")
                          : isActive
                          ? t("in progress…")
                          : t("queued")}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}

            {/* File list with statuses */}
            <div className="border border-line rounded-2xl divide-y divide-line text-left max-h-48 overflow-y-auto">
              {items.map((it, idx) => (
                <div
                  key={`${it.file.name}-${idx}`}
                  className="flex items-center gap-3 px-4 py-2.5"
                >
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-medium truncate">
                      {it.file.name}
                    </div>
                    {it.status === "failed" && it.error && (
                      <div className="text-xs text-accent truncate">
                        {it.error}
                      </div>
                    )}
                  </div>
                  <div className="text-xs font-medium flex-shrink-0">
                    {statusBadge(it.status)}
                  </div>
                </div>
              ))}
            </div>

            <p className="text-xs text-ink-mute mt-5 font-mono">
              {isDone
                ? t("Done — closing…")
                : t("One file at a time — please keep this open.")}
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
