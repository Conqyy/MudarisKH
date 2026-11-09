"use client";

import Icon from "@/components/Icon";
import { useOverlayMotion } from "@/lib/use-overlay-motion";

import { useState, useRef, useEffect, ChangeEvent, DragEvent } from "react";
import { useAuth } from "@/lib/auth-context";
import { useLang } from "@/lib/i18n";

import { apiFetch } from "@/lib/api";
import { getSupportingStatus, MaterialKind } from "@/lib/supporting-materials";
interface Props {
  courseId: string;
  onClose: () => void;
  onSuccess: () => void;
}

const API_URL =
  process.env.NEXT_PUBLIC_BACKEND_URL || "http://127.0.0.1:8000";

const MAX_SIZE_MB = 300;
const ACCEPTED_EXTS = ["mp3", "wav", "m4a", "mp4", "mov"];
const ACCEPT_ATTR =
  "audio/mpeg,audio/mp3,audio/wav,audio/x-wav,audio/mp4,audio/x-m4a,audio/m4a,video/mp4,video/quicktime,.mp3,.wav,.m4a,.mp4,.mov";

// These steps describe the durable job; the course page shows live progress.
const STEPS = [
  { id: "upload", label: "Uploading recording", duration: 0 },
  { id: "extract", label: "Extracting source content…", duration: 0 },
  { id: "align", label: "Comparing with lectures…", duration: 0 },
];

// Typed notes skip transcription — same analysis AI, different steps.
const NOTE_STEPS = [
  { id: "upload", label: "Saving your notes", duration: 0 },
  { id: "extract", label: "Extracting source content…", duration: 0 },
  { id: "align", label: "Comparing with lectures…", duration: 0 },
];

type Phase = "select" | "processing" | "done";
type ItemStatus = "queued" | "processing" | "accepted" | "done" | "failed";

interface QueueItem {
  kind: "file" | "url" | "notes";
  label: string; // file name, the URL, or the notes title
  file?: File;
  url?: string;
  notesText?: string;
  notesTitle?: string;
  status: ItemStatus;
  error?: string;
}

const stepsFor = (item?: QueueItem) =>
  item?.kind === "notes" ? NOTE_STEPS : STEPS;

