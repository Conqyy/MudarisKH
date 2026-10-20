"use client";

import { useCallback, useState } from "react";
import MultiUploadModal, { Step } from "@/components/MultiUploadModal";
import { getSupportingStatus } from "@/lib/supporting-materials";

interface Props {
  courseId: string;
  onClose: () => void;
  onSuccess: () => void;
}

const STEPS: Step[] = [
  { id: "upload", label: "Uploading exam", duration: 0 },
  { id: "extract", label: "Extracting source content…", duration: 0 },
  { id: "align", label: "Comparing with lectures…", duration: 0 },
];

export default function UploadHistoricalExamModal({ courseId, onClose, onSuccess }: Props) {
  const [stage, setStage] = useState<{ documentId: string; step: number } | null>(null);
  const pollAccepted = useCallback(async (result: unknown, signal: AbortSignal) => {
    const accepted = result as { exam_id?: unknown; materialId?: unknown; kind?: unknown; jobId?: unknown };
    if (typeof accepted.exam_id !== "string" || accepted.materialId !== accepted.exam_id || accepted.kind !== "historical_exam" || typeof accepted.jobId !== "string") throw new Error("Upload did not return a material identity.");
    const status = await getSupportingStatus("historical_exam", accepted.exam_id, signal, courseId);
    if (status.jobId !== accepted.jobId) throw new Error("Supporting analysis changed. Check the course page.");
    setStage({ documentId: accepted.exam_id, step: status.stage === "aligning" ? 2 : status.stage === "extracting" ? 1 : 0 });
  }, [courseId]);
  return (
    <MultiUploadModal
      courseId={courseId}
      onClose={onClose}
      onSuccess={onSuccess}
      endpoint="/api/historical-exams/upload"
      accent="#c8472f"
      icon="📋"
      acceptExts={["pdf", "jpg", "jpeg", "png", "webp", "heic", "heif"]}
      acceptAttr="application/pdf,.pdf,image/*"
      heading="Upload past exams"
      subtitle="Upload a PDF or photos of the exam pages. Mudaris will study its format, question types, and how marks are distributed."
      fileNoun="past exam"
      steps={STEPS}
      pollAccepted={pollAccepted} actualStep={stage} acceptedId="exam_id" completionMode="queued"
      footerNote="Uploads are queued one at a time. Follow analysis progress on the course page."
    />
  );
}
