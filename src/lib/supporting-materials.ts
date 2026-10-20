import { API_URL, apiFetch, fetchObjectUrl } from "@/lib/api";

export type MaterialKind = "historical_exam" | "tutorial" | "audio" | "notes";
export interface SupportingRef { kind: MaterialKind; materialId: string; sourceRevision: string; unitId: string; }
export interface SupportingStatus {
  id?: string; courseId?: string; materialId: string; kind: MaterialKind; jobId: string | null;
  status: "queued" | "processing" | "completed" | "incomplete" | "failed" | "legacy" | string;
  stage: string | null; progress: { completedUnits: number; totalUnits: number | null; completedRequirements: number; totalRequirements: number | null };
  sourceRevision: string | null; reportRevision: string | null; scopeRevision: string | null;
  coverage: { source?: unknown; extraction?: unknown; alignment?: unknown } | null;
  legacy: boolean; stale: boolean; errorMessage: string | null;
  title?: string; sourceType?: string; uploadedAt?: number;
}
export interface SupportingRequirement { id: string; text: string; category: string; supportingSourceRefs?: SupportingRef[]; }
export interface SupportingProof { ref: SupportingRef; type?: string; quote?: string; }
export interface SupportingItem { id: string; parentId: string | null; paperId: string | null; printedLabel: string | null; itemType: string; text: string; printedMarks: number | null; requirements: SupportingRequirement[]; supportingSourceRefs?: SupportingRef[]; sharedContextIds: string[]; choices?: unknown[]; givenData?: unknown[]; }
export interface SupportingContextDependency { componentId: string; ownerType: "shared_context" | "item"; ownerId: string; field: string; index: number | null; decision: "required" | "not_required" | "unresolved"; relation: string; usable: boolean; verification?: { reason?: string } | null; supportingSourceProofs: SupportingProof[]; lectureSupportProofs: Array<{ ref: unknown }>; }
export interface SupportingAlignment { itemId: string; status: string; requirements: Array<{ requirementId: string; relation: string; reason: string; lectureAnchorRefs?: unknown[]; lectureSupportProofs?: unknown[]; supportingSourceProofs?: SupportingProof[] }>; unresolvedRequirementIds: string[]; contextDependencies?: SupportingContextDependency[]; }
export interface SupportingTopic { id: string; text: string; itemIds: string[]; requirementIds: string[]; supportingSourceRefs: SupportingRef[]; alignment: { topicId: string; originRequirementIds: string[]; relation: string; reason: string; lectureAnchorRefs?: unknown[]; lectureSupportProofs?: Array<{ ref: unknown }>; supportingSourceProofs?: SupportingProof[] } | null; }
export interface SupportingReportPage { reportRevision: string; offset: number; limit: number; total: number; nextOffset: number | null; items: SupportingItem[]; alignments: SupportingAlignment[]; sharedContexts: Array<{ id: string; text: string; supportingSourceRefs?: SupportingRef[] }>; papers: Array<{ paperId: string; [key: string]: unknown }>; topics: SupportingTopic[]; extractionCoverage: Record<string, unknown>; alignmentCoverage: Record<string, unknown>; scopeSnapshot: Record<string, unknown>; }
export interface SupportingSource { ref: SupportingRef; originalPage?: number | null; unit: { unitId: string; position: number; kind: string; text: string; visualText: string; visualAssets: Array<{ assetId: string; kind: string }>; disposition: string; timing: { startSeconds: number; endSeconds: number } | null }; }
export interface SupportingRow { id: string; kind?: string; materialId?: string; sourceType?: string; status: string; legacy?: boolean; stale?: boolean; sourceRevision?: string | null; reportRevision?: string | null; jobId?: string | null; title?: string; }
export type SupportingPresentation = "usable" | "waiting" | "retry" | "missing";

const kinds: MaterialKind[] = ["historical_exam", "tutorial", "audio", "notes"];
const valid = (value: unknown): value is string => typeof value === "string" && !!value.trim();
export function validatedSupportingRefs(value: unknown): SupportingRef[] {
  if (!Array.isArray(value)) return [];
  const seen = new Set<string>();
  return value.flatMap(candidate => {
    if (!candidate || !kinds.includes(candidate.kind) || ![candidate.materialId, candidate.sourceRevision, candidate.unitId].every(valid)) return [];
    const ref: SupportingRef = { kind: candidate.kind, materialId: candidate.materialId, sourceRevision: candidate.sourceRevision, unitId: candidate.unitId };
    const key = JSON.stringify(ref);
    if (seen.has(key)) return [];
    seen.add(key);
    return [ref];
  });
}
export function kindForRow(row: SupportingRow, collection: "historical_exam" | "tutorial" | "audio"): MaterialKind {
  return collection === "audio" && row.sourceType === "notes" ? "notes" : collection;
}
export function supportingPresentation(row: SupportingRow | undefined): SupportingPresentation {
  if (!row) return "missing";
  if (row.status === "missing") return "missing";
  if (row.status === "completed" && !row.legacy && !row.stale && valid(row.jobId) && valid(row.sourceRevision) && valid(row.reportRevision)) return "usable";
  if (["queued", "processing", "preparing", "extracting", "aligning"].includes(row.status) && !row.stale) return "waiting";
  return "retry";
}
export function selectedSupportingBlocker(selected: Set<string>, rows: SupportingRow[]): { id: string; row?: SupportingRow; reason: SupportingPresentation } | null {
  const byId = new Map(rows.map(row => [row.id, row]));
  for (const id of selected) {
    const row = byId.get(id);
    const reason = supportingPresentation(row);
    if (reason !== "usable") return { id, row, reason };
  }
  return null;
}
export function firstSupportingBlocker(groups: Array<{ selected: Set<string>; rows: SupportingRow[] }>) {
  for (const group of groups) {
    const blocker = selectedSupportingBlocker(group.selected, group.rows);
    if (blocker) return blocker;
  }
  return null;
}
export function retainSelectedRows<T extends SupportingRow>(rows: T[], previous: T[], selected: Set<string>): T[] {
  const ids = new Set(rows.map(row => row.id));
  return [...rows, ...previous.filter(row => selected.has(row.id) && !ids.has(row.id)).map(row => ({ ...row, status: "missing" }))];
}

