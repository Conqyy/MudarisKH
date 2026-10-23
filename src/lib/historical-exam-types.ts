export const HISTORICAL_EXAM_TYPES = ["quiz", "midterm", "final"] as const;
export type HistoricalExamType = typeof HISTORICAL_EXAM_TYPES[number];
export const EXAM_TYPE_LABELS: Record<HistoricalExamType, string> = { quiz: "Quiz", midterm: "Midterm", final: "Final" };
export const EXAM_GROUP_LABELS: Record<HistoricalExamType, string> = { quiz: "Quizzes", midterm: "Midterms", final: "Finals" };
