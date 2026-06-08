"use client";

import { useState, useRef, useEffect, ChangeEvent, DragEvent } from "react";
import { useAuth } from "@/lib/auth-context";
import { useLang } from "@/lib/i18n";

interface Props {
  courseId: string;
  onClose: () => void;
  onSuccess: () => void;
}

const API_URL =
  process.env.NEXT_PUBLIC_BACKEND_URL || "http://127.0.0.1:8000";

const ACCENT = "#b8923a"; // gold — matches the recording color elsewhere
const MAX_SIZE_MB = 300;
const ACCEPTED_EXTS = ["mp3", "wav", "m4a", "mp4", "mov"];
const ACCEPT_ATTR =
  "audio/mpeg,audio/mp3,audio/wav,audio/x-wav,audio/mp4,audio/x-m4a,audio/m4a,video/mp4,video/quicktime,.mp3,.wav,.m4a,.mp4,.mov";

// Per-item processing steps (animated while each recording is analyzed).
const STEPS = [
  { id: "fetch", label: "Fetching recording", duration: 5000 },
  { id: "transcribe", label: "Transcribing (Whisper large-v3)", duration: 14000 },
  { id: "summarize", label: "Summarizing the lecture", duration: 6000 },
  { id: "hints", label: "Extracting exam hints", duration: 4000 },
];

type Phase = "select" | "processing" | "done";
type ItemStatus = "queued" | "processing" | "done" | "failed";

interface QueueItem {
  kind: "file" | "url";
  label: string; // file name or the URL
  file?: File;
  url?: string;
  status: ItemStatus;
  error?: string;
}

