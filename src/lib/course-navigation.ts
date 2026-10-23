export type CourseTab = "overview" | "materials" | "exam" | "flashcards" | "summary" | "tutor";

/** Preserve existing document/audio links while the course root gains two views. */
export function resolveCourseView(search: Pick<URLSearchParams, "get">): "overview" | "materials" {
  return search.get("view") === "materials" || search.get("doc") || search.get("audio") || search.get("section") === "documents" ? "materials" : "overview";
}

export function courseTabHref(courseId: string, tab: CourseTab): string {
  const root = `/course/${encodeURIComponent(courseId)}`;
  return tab === "overview" ? root : tab === "materials" ? `${root}?view=materials` : `${root}/${tab}`;
}
