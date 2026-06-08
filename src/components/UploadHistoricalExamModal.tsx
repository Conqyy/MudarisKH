"use client";

import MultiUploadModal, { Step } from "@/components/MultiUploadModal";

interface Props {
  courseId: string;
  onClose: () => void;
  onSuccess: () => void;
}

const STEPS: Step[] = [
  { id: "upload", label: "Uploading exam", duration: 1000 },
  { id: "read", label: "Reading exam pages (text + images)", duration: 2000 },
  { id: "types", label: "Identifying question types", duration: 2600 },
  { id: "weights", label: "Weighting topics & difficulty", duration: 2200 },
  { id: "blueprint", label: "Building grading blueprint", duration: 2600 },
];

export default function UploadHistoricalExamModal({ courseId, onClose, onSuccess }: Props) {
  return (
    <MultiUploadModal
      courseId={courseId}
      onClose={onClose}
      onSuccess={onSuccess}
      endpoint="/api/historical-exams/upload"
      accent="#c8472f"
      icon="📋"
      acceptExts={["pdf"]}
      acceptAttr="application/pdf,.pdf"
      heading="Upload past exams"
      subtitle="Mudaris will study the past exam to learn its format, question types, and how marks are distributed."
      fileNoun="past exam"
      steps={STEPS}
    />
  );
}
