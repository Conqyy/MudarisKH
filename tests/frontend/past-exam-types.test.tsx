import React from "react";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import ExamPage from "../../src/app/course/[id]/exam/page";
import SummaryPage from "../../src/app/course/[id]/summary/page";
import CoursePage from "../../src/app/course/[id]/page";
import UploadHistoricalExamModal from "../../src/components/UploadHistoricalExamModal";

const mocks = vi.hoisted(() => ({ api: vi.fn(), update: vi.fn(), user: { uid: "u1" }, course: { id: "c1", userId: "u1", title: "Algorithms", code: "CS", color: "sage", examOrder: ["q1", "m1", "q2", "f1", "old"] } }));
vi.mock("@/lib/api", () => ({ apiFetch: mocks.api, apiJson: async (url: string, init?: RequestInit) => { const result = await mocks.api(url, init); const data = await result.json(); if (!result.ok) throw new Error(data.detail); return data; } }));
vi.mock("@/lib/auth-context", () => ({ useAuth: () => ({ user: mocks.user, loading: false }) }));
vi.mock("@/lib/firestore-helpers", () => ({ getCourse: async () => mocks.course, getUserCourses: async () => [mocks.course], updateCourse: mocks.update }));
vi.mock("@/lib/activity", () => ({ useTrackRecent: () => {} }));
vi.mock("@/components/Navbar", () => ({ default: () => null }));
vi.mock("@/components/Sidebar", () => ({ default: () => null }));
vi.mock("@/components/BookmarkButton", () => ({ default: () => null }));
vi.mock("@/components/SupportingMaterialAction", () => ({ default: () => null }));
vi.mock("next/navigation", () => ({ useParams: () => ({ id: "c1" }), useSearchParams: () => new URLSearchParams(), useRouter: () => ({ push: vi.fn() }) }));
vi.mock("next/link", () => ({ default: ({ children, ...props }: any) => <a {...props}>{children}</a> }));

const response = (data: unknown) => ({ ok: true, status: 200, json: async () => data });
const paper = (id: string, examType?: string) => ({ id, examType, title: `Paper ${id}`, status: "completed", jobId: "j1", sourceRevision: "s1", reportRevision: "r1", stale: false, legacy: false, uploadedAt: 1 });
function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>(r => { resolve = r; }); return { promise, resolve }; }
const docs = [{ id: "d1", title: "Lecture one", status: "completed", fileType: "pdf", preparationStatus: "completed", guideStatus: "completed" }, { id: "d2", title: "Lecture two", status: "completed", fileType: "pdf", preparationStatus: "completed", guideStatus: "completed" }];
beforeEach(() => {
  vi.resetAllMocks();
  mocks.api.mockImplementation(async (url: string) => {
    if (url.endsWith("/foundation")) return response({ ready: true, state: "ready", revision: "r1", documentCount: 2, completedCount: 2 });
    if (url.includes("/documents/")) return response({ documents: docs });
    if (url.includes("/intelligence/")) return response({ counts: { historical_exams: 99, tutorials: 0, audio: 0 } });
    if (url.includes("/historical-exams/")) { const type = new URL(url).searchParams.get("exam_type"); return response({ historical_exams: type ? [paper(`${type}1`, type)] : [paper("q1", "quiz"), paper("q2", "quiz"), paper("m1", "midterm"), paper("f1", "final"), paper("old")] }); }
    return response({});
  });
});
afterEach(cleanup);

it("requires an authoritative batch type and sends it on every real upload", async () => {
  mocks.api.mockImplementation(async (url: string) => url.endsWith("/upload") ? response({ exam_id: "h1", materialId: "h1", kind: "historical_exam", jobId: "j1" }) : response({ materialId: "h1", kind: "historical_exam", jobId: "j1", status: "queued", stage: "queued", courseId: "c1" }));
  const { container, unmount } = render(<UploadHistoricalExamModal courseId="c1" onClose={() => {}} onSuccess={() => {}} />);
  fireEvent.change(container.querySelector('input[type="file"]')!, { target: { files: [new File(["a"], "merged.pdf", { type: "application/pdf" }), new File(["b"], "second.pdf", { type: "application/pdf" })] } });
  expect((screen.getByRole("button", { name: /Upload & Analyze/ }) as HTMLButtonElement).disabled).toBe(true);
  fireEvent.change(screen.getByRole("combobox", { name: "Past exam type" }), { target: { value: "midterm" } });
  fireEvent.click(screen.getByRole("button", { name: /Upload & Analyze/ }));
  await waitFor(() => expect(mocks.api.mock.calls.filter(([url]) => url.endsWith("/upload"))).toHaveLength(2));
  const forms = mocks.api.mock.calls.filter(([url]) => url.endsWith("/upload")).map(([, init]) => init.body as FormData);
  expect(forms.map(form => form.get("exam_type"))).toEqual(["midterm", "midterm"]);
  expect(forms.map(form => (form.get("file") as File).name)).toEqual(["merged.pdf", "second.pdf"]);
  unmount();
});