export default function UploadAudioModal({ courseId, onClose, onSuccess }: Props) {
  const { user } = useAuth();
  const { t } = useLang();
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [mode, setMode] = useState<"file" | "url">("file");
  const [items, setItems] = useState<QueueItem[]>([]);
  const [urlText, setUrlText] = useState("");
  const [dragActive, setDragActive] = useState(false);
  const [error, setError] = useState("");

  const [phase, setPhase] = useState<Phase>("select");
  const [currentIndex, setCurrentIndex] = useState(0);
  const [currentStep, setCurrentStep] = useState(0);
  const [completed, setCompleted] = useState<Set<string>>(new Set());

  const cancelledRef = useRef(false);
  useEffect(() => {
    return () => {
      cancelledRef.current = true;
    };
  }, []);

  const switchMode = (m: "file" | "url") => {
    setMode(m);
    setError("");
    setItems([]);
  };

  const validateFile = (f: File): string | null => {
    const sizeMB = f.size / 1024 / 1024;
    if (sizeMB > MAX_SIZE_MB)
      return `"${f.name}" is too large (${sizeMB.toFixed(1)}MB). Max is ${MAX_SIZE_MB}MB. For longer videos, use a URL.`;
    const ext = f.name.split(".").pop()?.toLowerCase();
    if (!ext || !ACCEPTED_EXTS.includes(ext))
      return `"${f.name}" is not a supported type (${ACCEPTED_EXTS.join(", ").toUpperCase()}).`;
    return null;
  };

  const addFiles = (incoming: FileList | File[]) => {
    setError("");
    const next: QueueItem[] = [];
    let firstError = "";
    Array.from(incoming).forEach((f) => {
      const err = validateFile(f);
      if (err) {
        if (!firstError) firstError = err;
        return;
      }
      const dup =
        items.some((it) => it.file?.name === f.name && it.file?.size === f.size) ||
        next.some((it) => it.file?.name === f.name && it.file?.size === f.size);
      if (!dup)
        next.push({ kind: "file", label: f.name, file: f, status: "queued" });
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

  const removeFile = (idx: number) =>
    setItems((prev) => prev.filter((_, i) => i !== idx));

  const setItemStatus = (idx: number, status: ItemStatus, err?: string) =>
    setItems((prev) =>
      prev.map((it, i) => (i === idx ? { ...it, status, error: err } : it))
    );

  // Detected (valid http/https) URLs from the textarea, one per line.
  const parsedUrls = urlText
    .split(/[\n\s]+/)
    .map((s) => s.trim())
    .filter((s) => /^https?:\/\/.+/i.test(s));

  const uploadOne = async (item: QueueItem) => {
    if (item.kind === "file") {
      const formData = new FormData();
      formData.append("file", item.file!);
      formData.append("user_id", user!.uid);
      formData.append("course_id", courseId);
      formData.append("title", item.file!.name.replace(/\.[^/.]+$/, ""));
      formData.append("background", "0");
      const res = await fetch(`${API_URL}/api/audio/upload`, {
        method: "POST",
        body: formData,
      });
      if (!res.ok) {
        const e = await res.json().catch(() => null);
        throw new Error(e?.detail || `Upload failed (${res.status})`);
      }
      return;
    }
    // URL
    const res = await fetch(`${API_URL}/api/audio/upload-url`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        user_id: user!.uid,
        course_id: courseId,
        video_url: item.url,
        title: "",
        background: "0",
      }),
    });
    if (!res.ok) {
      const e = await res.json().catch(() => null);
      throw new Error(e?.detail || `Upload failed (${res.status})`);
    }
  };

  const processOne = async (item: QueueItem): Promise<{ ok: boolean; error?: string }> => {
    setCurrentStep(0);
    setCompleted(new Set());

    let finished = false;
    const uploadPromise = uploadOne(item);

    (async () => {
      for (let i = 0; i < STEPS.length; i++) {
        if (cancelledRef.current || finished) return;
        setCurrentStep(i);
        if (i === STEPS.length - 1) return;
        await new Promise((r) => setTimeout(r, STEPS[i].duration));
        if (cancelledRef.current || finished) return;
        setCompleted((prev) => new Set(prev).add(STEPS[i].id));
      }
    })();

    try {
      await uploadPromise;
      finished = true;
      if (!cancelledRef.current) {
        setCompleted(new Set(STEPS.map((s) => s.id)));
        setCurrentStep(STEPS.length);
      }
      return { ok: true };
    } catch (e: any) {
      finished = true;
      return { ok: false, error: e?.message || "Upload failed" };
    }
  };

  const runQueue = async (queue: QueueItem[]) => {
    cancelledRef.current = false;
    setPhase("processing");
    // Process strictly one at a time — never all at once.
    for (let idx = 0; idx < queue.length; idx++) {
      if (cancelledRef.current) return;
      setCurrentIndex(idx);
      setItemStatus(idx, "processing");
      const result = await processOne(queue[idx]);
      if (cancelledRef.current) return;
      if (result.ok) setItemStatus(idx, "done");
      else setItemStatus(idx, "failed", result.error);
    }
    if (cancelledRef.current) return;
    setPhase("done");
    setTimeout(() => {
      if (cancelledRef.current) return;
      onSuccess();
      onClose();
    }, 1600);
  };

  const startFiles = () => {
    if (!user) return;
    if (items.length === 0) {
      setError("Please add at least one recording.");
      return;
    }
    setError("");
    runQueue(items);
  };

  const startUrls = () => {
    if (!user) return;
    if (parsedUrls.length === 0) {
      setError("Please paste at least one valid video URL (http/https).");
      return;
    }
    setError("");
    const queue: QueueItem[] = parsedUrls.map((u) => ({
      kind: "url",
      label: u,
      url: u,
      status: "queued",
    }));
    setItems(queue);
    runQueue(queue);
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

  const statusBadge = (s: ItemStatus) => {
    if (s === "done") return <span className="text-sage">● {t("Done")}</span>;
    if (s === "failed") return <span className="text-accent">● {t("Failed")}</span>;
    if (s === "processing")
      return (
        <span style={{ color: ACCENT }} className="flex items-center gap-1.5">
          <span
            className="w-3 h-3 border-2 rounded-full animate-spin"
            style={{ borderColor: `${ACCENT}40`, borderTopColor: ACCENT }}
          />
          {t("Analyzing…")}
        </span>
      );
    return <span className="text-ink-mute">● {t("Queued")}</span>;
  };

  return (
    <div
      className="fixed inset-0 bg-ink/50 backdrop-blur-md z-[100] flex items-center justify-center p-6 animate-fade-in"
      style={{ ["--accent" as any]: ACCENT }}
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
              {t("Upload lecture recordings")}
            </h2>
            <p className="text-ink-soft text-sm mb-6">
              {t(
                "Audio or video. We'll transcribe each one, summarize what the professor covered, and extract exam hints."
              )}
            </p>

            <div className="flex gap-2 mb-6 p-1 bg-bg-alt rounded-full">
              <button
                type="button"
                onClick={() => switchMode("file")}
                className={`flex-1 py-2 rounded-full text-sm font-medium transition ${
                  mode === "file" ? "bg-ink text-paper" : "text-ink-soft hover:text-ink"
                }`}
              >
                {t("Upload files")}
              </button>
              <button
                type="button"
                onClick={() => switchMode("url")}
                className={`flex-1 py-2 rounded-full text-sm font-medium transition ${
                  mode === "url" ? "bg-ink text-paper" : "text-ink-soft hover:text-ink"
                }`}
              >
                {t("Paste video URLs")}
              </button>
            </div>

            {error && (
              <div
                className="text-sm rounded-xl p-3 mb-5"
                style={{ backgroundColor: `${ACCENT}1a`, color: ACCENT }}
              >
                {error}
              </div>
            )}

            {mode === "url" ? (
              <>
                <label className="block text-sm font-medium text-ink-soft mb-2">
                  {t("Video URLs")} <span className="text-accent">*</span>{" "}
                  <span className="text-ink-mute font-normal">{t("(one per line)")}</span>
                </label>
                <textarea
                  value={urlText}
                  onChange={(e) => {
                    setUrlText(e.target.value);
                    setError("");
                  }}
                  rows={5}
                  placeholder={"https://… (YouTube, Vimeo, or a direct video link)\nhttps://…\nhttps://…"}
                  className="w-full px-4 py-3 border border-line rounded-xl bg-bg focus:outline-none focus:border-accent transition mb-2 font-mono text-xs resize-y"
                />
                <p className="text-xs text-ink-mute mb-6">
                  {parsedUrls.length > 0
                    ? `${parsedUrls.length} ${t("URLs detected · processed one at a time.")}`
                    : t("We fetch each video, extract the audio to MP3, and transcribe it.")}
                </p>
                <button
                  type="button"
                  onClick={startUrls}
                  disabled={parsedUrls.length === 0}
                  className="w-full bg-[var(--accent)] text-paper py-3.5 rounded-full font-medium hover:bg-ink transition disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {parsedUrls.length > 0
                    ? `${t("Fetch & Analyze")} (${parsedUrls.length}) →`
                    : `${t("Fetch & Analyze")} →`}
                </button>
              </>
            ) : (
              <>
                <div
                  onDragEnter={handleDrag}
                  onDragOver={handleDrag}
                  onDragLeave={handleDrag}
                  onDrop={handleDrop}
                  onClick={() => fileInputRef.current?.click()}
                  className="border-2 border-dashed rounded-2xl p-7 text-center cursor-pointer transition mb-5"
                  style={{
                    borderColor: dragActive ? ACCENT : undefined,
                    backgroundColor: dragActive ? `${ACCENT}0d` : undefined,
                  }}
                >
                  <div className="text-4xl mb-3 opacity-50">
                    {dragActive ? "📥" : "🎙️"}
                  </div>
                  <div className="font-serif text-lg mb-1">
                    {dragActive
                      ? t("Drop your recordings here")
                      : t("Drop recordings or click to browse")}
                  </div>
                  <div className="text-xs text-ink-mute">
                    {ACCEPTED_EXTS.join(", ").toUpperCase()} · {MAX_SIZE_MB}MB ·{" "}
                    {t("select multiple")}
                  </div>
                  <input
                    ref={fileInputRef}
                    type="file"
                    multiple
                    accept={ACCEPT_ATTR}
                    onChange={handleFileChange}
                    className="hidden"
                  />
                </div>

                {items.length > 0 && (
                  <div className="border border-line rounded-2xl divide-y divide-line mb-5 max-h-56 overflow-y-auto">
                    {items.map((it, idx) => (
                      <div
                        key={`${it.label}-${idx}`}
                        className="flex items-center gap-3 px-4 py-3"
                      >
                        <div
                          className="w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0"
                          style={{ backgroundColor: `${ACCENT}1a` }}
                        >
                          🎙️
                        </div>
                        <div className="flex-1 min-w-0">
                          <div className="text-sm font-medium truncate">
                            {it.label}
                          </div>
                          {it.file && (
                            <div className="text-xs text-ink-mute">
                              {formatFileSize(it.file.size)}
                            </div>
                          )}
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
                  onClick={startFiles}
                  disabled={items.length === 0}
                  className="w-full bg-[var(--accent)] text-paper py-3.5 rounded-full font-medium hover:bg-ink transition disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {items.length > 0
                    ? `${t("Upload & Analyze")} (${items.length}) →`
                    : `${t("Upload & Analyze")} →`}
                </button>

                <p className="text-xs text-ink-mute text-center pt-3">
                  {t("Recordings are analyzed one at a time — about 1–3 minutes each.")}
                </p>
              </>
            )}
          </>
        )}

        {/* ============ PROCESSING / DONE PHASE ============ */}
        {(phase === "processing" || phase === "done") && (
          <div className="text-center py-1">
            <div className="w-24 h-24 mx-auto mb-6 relative">
              <div
                className={`w-24 h-24 border-[3px] rounded-full ${
                  isDone ? "" : "animate-spin-slow"
                }`}
                style={
                  isDone
                    ? { borderColor: "#6b7d5b" }
                    : { borderColor: "#e9e4da", borderTopColor: ACCENT }
                }
              />
              <div
                className="absolute inset-0 flex items-center justify-center font-mono font-semibold text-2xl"
                style={{ color: isDone ? "#6b7d5b" : ACCENT }}
              >
                {finishedCount}/{total}
              </div>
            </div>

            <h2 className="font-serif text-2xl md:text-3xl font-medium mb-2 tracking-tight">
              {isDone
                ? failedCount > 0
                  ? t("Finished with some issues")
                  : t("All recordings analyzed!")
                : t("Mudaris is analyzing…")}
            </h2>
            <p className="text-ink-soft text-sm mb-2 px-2">
              <span className="font-medium text-ink">{doneCount}</span> of{" "}
              <span className="font-medium text-ink">{total}</span> done
              {failedCount > 0 && (
                <span className="text-accent"> · {failedCount} failed</span>
              )}
            </p>
            {!isDone && items[currentIndex] && (
              <p className="text-ink-mute text-xs mb-6 px-2 truncate">
                {t("Now")}: &ldquo;{items[currentIndex].label}&rdquo; ({currentIndex + 1}/
                {total})
              </p>
            )}
            {isDone && <div className="mb-4" />}

            {!isDone && (
              <div className="bg-bg border border-line rounded-2xl p-4 text-left mb-5">
                {STEPS.map((step, i) => {
                  const stepDone = completed.has(step.id);
                  const isActive = i === currentStep && !stepDone;
                  const isPending = i > currentStep;
                  return (
                    <div
                      key={step.id}
                      className={`flex items-center gap-3 py-2 ${
                        i < STEPS.length - 1 ? "border-b border-line" : ""
                      } ${isPending ? "opacity-40" : "opacity-100"}`}
                    >
                      <div
                        className="w-7 h-7 rounded-full flex items-center justify-center font-mono text-xs font-semibold flex-shrink-0 transition-all"
                        style={
                          stepDone
                            ? { backgroundColor: "#6b7d5b", color: "#faf7f2" }
                            : isActive
                            ? { backgroundColor: ACCENT, color: "#faf7f2" }
                            : { backgroundColor: "#e9e4da", color: "#6b6256" }
                        }
                      >
                        {stepDone ? "✓" : i + 1}
                      </div>
                      <div className="flex-1 text-sm font-medium">{step.label}</div>
                      <div className="font-mono text-[11px] text-ink-mute flex-shrink-0">
                        {stepDone ? "done" : isActive ? "in progress…" : "queued"}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}

            <div className="border border-line rounded-2xl divide-y divide-line text-left max-h-48 overflow-y-auto">
              {items.map((it, idx) => (
                <div
                  key={`${it.label}-${idx}`}
                  className="flex items-center gap-3 px-4 py-2.5"
                >
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-medium truncate">{it.label}</div>
                    {it.status === "failed" && it.error && (
                      <div className="text-xs text-accent truncate">{it.error}</div>
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
                : t("One recording at a time — please keep this open.")}
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