export default function UploadAudioModal({ courseId, onClose, onSuccess }: Props) {
  const { user } = useAuth();
  const { t } = useLang();
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [mode, setMode] = useState<"file" | "url" | "notes">("file");
  const [items, setItems] = useState<QueueItem[]>([]);
  const [urlText, setUrlText] = useState("");
  const [notesText, setNotesText] = useState("");
  const [notesTitle, setNotesTitle] = useState("");
  const [dragActive, setDragActive] = useState(false);
  const [error, setError] = useState("");

  const [phase, setPhase] = useState<Phase>("select");
  const { ref: dialogRef, close: closeDialog } = useOverlayMotion(onClose, { canClose: phase !== "processing" });
  const [currentIndex, setCurrentIndex] = useState(0);
  const [currentStep, setCurrentStep] = useState(0);
  const [completed, setCompleted] = useState<Set<string>>(new Set());

  const cancelledRef = useRef(false);
  const requestRef = useRef<AbortController | null>(null);
  const identity = `${user?.uid || ""}:${courseId}`;
  const identityRef = useRef(identity);
  identityRef.current = identity;
  useEffect(() => {
    cancelledRef.current = false;
    return () => {
      cancelledRef.current = true;
      requestRef.current?.abort();
    };
  }, [identity]);

  const switchMode = (m: "file" | "url" | "notes") => {
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

  const uploadOne = async (item: QueueItem, signal: AbortSignal) => {
    if (item.kind === "file") {
      const formData = new FormData();
      formData.append("file", item.file!);
      formData.append("user_id", user!.uid);
      formData.append("course_id", courseId);
      formData.append("title", item.file!.name.replace(/\.[^/.]+$/, ""));
      const res = await apiFetch(`${API_URL}/api/audio/upload`, {
        method: "POST",
        body: formData,
        signal,
      });
      if (!res.ok) {
        const e = await res.json().catch(() => null);
        throw new Error(e?.detail || `Upload failed (${res.status})`);
      }
      return res.json();
    }
    if (item.kind === "notes") {
      const res = await apiFetch(`${API_URL}/api/audio/upload-notes`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          user_id: user!.uid,
          course_id: courseId,
          notes: item.notesText,
          title: item.notesTitle || "",
        }),
        signal,
      });
      if (!res.ok) {
        const e = await res.json().catch(() => null);
        throw new Error(e?.detail || `Analysis failed (${res.status})`);
      }
      return res.json();
    }
    // URL
    const res = await apiFetch(`${API_URL}/api/audio/upload-url`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        user_id: user!.uid,
        course_id: courseId,
        video_url: item.url,
        title: "",
      }),
      signal,
    });
    if (!res.ok) {
      const e = await res.json().catch(() => null);
      throw new Error(e?.detail || `Upload failed (${res.status})`);
    }
    return res.json();
  };

  const processOne = async (item: QueueItem): Promise<{ ok: boolean; error?: string }> => {
    const steps = stepsFor(item);
    setCurrentStep(0);
    setCompleted(new Set());

    const signal = requestRef.current!.signal;
    try {
      const result = await uploadOne(item, signal);
      signal.throwIfAborted();
      const kind: MaterialKind = item.kind === "notes" ? "notes" : "audio";
      if (!result || typeof result.recording_id !== "string" || result.materialId !== result.recording_id || result.kind !== kind || typeof result.jobId !== "string") throw new Error(t("Upload did not return a material identity."));
      const status = await getSupportingStatus(kind, result.recording_id, signal, courseId);
      if (status.jobId !== result.jobId) throw new Error(t("Supporting analysis changed. Check the course page."));
      signal.throwIfAborted();
      if (!cancelledRef.current) { setCompleted(new Set([steps[0].id])); setCurrentStep(status.stage === "aligning" ? 2 : status.stage === "extracting" ? 1 : 0); }
      return { ok: true };
    } catch (e: any) {
      return { ok: false, error: e?.message || "Upload failed" };
    }
  };

  const runQueue = async (queue: QueueItem[]) => {
    cancelledRef.current = false;
    requestRef.current?.abort();
    requestRef.current = new AbortController();
    const startedIdentity = identity;
    const stale = () => cancelledRef.current || requestRef.current?.signal.aborted || identityRef.current !== startedIdentity;
    setPhase("processing");
    // Process strictly one at a time — never all at once.
    for (let idx = 0; idx < queue.length; idx++) {
      if (stale()) return;
      setCurrentIndex(idx);
      setItemStatus(idx, "processing");
      const result = await processOne(queue[idx]);
      if (stale()) return;
      if (result.ok) setItemStatus(idx, "accepted");
      else setItemStatus(idx, "failed", result.error);
    }
    if (stale()) return;
    setPhase("done");
    setTimeout(() => {
      if (stale()) return;
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

  const startNotes = () => {
    if (!user) return;
    if (notesText.trim().length < 20) {
      setError(t("Please write at least a couple of sentences about the lecture."));
      return;
    }
    setError("");
    const title = notesTitle.trim() || t("Typed Lecture Notes");
    const queue: QueueItem[] = [
      {
        kind: "notes",
        label: title,
        notesText: notesText.trim(),
        notesTitle: notesTitle.trim(),
        status: "queued",
      },
    ];
    setItems(queue);
    runQueue(queue);
  };

  const formatFileSize = (bytes: number) => {
    const mb = bytes / 1024 / 1024;
    if (mb < 1) return `${(bytes / 1024).toFixed(0)} KB`;
    return `${mb.toFixed(1)} MB`;
  };

  const doneCount = items.filter((it) => it.status === "done" || it.status === "accepted").length;
  const failedCount = items.filter((it) => it.status === "failed").length;
  const finishedCount = doneCount + failedCount;
  const total = items.length;
  const isBusy = phase === "processing";
  const isDone = phase === "done";


  const statusBadge = (status: ItemStatus) => <span className={"status-badge " + (status === "failed" ? "danger" : status === "done" ? "success" : "info")}>{status === "processing" && <Icon name="loader" size={14} className="animate-spin" />}{t(status === "done" ? "Done" : status === "accepted" ? "Uploaded; analysis is queued." : status === "failed" ? "Failed" : status === "processing" ? "Uploading materials…" : "Queued")}</span>;

  return <div ref={dialogRef} role="dialog" aria-modal="true" aria-label="Upload recordings" tabIndex={-1} className="dialog-overlay" onClick={() => { if (phase === "select") closeDialog(); }}>
    <div className="dialog-panel material-dialog max-w-xl" onClick={event => event.stopPropagation()}>
      <button type="button" aria-label={t("Close dialog")} onClick={closeDialog} disabled={isBusy} className="icon-button material-dialog-close"><Icon name="close" /></button>
      {phase === "select" ? <>
        <h2>{t("Upload lecture recordings")}</h2>
        <p className="text-ink-soft text-sm mt-2 mb-6">{t("Add recordings, video URLs, or your lecture notes. Follow supporting analysis from Materials.")}</p>
        <div className="material-type-picker mb-5" role="group" aria-label={t("Recording input method")}>
          <button type="button" aria-pressed={mode === "file"} onClick={() => switchMode("file")}>{t("Upload files")}</button>
          <button type="button" aria-pressed={mode === "url"} onClick={() => switchMode("url")}>{t("Paste video URLs")}</button>
          <button type="button" aria-pressed={mode === "notes"} onClick={() => switchMode("notes")}>{t("Type notes")}</button>
        </div>
        {error && <div role="alert" className="material-inline-notice danger mb-4">{error}</div>}
        {mode === "notes" ? <>
          <label htmlFor="upload-notes-title" className="block text-sm font-medium mb-2">{t("Title (optional)")}</label>
          <input id="upload-notes-title" type="text" value={notesTitle} onChange={event => setNotesTitle(event.target.value)} placeholder={t("e.g. Week 6 — what the prof emphasized")} maxLength={80} className="ui-input w-full mb-4" />
          <label htmlFor="upload-notes-content" className="block text-sm font-medium mb-2">{t("What happened in the lecture?")}</label>
          <textarea id="upload-notes-content" value={notesText} onChange={event => { setNotesText(event.target.value); setError(""); }} rows={7} dir="auto" className="ui-input w-full mb-2 resize-y" placeholder={t("Write your lecture notes here…")} />
          <p className="text-xs text-ink-soft mb-5">{t("Your typed notes remain labeled as student content. Write at least 20 characters.")}</p>
          <button type="button" onClick={startNotes} disabled={notesText.trim().length < 20} className="ui-button primary w-full"><Icon name="file" size={18} />{t("Analyze notes")}</button>
        </> : mode === "url" ? <>
          <label htmlFor="upload-video-urls" className="block text-sm font-medium mb-2">{t("Video URLs")} <span className="text-ink-soft font-normal">{t("(one per line)")}</span></label>
          <textarea id="upload-video-urls" value={urlText} onChange={event => { setUrlText(event.target.value); setError(""); }} rows={5} dir="ltr" placeholder={"https://…\nhttps://…"} className="ui-input w-full resize-y mb-2" />
          <p className="text-xs text-ink-soft mb-5">{parsedUrls.length > 0 ? parsedUrls.length + " " + t("URLs detected · processed one at a time.") : t("We fetch each video, extract the audio to MP3, and transcribe it.")}</p>
          <button type="button" onClick={startUrls} disabled={!parsedUrls.length} className="ui-button primary w-full"><Icon name="upload" size={18} />{t("Fetch & Analyze")}{parsedUrls.length ? " (" + parsedUrls.length + ")" : ""}</button>
        </> : <>
          <div className="material-upload-drop" data-active={dragActive} onDragEnter={handleDrag} onDragOver={handleDrag} onDragLeave={handleDrag} onDrop={handleDrop}>
            <span className="material-upload-symbol"><Icon name="upload" size={26} /></span>
            <p className="font-medium">{t(dragActive ? "Drop your recordings here" : "Drag and drop recordings")}</p>
            <p className="text-xs text-ink-soft">{ACCEPTED_EXTS.join(", ").toUpperCase()} · {MAX_SIZE_MB}MB · {t("select multiple")}</p>
            <button type="button" onClick={() => fileInputRef.current?.click()} className="ui-button secondary">{t("Browse recordings")}</button>
            <input ref={fileInputRef} type="file" multiple accept={ACCEPT_ATTR} onChange={handleFileChange} className="hidden" aria-label={t("Choose recordings")} />
          </div>
          {items.length > 0 && <div className="material-upload-list">{items.map((item, index) => <div key={item.label + index} className="material-upload-file">
            <Icon name="file" size={20} className="text-ink-soft shrink-0" /><div className="material-file-copy"><p dir="auto">{item.label}</p>{item.file && <span className="text-xs text-ink-soft tabular-nums">{formatFileSize(item.file.size)}</span>}</div>
            <button type="button" aria-label={t("Remove") + " " + item.label} className="icon-button" onClick={() => removeFile(index)}><Icon name="close" size={18} /></button>
          </div>)}</div>}
          <button type="button" onClick={startFiles} disabled={!items.length} className="ui-button primary w-full"><Icon name="upload" size={18} />{t("Upload & Analyze")}{items.length ? " (" + items.length + ")" : ""}</button>
          <p className="text-xs text-ink-soft leading-relaxed mt-4">{t("Uploads are queued one at a time. Follow analysis progress on the course page.")}</p>
        </>}
      </> : <div className="text-center pt-4" aria-live="polite" aria-atomic="false">
        <div className="material-progress-count">{finishedCount}/{total}</div>
        <h2>{t(isDone ? failedCount ? "Finished with some issues" : "Uploaded; analysis is queued." : "Uploading materials…")}</h2>
        <p className="text-sm text-ink-soft mt-2 mb-5">{doneCount} {t("of")} {total} {t("uploaded")}{failedCount ? " · " + failedCount + " " + t("failed") : ""}</p>
        {!isDone && items[currentIndex] && <p dir="auto" className="text-sm text-ink-soft mb-4 break-words">{t("Now")}: {items[currentIndex].label}</p>}
        {!isDone && <div className="mb-4">{stepsFor(items[currentIndex]).map((step,index) => <div key={step.id} className="material-stage" data-active={index === currentStep && !completed.has(step.id)} data-done={completed.has(step.id)}>
          <span className="material-stage-mark">{completed.has(step.id) ? <Icon name="check" size={16} /> : index + 1}</span><span className="flex-1 text-sm font-medium">{t(step.label)}</span><span className="text-xs text-ink-soft">{t(completed.has(step.id) ? "done" : index === currentStep ? "in progress…" : "queued")}</span>
        </div>)}</div>}
        <div className="material-upload-list">{items.map((item,index) => <div key={item.label + index} className="material-upload-file"><div className="material-file-copy"><p dir="auto">{item.label}</p>{item.error && <p className="text-xs text-danger mt-1" role="alert">{item.error}</p>}</div>{statusBadge(item.status)}</div>)}</div>
        <p className="text-xs text-ink-soft mt-5">{t(isDone ? "Done — closing…" : "One recording at a time — please keep this open.")}</p>
      </div>}
    </div>
  </div>;
}