it("groups course papers, classifies legacy papers through the API and preserves other groups on reorder", async () => {
  let classified = false;
  const base = mocks.api.getMockImplementation()!;
  mocks.api.mockImplementation(async (url: string, init?: RequestInit) => {
    if (url.endsWith("/old/classify")) { classified = true; return response({ historical_exam: paper("old", "midterm") }); }
    if (url.endsWith("/historical-exams/c1")) return response({ historical_exams: [paper("q1", "quiz"), paper("q2", "quiz"), paper("m1", "midterm"), paper("f1", "final"), paper("old", classified ? "midterm" : undefined)] });
    return base(url, init);
  });
  render(<CoursePage />);
  const quizzes = await screen.findByRole("region", { name: "Quizzes" });
  expect(within(quizzes).getByText("2")).toBeTruthy();
  expect(within(screen.getByRole("region", { name: "Midterms" })).getByText("1")).toBeTruthy();
  expect(within(screen.getByRole("region", { name: "Finals" })).getByText("1")).toBeTruthy();
  fireEvent.click(within(quizzes).getByRole("button", { name: /Move Paper q1 down/ }));
  await waitFor(() => expect(mocks.update).toHaveBeenCalledWith("c1", { examOrder: ["q2", "m1", "q1", "f1", "old"] }, { examOrder: ["q1", "m1", "q2", "f1", "old"] }));
  fireEvent.change(screen.getByRole("combobox", { name: "Classify Paper old" }), { target: { value: "midterm" } });
  await waitFor(() => expect(within(screen.getByRole("region", { name: "Midterms" })).getByText("Paper old")).toBeTruthy());
  expect(mocks.api.mock.calls.find(([url]) => url.endsWith("/old/classify"))?.[1]).toMatchObject({ method: "POST", body: JSON.stringify({ exam_type: "midterm" }) });
  expect(screen.queryByRole("combobox", { name: "Classify Paper old" })).toBeNull();
});

for (const [name, Page, generate] of [["exam", ExamPage, /Generate Exam/], ["summary", SummaryPage, /Generate Summary/]] as const) {
  it(`${name} excludes mismatched and unclassified API rows and clears a previous category blocker`, async () => {
    let sent: any;
    const base = mocks.api.getMockImplementation()!;
    mocks.api.mockImplementation(async (url: string, init?: RequestInit) => {
      if (init?.method === "POST") { sent = JSON.parse(init.body as string); return new Promise(() => {}); }
      if (url.includes("exam_type=final")) return response({ historical_exams: [{ ...paper("pending", "final"), status: "queued" }, paper("wrong", "quiz"), paper("unclassified")] });
      return base(url, init);
    });
    render(<Page />);
    const pending = await screen.findByRole("checkbox", { name: /Paper pending/ });
    expect(screen.queryByText("Paper wrong")).toBeNull();
    expect(screen.queryByText("Paper unclassified")).toBeNull();
    fireEvent.click(pending);
    expect((screen.getByRole("button", { name: generate }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(screen.getByRole("combobox", { name: "Past exam type" }), { target: { value: "midterm" } });
    await screen.findByText("Paper midterm1");
    expect(screen.queryByText("Paper pending")).toBeNull();
    expect((screen.getByRole("button", { name: generate }) as HTMLButtonElement).disabled).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: generate }));
    await waitFor(() => expect(sent).toMatchObject({ historical_exam_type: "midterm", historical_exam_ids: ["midterm1"] }));
  });
  it(`${name} scopes requests and selections to the chosen category, preserves lectures and ignores late responses`, async () => {
    const slow = deferred<any>(); const sent: any[] = [];
    const base = mocks.api.getMockImplementation()!;
    mocks.api.mockImplementation(async (url: string, init?: RequestInit) => {
      if (init?.method === "POST") { sent.push(JSON.parse(init.body as string)); return new Promise(() => {}); }
      if (url.includes("exam_type=quiz")) return slow.promise;
      return base(url, init);
    });
    render(<Page />);
    await screen.findByText("Paper final1");
    expect(screen.queryByText(/99 past exam/)).toBeNull();
    fireEvent.click(screen.getByRole("checkbox", { name: /Lecture two/ }));
    fireEvent.change(screen.getByRole("combobox", { name: "Past exam type" }), { target: { value: "quiz" } });
    expect(screen.queryByText("Paper final1")).toBeNull();
    expect((screen.getByRole("button", { name: generate }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(screen.getByRole("combobox", { name: "Past exam type" }), { target: { value: "midterm" } });
    await screen.findByText("Paper midterm1");
    await act(async () => slow.resolve(response({ historical_exams: [paper("lateQuiz", "quiz")] })));
    expect(screen.queryByText("Paper lateQuiz")).toBeNull();
    expect((screen.getByRole("checkbox", { name: /Lecture two/ }) as HTMLInputElement).checked).toBe(false);
    if (name === "exam") fireEvent.change(screen.getByRole("slider"), { target: { value: "5" } });
    fireEvent.click(screen.getByRole("button", { name: generate }));
    await waitFor(() => expect(sent).toHaveLength(1));
    expect(sent[0]).toMatchObject({ historical_exam_type: "midterm", historical_exam_ids: ["midterm1"], document_ids: ["d1"] });
    if (name === "exam") expect(sent[0]).toMatchObject({ exam_type: "Midterm", total_marks: 5 });
    expect(mocks.api.mock.calls.filter(([url]) => url.includes("/historical-exams/")).every(([url]) => new URL(url).searchParams.has("exam_type"))).toBe(true);
  });
  it(`${name} sends an explicit empty selection after deselecting the visible category`, async () => {
    let sent: any;
    const base = mocks.api.getMockImplementation()!;
    mocks.api.mockImplementation(async (url: string, init?: RequestInit) => { if (init?.method === "POST") { sent = JSON.parse(init.body as string); return new Promise(() => {}); } return base(url, init); });
    render(<Page />);
    fireEvent.click(await screen.findByRole("checkbox", { name: /Paper final1/ }));
    fireEvent.click(screen.getByRole("button", { name: generate }));
    await waitFor(() => expect(sent).toMatchObject({ historical_exam_type: "final", historical_exam_ids: [] }));
  });
}
