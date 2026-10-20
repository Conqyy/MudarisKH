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
  { id: "upload", label: "Uploading tutorial", duration: 0 },
  { id: "extract", label: "Extracting source content…", duration: 0 },
  { id: "align", label: "Comparing with lectures…", duration: 0 },
];

export default function UploadTutorialModal({ courseId, onClose, onSuccess }: Props) {
  const [stage, setStage] = useState<{ documentId: string; step: number } | null>(null);
  const pollAccepted = useCallback(async (result: unknown, signal: AbortSignal) => {
    const accepted = result as { tutorial_id?: unknown; materialId?: unknown; kind?: unknown; jobId?: unknown };
    if (typeof accepted.tutorial_id !== "string" || accepted.materialId !== accepted.tutorial_id || accepted.kind !== "tutorial" || typeof accepted.jobId !== "string") throw new Error("Upload did not return a material identity.");
    const status = await getSupportingStatus("tutorial", accepted.tutorial_id, signal, courseId);
    if (status.jobId !== accepted.jobId) throw new Error("Supporting analysis changed. Check the course page.");
    setStage({ documentId: accepted.tutorial_id, step: status.stage === "aligning" ? 2 : status.stage === "extracting" ? 1 : 0 });
  }, [courseId]);
  return (
    <MultiUploadModal
      courseId={courseId}
      onClose={onClose}
      onSuccess={onSuccess}
      endpoint="/api/tutorials/upload"
      accent="#3f6f7d"
      icon="✏️"
      acceptExts={["pdf", "pptx", "docx"]}
      acceptAttr="application/pdf,application/vnd.openxmlformats-officedocument.presentationml.presentation,application/vnd.openxmlformats-officedocument.wordprocessingml.document,.pdf,.pptx,.docx"
      heading="Upload tutorials"
      subtitle="Mudaris will look at the tutorial problems and use their ideas to build exam-style questions."
      fileNoun="tutorial"
      steps={STEPS}
      pollAccepted={pollAccepted} actualStep={stage} acceptedId="tutorial_id" completionMode="queued"
      footerNote="Uploads are queued one at a time. Follow analysis progress on the course page."
    />
  );
}
