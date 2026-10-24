import React from "react";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import ExamPage from "../../src/app/course/[id]/exam/page";
import SummaryPage from "../../src/app/course/[id]/summary/page";
import CoursePage from "../../src/app/course/[id]/page";
import UploadHistoricalExamModal from "../../src/components/UploadHistoricalExamModal";

const mocks = vi.hoisted(() => ({ api: vi.fn(), update: vi.fn(), search: "", user: { uid: "u1" }, course: { id: "c1", userId: "u1", title: "Algorithms", code: "CS", color: "sage", examOrder: ["q1", "m1", "q2", "f1", "old"] } }));
vi.mock("@/lib/api", () => ({ API_URL: "http://127.0.0.1:8000", apiFetch: mocks.api, apiJson: async (url: string, init?: RequestInit) => { const result = await mocks.api(url, init); const data = await result.json(); if (!result.ok) throw new Error(data.detail); return data; } }));
vi.mock("@/lib/auth-context", () => ({ useAuth: () => ({ user: mocks.user, loading: false }) }));
vi.mock("@/lib/firestore-helpers", () => ({ getCourse: async () => mocks.course, getUserCourses: async () => [mocks.course], updateCourse: mocks.update }));
vi.mock("@/lib/activity", () => ({ useTrackRecent: () => {} }));
vi.mock("@/components/Navbar", () => ({ default: () => null }));
vi.mock("@/components/Sidebar", () => ({ default: () => null }));
vi.mock("@/components/BookmarkButton", () => ({ default: () => null }));
vi.mock("@/components/SupportingMaterialAction", () => ({ default: () => null }));
vi.mock("next/navigation", () => ({ useParams: () => ({ id: "c1" }), useSearchParams: () => new URLSearchParams(mocks.search), useRouter: () => ({ push: vi.fn() }) }));
vi.mock("next/link", () => ({ default: ({ children, ...props }: any) => <a {...props}>{children}</a> }));

const response = (data: unknown) => ({ ok: true, status: 200, json: async () => data });
const paper = (id: string, examType?: string) => ({ id, examType, title: `Paper ${id}`, status: "completed", jobId: "j1", sourceRevision: "s1", reportRevision: "r1", stale: false, legacy: false, uploadedAt: 1 });
function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>(r => { resolve = r; }); return { promise, resolve }; }
const docs = [{ id: "d1", title: "Lecture one", status: "completed", fileType: "pdf", preparationStatus: "completed", guideStatus: "completed" }, { id: "d2", title: "Lecture two", status: "completed", fileType: "pdf", preparationStatus: "completed", guideStatus: "completed" }];
beforeEach(() => {
  vi.resetAllMocks();
  mocks.search = "";
  mocks.api.mockImplementation(async (url: string) => {
    if (url.endsWith("/foundation")) return response({ ready: true, state: "ready", revision: "r1", documentCount: 2, completedCount: 2 });
    if (url.includes("/documents/")) return response({ documents: docs });
    if (url.includes("/intelligence/")) return response({ counts: { historical_exams: 99, tutorials: 0, audio: 0 } });
    if (url.includes("/historical-exams/")) { const type = new URL(url).searchParams.get("exam_type"); return response({ historical_exams: type ? [paper(`${type}1`, type)] : [paper("q1", "quiz"), paper("q2", "quiz"), paper("m1", "midterm"), paper("f1", "final"), paper("old")] }); }
    return response({});
  });
});
afterEach(cleanup);

it("separates overview exam mini cards by type and keeps unclassified papers discoverable", async () => {
  render(<CoursePage />);
  const group = await screen.findByRole("region", { name: "Past Exams" });
  const cards = ["Final", "Midterm", "Quiz"].map(name => within(group).getByRole("region", { name }));
  expect([...group.querySelectorAll(".course-material-panel")].map(card => card.id)).toEqual(["past-exams-final", "past-exams-midterm", "past-exams-quiz"]);
  expect(cards.map(card => card.querySelector('[id$="-count"]')?.textContent)).toEqual(["1", "1", "2"]);
  expect(screen.queryByText("Paper f1")).toBeTruthy();
  expect(within(cards[0]).queryByRole("button", { name: /Move Paper f1/ })).toBeNull();
  fireEvent.click(within(cards[0]).getByRole("button", { name: "Final" }));
  expect(within(cards[0]).getByText("Paper f1")).toBeTruthy();
  expect(within(cards[0]).queryByText("Paper q1")).toBeNull();
  expect(within(cards[0]).queryByText("Paper m1")).toBeNull();
  expect(within(cards[1]).getByRole("button", { name: "Midterm" }).getAttribute("aria-expanded")).toBe("false");
  expect(within(group).getByRole("link", { name: /Needs classification.*1/ }).getAttribute("href")).toBe("/course/c1?view=materials#past-exams");
});

