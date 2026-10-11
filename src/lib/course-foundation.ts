export type CourseFoundationState = "missing" | "processing" | "failed" | "confirmation_required" | "ready";

export interface CourseFoundation {
  ready: boolean;
  state: CourseFoundationState;
  revision: string;
  documentCount: number;
  completedCount: number;
  pendingCount: number;
  failedCount: number;
  failedDocumentIds?: string[];
  message: string;
}

const guidance: Record<CourseFoundationState, string> = {
  missing: "Upload all your lecture documents first. Every document needs a successful analysis before you can unlock supporting uploads and study tools.",
  processing: "Lecture documents are still being analyzed. Wait for every document to finish before confirming your uploads.",
  failed: "Some lecture documents need attention. Retry failed or empty analyses below, or remove documents you no longer need.",
  confirmation_required: "All current lecture documents are analyzed. Upload any remaining lecture documents, then confirm that you have uploaded them all.",
  ready: "Your lecture documents are analyzed and confirmed. Supporting uploads and study tools are unlocked.",
};

export function foundationGuidance(foundation: CourseFoundation | null, loading: boolean, error: string | null): string {
  if (loading) return "Checking your lecture document foundation…";
  if (error && !foundation) return "Could not check your lecture documents. Retry to unlock supporting uploads and study tools safely.";
  return foundation ? guidance[foundation.state] : guidance.missing;
}
