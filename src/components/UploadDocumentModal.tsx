"use client";

import MultiUploadModal, { Step } from "@/components/MultiUploadModal";

interface Props {
  courseId: string;
  onClose: () => void;
  onSuccess: () => void;
}

const STEPS: Step[] = [
  { id: "upload", label: "Uploading document", duration: 1000 },
  { id: "extract", label: "Extracting text", duration: 1600 },
  { id: "concepts", label: "Analyzing concepts & definitions", duration: 2600 },
  { id: "formulas", label: "Identifying formulas & key terms", duration: 2200 },
  { id: "chapters", label: "Mapping chapters & topics", duration: 2600 },
];

export default function UploadDocumentModal({ courseId, onClose, onSuccess }: Props) {
  return (
    <MultiUploadModal
      courseId={courseId}
      onClose={onClose}
      onSuccess={onSuccess}
      endpoint="/api/documents/upload"
      accent="#c8472f"
      icon="📄"
      acceptExts={["pdf", "pptx", "docx"]}
      acceptAttr="application/pdf,application/vnd.openxmlformats-officedocument.presentationml.presentation,application/vnd.openxmlformats-officedocument.wordprocessingml.document,.pdf,.pptx,.docx"
      heading="Upload documents"
      subtitle="Mudaris will read your document, analyze it, and pull out the key topics, definitions, and formulas."
      fileNoun="document"
      steps={STEPS}
    />
  );
}
