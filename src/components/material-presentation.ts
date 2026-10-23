import type { IconName } from "@/components/Icon";
import type { ActivityKind } from "@/lib/activity";
import type { ReminderType } from "@/lib/firestore-helpers";

export const COURSE_COLORS = [
  { name: "Blue", value: "#526BCB" },
  { name: "Violet", value: "#8267B9" },
  { name: "Cyan", value: "#278A9B" },
  { name: "Green", value: "#45806C" },
  { name: "Amber", value: "#B17B2A" },
  { name: "Rose", value: "#B46381" },
];

export const ACTIVITY_ICONS: Record<ActivityKind, IconName> = {
  course: "folder", document: "file", audio: "audio", exam: "exam", summary: "summary", flashcards: "cards",
};

export const REMINDER_ICONS: Record<ReminderType, IconName> = {
  quiz: "edit", midterm: "exam", final: "exam", assignment: "file", project: "layers", presentation: "audio", other: "calendar",
};
