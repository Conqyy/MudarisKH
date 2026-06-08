"use client";

import MultiUploadModal, { Step } from "@/components/MultiUploadModal";

interface Props {
  courseId: string;
  onClose: () => void;
  onSuccess: () => void;
}

const STEPS: Step[] = [
  { id: "upload", label: "Uploading tutorial", duration: 1000 },
  { id: "read", label: "Reading problems (text + images)", duration: 2000 },
  { id: "topics", label: "Identifying topics covered", duration: 2400 },
  { id: "ideas", label: "Capturing worked-problem ideas", duration: 2600 },
  { id: "link", label: "Linking ideas to the exam generator", duration: 2200 },
];

export default function UploadTutorialModal({ courseId, onClose, onSuccess }: Props) {
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
      footerNote="Tutorials add problem ideas only — analyzed one at a time, ~15–30s each."
    />
  );
}
