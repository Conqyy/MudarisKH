"use client";

import Icon from "@/components/Icon";
import { useDialog } from "@/lib/use-dialog";

import {
  useState,
  useRef,
  useEffect,
  ChangeEvent,
  DragEvent,
  ReactNode,
} from "react";
import { useAuth } from "@/lib/auth-context";
import { useLang } from "@/lib/i18n";

import { apiFetch } from "@/lib/api";
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
  /** Legacy presentation props are accepted for existing consumers. */
  accent?: string;
  icon?: string;
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
  maxSizeMB?: number;
  pollAccepted?: (result: unknown, signal: AbortSignal) => Promise<void>;
  actualStep?: { documentId: string; step: number } | null;
  acceptedId?: "document_id" | "exam_id" | "tutorial_id";
  completionMode?: "analyzed" | "queued";
  extraFields?: Record<string, string>;
  selectionFields?: ReactNode;
  selectionValid?: boolean;
}

type Phase = "select" | "processing" | "done";
type FileStatus = "queued" | "processing" | "accepted" | "done" | "failed";

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
  acceptExts,
  acceptAttr,
  heading,
  subtitle,
  fileNoun,
  steps,
  footerNote,
  maxSizeMB = MAX_SIZE_MB,
  pollAccepted,
  actualStep,
  acceptedId = "document_id",
  completionMode = "analyzed",
  extraFields,
  selectionFields,
  selectionValid = true,
}: Props) {
  const dialogRef = useDialog(() => { if (phase !== "processing") onClose(); });
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
  const [acceptedDocumentId, setAcceptedDocumentId] = useState<string | null>(null);
  const [completed, setCompleted] = useState<Set<string>>(new Set());

  const cancelledRef = useRef(false);
  const requestRef = useRef<AbortController | null>(null);
  const completionRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const identity = `${user?.uid || ""}:${courseId}`;
  const identityRef = useRef(identity);
  identityRef.current = identity;

  useEffect(() => {
    cancelledRef.current = false;
    setPhase("select");
    setItems([]);
    return () => {
      cancelledRef.current = true;
      requestRef.current?.abort();
      if (completionRef.current) clearTimeout(completionRef.current);
    };
  }, [identity]);

  useEffect(() => {
    // Status belongs to one accepted document, never the previous batch file.
    if (pollAccepted && acceptedDocumentId && actualStep?.documentId === acceptedDocumentId) {
      setCurrentStep(actualStep.step);
      setCompleted(new Set(steps.slice(0, actualStep.step).map(s => s.id)));
    }
  }, [actualStep, acceptedDocumentId, pollAccepted, steps]);

  const validateFile = (f: File): string | null => {
    const sizeMB = f.size / 1024 / 1024;
    if (sizeMB > maxSizeMB)
      return `"${f.name}" is too large (${sizeMB.toFixed(1)}MB). Max is ${maxSizeMB}MB.`;
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

  const uploadOne = async (file: File, signal: AbortSignal) => {
    const formData = new FormData();
    formData.append("file", file);
    formData.append("user_id", user!.uid);
    formData.append("course_id", courseId);
    formData.append("title", file.name.replace(/\.[^/.]+$/, ""));
    Object.entries(extraFields || {}).forEach(([key, value]) => formData.append(key, value));

    const res = await apiFetch(`${API_URL}${endpoint}`, {
      method: "POST",
      body: formData,
      signal,
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
    setAcceptedDocumentId(null);
    setCurrentStep(0);
    setCompleted(new Set());

    let finished = false;
    const controller = requestRef.current!;
    const uploadPromise = uploadOne(file, controller.signal);

    // Cosmetic step animation (all but the last step, which holds until done)
    if (!pollAccepted) (async () => {
      for (let i = 0; i < steps.length; i++) {
        if (cancelledRef.current || controller.signal.aborted || finished) return;
        setCurrentStep(i);
        if (i === steps.length - 1) return;
        await new Promise((r) => setTimeout(r, steps[i].duration));
        if (cancelledRef.current || controller.signal.aborted || finished) return;
        setCompleted((prev) => new Set(prev).add(steps[i].id));
      }
    })();

    try {
      const response = await uploadPromise;
      controller.signal.throwIfAborted();
      if (pollAccepted) {
        const accepted = await response.json();
        controller.signal.throwIfAborted();
        const id = accepted?.[acceptedId];
        if (typeof id !== "string" || !id || (accepted.materialId && accepted.materialId !== id)) throw new Error(t("Upload did not return a material identity."));
        setAcceptedDocumentId(id);
        await pollAccepted(accepted, controller.signal);
        controller.signal.throwIfAborted();
      }
      finished = true;
      if (!cancelledRef.current) {
        setCompleted(new Set((completionMode === "queued" ? steps.slice(0, 1) : steps).map((s) => s.id)));
        setCurrentStep(completionMode === "queued" ? 1 : steps.length);
      }
      return { ok: true };
    } catch (e: any) {
      finished = true;
      return { ok: false, error: e?.message || "Upload failed" };
    }
  };

  const startProcessing = async () => {
    if (!user || !selectionValid) return;
    if (items.length === 0) {
      setError(`Please add at least one ${fileNoun}.`);
      return;
    }
    setError("");
    cancelledRef.current = false;
    const startedIdentity = identity;
    requestRef.current?.abort();
    requestRef.current = new AbortController();
    const stale = () => cancelledRef.current || requestRef.current?.signal.aborted || identityRef.current !== startedIdentity;
    setPhase("processing");

    // Process strictly one at a time — never all at once.
    for (let idx = 0; idx < items.length; idx++) {
      if (stale()) return;
      setCurrentIndex(idx);
      setItemStatus(idx, "processing");

      const result = await processOne(items[idx].file);
      if (stale()) return;

      if (result.ok) setItemStatus(idx, completionMode === "queued" ? "accepted" : "done");
      else setItemStatus(idx, "failed", result.error);
    }

    if (stale()) return;
    setPhase("done");
    // Give the user a beat to read the final counter, then refresh + close.
    completionRef.current = setTimeout(() => {
      if (stale()) return;
      onSuccess();
      onClose();
    }, 1600);
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


  const statusBadge = (status: FileStatus) => {
    if (status === "done") return <span className="status-badge success">● {t("Done")}</span>;
    if (status === "accepted") return <span className="status-badge warning">{t("Uploaded; analysis is queued.")}</span>;
    if (status === "failed") return <span className="status-badge danger">{t("Failed")}</span>;
    if (status === "processing") return <span className="status-badge info"><Icon name="loader" size={14} className="animate-spin" />{t(pollAccepted && completionMode === "analyzed" ? "Analyzing…" : "Uploading materials…")}</span>;
    return <span className="status-badge">{t("Queued")}</span>;
  };

  return (
    <div ref={dialogRef} role="dialog" aria-modal="true" aria-label="Upload materials" tabIndex={-1} className="dialog-overlay" onClick={() => { if (phase === "select") onClose(); }}>
      <div className="dialog-panel material-dialog max-w-xl" onClick={event => event.stopPropagation()}>
        <button type="button" onClick={onClose} aria-label={t("Close dialog")} disabled={isBusy} className="icon-button material-dialog-close"><Icon name="close" /></button>
        {phase === "select" ? <>
          <h2>{t(heading)}</h2>
          <p className="text-ink-soft text-sm mt-2 mb-6">{t(subtitle)}</p>
          {selectionFields}
          {error && <div role="alert" className="material-inline-notice danger">{error}</div>}
          <div className="material-upload-drop" data-active={dragActive} onDragEnter={handleDrag} onDragOver={handleDrag} onDragLeave={handleDrag} onDrop={handleDrop}>
            <span className="material-upload-symbol"><Icon name="upload" size={26} /></span>
            <p className="font-medium">{t(dragActive ? "Drop your files here" : "Drag and drop your files")}</p>
            <p className="text-xs text-ink-soft">{acceptExts.join(", ").toUpperCase()} · {maxSizeMB}MB · {t("select multiple")}</p>
            <button type="button" className="ui-button secondary" onClick={() => fileInputRef.current?.click()}>{t("Browse files")}</button>
            <input ref={fileInputRef} type="file" multiple accept={acceptAttr} onChange={handleFileChange} className="hidden" aria-label={t("Choose files")} />
          </div>
          {items.length > 0 && <div className="material-upload-list">{items.map((item, index) => <div key={item.file.name + index} className="material-upload-file">
            <Icon name="file" size={20} className="text-ink-soft shrink-0" />
            <div className="material-file-copy"><p dir="auto">{item.file.name}</p><span className="text-xs text-ink-soft tabular-nums">{formatFileSize(item.file.size)}</span></div>
            <button type="button" aria-label={t("Remove") + " " + item.file.name} className="icon-button" onClick={() => removeFile(index)}><Icon name="close" size={18} /></button>
          </div>)}</div>}
          <button type="button" disabled={!items.length || !selectionValid} className="ui-button primary w-full" onClick={startProcessing}><Icon name="upload" size={18} />{t("Upload & Analyze")}{items.length > 0 ? " (" + items.length + ")" : ""}</button>
          {footerNote && <p className="text-xs text-ink-soft leading-relaxed mt-4">{t(footerNote)}</p>}
        </> : <div className="text-center pt-4" aria-live="polite" aria-atomic="false">
          <div className="material-progress-count">{finishedCount}/{total}</div>
          <h2>{t(isDone ? failedCount ? "Finished with some issues" : completionMode === "queued" ? "Uploaded; analysis is queued." : "All files analyzed!" : "Uploading materials…")}</h2>
          <p className="text-sm text-ink-soft mt-2 mb-5">{doneCount} {t("of")} {total} {t(completionMode === "queued" ? "uploaded" : "analyzed")}{failedCount > 0 ? " · " + failedCount + " " + t("failed") : ""}</p>
          {!isDone && items[currentIndex] && <p className="text-sm text-ink-soft mb-4 break-words" dir="auto">{t("Now")}: {items[currentIndex].file.name}</p>}
          {!isDone && pollAccepted && <div className="mb-4">{steps.map((step, index) => <div key={step.id} className="material-stage" data-active={index === currentStep && !completed.has(step.id)} data-done={completed.has(step.id)}>
            <span className="material-stage-mark">{completed.has(step.id) ? <Icon name="check" size={16} /> : index + 1}</span>
            <span className="flex-1 text-sm font-medium">{t(step.label)}</span>
            <span className="text-xs text-ink-soft">{t(completed.has(step.id) ? "done" : index === currentStep ? "in progress…" : "queued")}</span>
          </div>)}</div>}
          <div className="material-upload-list">{items.map((item, index) => <div key={item.file.name + index} className="material-upload-file">
            <div className="material-file-copy"><p dir="auto">{item.file.name}</p>{item.error && <p className="text-xs text-danger mt-1" role="alert">{item.error}</p>}</div>
            {statusBadge(item.status)}
          </div>)}</div>
          <p className="text-xs text-ink-soft mt-5">{t(isDone ? "Done — closing…" : "One file at a time — please keep this open.")}</p>
        </div>}
      </div>
    </div>
  );
}