function path(kind: MaterialKind, id: string, action: string, params: Record<string, string | number | undefined> = {}) {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) if (value !== undefined) query.set(key, String(value));
  return `${API_URL}/api/supporting/${encodeURIComponent(kind)}/${encodeURIComponent(id)}/${action}${query.size ? `?${query}` : ""}`;
}
async function responseJson<T>(url: string, init: RequestInit = {}): Promise<T> {
  const response = await apiFetch(url, init);
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    const error = new Error(typeof body?.detail === "string" ? body.detail : `Request failed (${response.status})`);
    Object.assign(error, { status: response.status });
    throw error;
  }
  init.signal?.throwIfAborted();
  return response.json();
}
function exactStatus(status: SupportingStatus, kind: MaterialKind, id: string): SupportingStatus {
  if (status?.kind !== kind || status?.materialId !== id) throw new Error("Supporting material identity changed");
  return status;
}
export async function getSupportingStatus(kind: MaterialKind, materialId: string, signal?: AbortSignal, courseId?: string): Promise<SupportingStatus> {
  return exactStatus(await responseJson(path(kind, materialId, "status", { course_id: courseId }), { signal }), kind, materialId);
}
export async function prepareSupportingMaterial(kind: MaterialKind, materialId: string, courseId?: string, retry = false, signal?: AbortSignal): Promise<SupportingStatus> {
  return exactStatus(await responseJson(path(kind, materialId, "prepare", { course_id: courseId, retry: retry ? "true" : undefined }), { method: "POST", signal }), kind, materialId);
}
export async function getSupportingReport(kind: MaterialKind, materialId: string, revision: string, offset = 0, limit = 50, signal?: AbortSignal, courseId?: string): Promise<SupportingReportPage> {
  const page = await responseJson<SupportingReportPage>(path(kind, materialId, "report", { revision, course_id: courseId, offset, limit }), { signal });
  if (page?.reportRevision !== revision) throw new Error("Report revision changed");
  if (page.offset !== offset || page.limit !== limit || !Number.isInteger(page.total) || page.total < 0 || !Array.isArray(page.items) || page.items.length > limit) throw new Error("Invalid report page");
  const expectedCount = Math.min(limit, Math.max(0, page.total - offset));
  const expectedNext = offset + limit < page.total ? offset + limit : null;
  if (page.items.length !== expectedCount || page.nextOffset !== expectedNext) throw new Error("Invalid report continuation");
  return page;
}
export async function getSupportingSource(ref: SupportingRef, signal?: AbortSignal, courseId?: string): Promise<SupportingSource> {
  const checked = validatedSupportingRefs([ref])[0];
  if (!checked) throw new Error("Invalid supporting source identity");
  const result = await responseJson<SupportingSource>(path(ref.kind, ref.materialId, "source", { revision: ref.sourceRevision, unit_id: ref.unitId, course_id: courseId }), { signal });
  if (!result?.ref || Object.entries(checked).some(([key, value]) => result.ref[key as keyof SupportingRef] !== value) || result.unit?.unitId !== ref.unitId) throw new Error("Supporting source identity changed");
  return result;
}
export function getSupportingOriginal(ref: SupportingRef, courseId: string, signal?: AbortSignal): Promise<string> {
  return fetchObjectUrl(path(ref.kind, ref.materialId, "original", { revision: ref.sourceRevision, course_id: courseId }), { signal });
}
export async function getLegacySupportingAnalysis(kind: MaterialKind, materialId: string, courseId: string, signal?: AbortSignal): Promise<Record<string, unknown>> {
  const value = await responseJson<Record<string, unknown>>(path(kind, materialId, "legacy-analysis", { course_id: courseId }), { signal });
  if (value.materialId !== materialId || value.kind !== kind || value.courseId !== courseId || value.legacy !== true) throw new Error("Legacy analysis identity changed");
  return value;
}