it.each([["Final", "final"], ["Midterm", "midterm"], ["Quiz", "quiz"]] as const)("preselects the %s mini card's upload category", async (name, type) => {
  render(<CoursePage />);
  const card = await screen.findByRole("region", { name });
  fireEvent.click(within(card).getByRole("button", { name }));
  fireEvent.click(within(card).getByRole("button", { name: /^\+?\s*Upload$/ }));
  expect((await screen.findByRole("combobox", { name: "Past exam type" }) as HTMLSelectElement).value).toBe(type);
  for (const other of ["Final", "Midterm", "Quiz"].filter(label => label !== name)) {
    expect(within(screen.getByRole("region", { name: other })).getByRole("button", { name: other }).getAttribute("aria-expanded")).toBe("false");
  }
});

it("keeps a past-exam selection and lecture confirmation while focus revalidates the foundation", async () => {
  const { container } = render(<CoursePage />);
  const card = await screen.findByRole("region", { name: "Final" });
  fireEvent.click(within(card).getByRole("button", { name: "Final" }));
  fireEvent.click(within(card).getByRole("button", { name: /^\+?\s*Upload$/ }));
  const dialog = await screen.findByRole("dialog", { name: "Upload materials" });
  const selector = within(dialog).getByRole("combobox", { name: "Past exam type" }) as HTMLSelectElement;
  const background = deferred<any>();
  mocks.api.mockImplementationOnce(() => background.promise);
  const callsBeforeFocus = mocks.api.mock.calls.length;

  // A native file chooser returns window focus before its change event. A
  // background GET must not revoke the last confirmed result or remount files.
  fireEvent(window, new Event("focus"));
  expect(screen.queryByRole("dialog", { name: "Upload materials" })).toBe(dialog);
  fireEvent.change(within(dialog).getByLabelText("Choose files"), { target: { files: [new File(["synthetic"], "selected-final.pdf", { type: "application/pdf" })] } });
  expect(within(dialog).getByText("selected-final.pdf")).toBeTruthy();
  expect(selector.value).toBe("final");
  expect(container.querySelector(".journey-confirm-node.is-confirmed")).not.toBeNull();
  expect(screen.getByText("Your lecture foundation is confirmed.")).toBeTruthy();
  const studyActions = container.querySelectorAll<HTMLButtonElement>("button.journey-tool");
  expect(studyActions).toHaveLength(4);
  expect([...studyActions].every(button => button.disabled)).toBe(true);
  expect(container.querySelector("a.journey-tool")).toBeNull();
  expect(mocks.api.mock.calls.slice(callsBeforeFocus).map(([url, init]) => [url, init?.method || "GET"]))
    .toEqual([[expect.stringMatching(/\/foundation$/), "GET"]]);

  await act(async () => background.resolve(response({ ready: true, state: "ready", revision: "r1", documentCount: 2, completedCount: 2 })));
  expect(screen.getByRole("dialog", { name: "Upload materials" })).toBe(dialog);
  expect(within(dialog).getByText("selected-final.pdf")).toBeTruthy();
  expect(within(dialog).getByRole("combobox", { name: "Past exam type" })).toBe(selector);
});

