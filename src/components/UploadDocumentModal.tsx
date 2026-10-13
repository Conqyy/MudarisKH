"use client";

import { useCallback, useState } from "react";
import MultiUploadModal, { Step } from "@/components/MultiUploadModal";
import type { CourseDocument } from "@/lib/firestore-helpers";
import { apiJson } from "@/lib/api";
import { useLang } from "@/lib/i18n";

interface Props { courseId: string; onClose: () => void; onSuccess: () => void; }
const API_URL = process.env.NEXT_PUBLIC_BACKEND_URL || "http://127.0.0.1:8000";
const STEPS: Step[] = [
  { id: "upload", label: "Uploading document", duration: 0 },
  { id: "prepare", label: "Preparing document", duration: 0 },
  { id: "guide", label: "Creating lightweight analysis", duration: 0 },
];
function pause(signal: AbortSignal) {
  return new Promise<void>((resolve, reject) => {
    const abort = () => { clearTimeout(timer); reject(new DOMException("Aborted", "AbortError")); };
    const timer = setTimeout(() => { signal.removeEventListener("abort", abort); resolve(); }, 2000);
    signal.addEventListener("abort", abort, { once: true });
    if (signal.aborted) abort();
  });
}
export default function UploadDocumentModal({ courseId, onClose, onSuccess }: Props) {
  const [stage, setStage] = useState<{ documentId: string; step: number } | null>(null);
  const { t } = useLang();
  const pollAccepted = useCallback(async (result: unknown, signal: AbortSignal) => {
    const id = (result as { document_id?: unknown })?.document_id;
    if (typeof id !== "string" || !id) throw new Error(t("Upload did not return a document identity."));
    setStage({ documentId: id, step: 1 });
    for (let attempt = 0; attempt < 300; attempt++) {
      signal.throwIfAborted();
      const data: { document?: CourseDocument } = await apiJson(`${API_URL}/api/documents/detail/${encodeURIComponent(id)}`, { signal });
      signal.throwIfAborted();
      const doc = data.document;
      if (!doc || doc.id !== id || (doc.courseId && doc.courseId !== courseId)) throw new Error(t("Document is unavailable."));
      if (doc.preparationStatus === "failed") throw new Error(doc.preparationError || t("Document preparation failed. Retry preparation from the course."));
      if (doc.guideStatus === "failed") throw new Error(doc.guideError || t("Lightweight analysis failed. Retry analysis from the course."));
      setStage({ documentId: id, step: doc.preparationStatus === "completed" ? 2 : 1 });
      if (doc.preparationStatus === "completed" && doc.guideStatus === "completed") return;
      await pause(signal);
    }
    throw new Error(t("Document is still processing. Check its stages on the course page."));
  }, [courseId, t]);
  return <MultiUploadModal courseId={courseId} onClose={onClose} onSuccess={onSuccess}
    endpoint="/api/documents/upload" accent="#c8472f" icon="📄" acceptExts={["pdf", "pptx", "docx"]}
    acceptAttr="application/pdf,application/vnd.openxmlformats-officedocument.presentationml.presentation,application/vnd.openxmlformats-officedocument.wordprocessingml.document,.pdf,.pptx,.docx"
    heading="Upload documents" subtitle="Every document is prepared from the original and receives a lightweight analysis. Both stages must finish before confirmation."
    fileNoun="document" steps={STEPS} maxSizeMB={100} actualStep={stage} pollAccepted={pollAccepted}
    footerNote="Up to 100 MiB, 160 pages or slides, and 600,000 extracted characters. Split larger documents. Unsupported visuals need a clearer PDF or replacement before confirmation." />;
}
