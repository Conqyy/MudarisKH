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
  failedStages?: Record<string, { stage: "preparation" | "guide" | "upgrade_required"; error: string }>;
  message: string;
}

const guidance: Record<CourseFoundationState, string> = {
  missing: "Upload all your lecture documents first. Every document needs successful preparation and lightweight analysis before you can unlock supporting uploads and study tools.",
  processing: "Lecture documents are still being prepared or analyzed. Wait for both stages of every document before confirming your uploads.",
  failed: "Some lecture documents need attention. Retry the failed stage or prepare older documents below. Replace unsupported visuals with a clearer PDF, or remove documents you no longer need.",
  confirmation_required: "All current lecture documents are prepared and analyzed. Upload any remaining lecture documents, then confirm that you have uploaded them all.",
  ready: "Your lecture documents are prepared, analyzed and confirmed. Supporting uploads and study tools are unlocked.",
};

export function foundationGuidance(foundation: CourseFoundation | null, loading: boolean, error: string | null): string {
  if (loading) return "Checking your lecture document foundation…";
  if (error && !foundation) return "Could not check your lecture documents. Retry to unlock supporting uploads and study tools safely.";
  return foundation ? guidance[foundation.state] : guidance.missing;
}