it("keeps a submitted past-exam request running through focus revalidation", async () => {
  const { container } = render(<CoursePage />);
  const card = await screen.findByRole("region", { name: "Final" });
  fireEvent.click(within(card).getByRole("button", { name: "Final" }));
  fireEvent.click(within(card).getByRole("button", { name: /^\+?\s*Upload$/ }));
  const dialog = await screen.findByRole("dialog", { name: "Upload materials" });
  fireEvent.change(within(dialog).getByLabelText("Choose files"), { target: { files: [new File(["synthetic"], "in-flight-final.pdf", { type: "application/pdf" })] } });
  const submitted = deferred<any>();
  let uploadSignal: AbortSignal | undefined;
  mocks.api.mockImplementationOnce((_url: string, init: RequestInit) => {
    uploadSignal = init.signal as AbortSignal;
    return submitted.promise;
  });
  fireEvent.click(within(dialog).getByRole("button", { name: /Upload & Analyze/ }));
  await waitFor(() => expect(uploadSignal).toBeDefined());
  const background = deferred<any>();
  mocks.api.mockImplementationOnce(() => background.promise);

  fireEvent(window, new Event("focus"));
  expect(screen.getByRole("dialog", { name: "Upload materials" })).toBe(dialog);
  expect(uploadSignal?.aborted).toBe(false);
  expect([...container.querySelectorAll<HTMLButtonElement>("button.journey-tool")].every(button => button.disabled)).toBe(true);
  await act(async () => background.resolve(response({ ready: true, state: "ready", revision: "r1", documentCount: 2, completedCount: 2 })));
  expect(uploadSignal?.aborted).toBe(false);

  mocks.api.mockImplementationOnce(async () => response({ materialId: "h1", kind: "historical_exam", jobId: "j1", status: "queued", stage: "queued", courseId: "c1" }));
  await act(async () => submitted.resolve(response({ exam_id: "h1", materialId: "h1", kind: "historical_exam", jobId: "j1" })));
  expect(within(dialog).getByText("1/1")).toBeTruthy();
  expect(within(dialog).getByRole("heading", { name: "Uploaded; analysis is queued." })).toBeTruthy();
  expect(mocks.api.mock.calls.filter(([url, init]) => url.endsWith("/upload") && init?.method === "POST")).toHaveLength(1);
  expect(mocks.api.mock.calls.filter(([url]) => url.endsWith("/confirm"))).toHaveLength(0);
});

it.each(["changed", "failed"] as const)("revokes an active past-exam upload when the foundation check is %s", async outcome => {
  render(<CoursePage />);
  const card = await screen.findByRole("region", { name: "Final" });
  fireEvent.click(within(card).getByRole("button", { name: "Final" }));
  fireEvent.click(within(card).getByRole("button", { name: /^\+?\s*Upload$/ }));
  const dialog = await screen.findByRole("dialog", { name: "Upload materials" });
  fireEvent.change(within(dialog).getByLabelText("Choose files"), { target: { files: [new File(["synthetic"], "unsent-final.pdf", { type: "application/pdf" })] } });
  const background = deferred<any>();
  mocks.api.mockImplementationOnce(() => background.promise);
  fireEvent(window, new Event("focus"));
  expect(screen.queryByRole("dialog", { name: "Upload materials" })).toBe(dialog);

  await act(async () => {
    if (outcome === "failed") background.resolve({ ok: false, json: async () => ({ detail: "Foundation unavailable" }) });
    else background.resolve(response({ ready: false, state: "confirmation_required", revision: "changed", documentCount: 3, completedCount: 3 }));
  });
  expect(screen.queryByRole("dialog", { name: "Upload materials" })).toBeNull();
  expect((within(card).getByRole("button", { name: /^\+?\s*Upload$/ }) as HTMLButtonElement).disabled).toBe(true);
  expect(screen.queryByText("Your lecture foundation is confirmed.")).toBeNull();
  expect(mocks.api.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(0);
});

it("allows a preselected exam upload category to be changed before sending", async () => {
  mocks.api.mockImplementation(async (url: string) => url.endsWith("/upload") ? response({ exam_id: "h1", materialId: "h1", kind: "historical_exam", jobId: "j1" }) : response({ materialId: "h1", kind: "historical_exam", jobId: "j1", status: "queued", stage: "queued", courseId: "c1" }));
  const { container } = render(<UploadHistoricalExamModal initialExamType="final" courseId="c1" onClose={() => {}} onSuccess={() => {}} />);
  expect((screen.getByRole("combobox", { name: "Past exam type" }) as HTMLSelectElement).value).toBe("final");
  fireEvent.change(screen.getByRole("combobox", { name: "Past exam type" }), { target: { value: "quiz" } });
  fireEvent.change(container.querySelector('input[type="file"]')!, { target: { files: [new File(["a"], "quiz.pdf", { type: "application/pdf" })] } });
  fireEvent.click(screen.getByRole("button", { name: /Upload & Analyze/ }));
  await waitFor(() => expect(mocks.api.mock.calls.some(([url]) => url.endsWith("/upload"))).toBe(true));
  const sent = mocks.api.mock.calls.find(([url]) => url.endsWith("/upload"))?.[1]?.body as FormData;
  expect(sent.get("exam_type")).toBe("quiz");
});

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
  mocks.search = "view=materials";
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
