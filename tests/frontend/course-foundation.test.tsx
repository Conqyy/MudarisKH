import React from "react";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const fake = vi.hoisted(() => ({
  user: { uid: "student" },
  foundation: { ready: false, state: "confirmation_required", revision: "revision-1", documentCount: 1, completedCount: 1, pendingCount: 0, failedCount: 0, failedDocumentIds: [] as string[], message: "Confirm all lecture documents." },
  foundationError: "", confirmError: "", confirmation: null as { revision: string } | null,
  documentRows: [] as any[],
  mutations: [] as string[],
  search: "",
}));
vi.mock("next/navigation", () => ({ useParams: () => ({ id: "course-1" }), useSearchParams: () => new URLSearchParams(fake.search), useRouter: () => ({ push: vi.fn() }) }));
vi.mock("next/link", () => ({ default: ({ children, href, ...props }: any) => <a {...props} href={href} onClick={event => { event.preventDefault(); fake.search = new URL(href, "http://localhost").search; }}>{children}</a> }));
vi.mock("@/lib/auth-context", () => ({ useAuth: () => ({ user: fake.user, loading: false }) }));
vi.mock("@/lib/i18n", () => ({ useLang: () => ({ t: (text: string) => text }) }));
vi.mock("@/lib/activity", () => ({ useTrackRecent: () => {} }));
vi.mock("@/lib/firestore-helpers", () => ({
  getCourse: async () => ({ id: "course-1", userId: "student", code: "CS101", title: "Algorithms", instructor: "Professor", color: "sage" }),
  getUserCourses: async () => [], updateCourse: async (_id: string, data: unknown) => data, deleteCourse: async () => {},
}));
vi.mock("@/components/Navbar", () => ({ default: () => null }));
vi.mock("@/components/Sidebar", () => ({ default: () => null }));
vi.mock("@/components/BookmarkButton", () => ({ default: () => null }));
vi.mock("@/components/EditCourseModal", () => ({ default: () => null }));
vi.mock("@/components/UploadDocumentModal", () => ({ default: ({ onSuccess, onClose }: any) => <div role="dialog" aria-label="Document upload"><button onClick={() => { fake.foundation = { ...fake.foundation, ready: false, state: "confirmation_required", revision: "revision-2", documentCount: 2, completedCount: 2 }; onSuccess(); onClose(); }}>Finish document upload</button><button onClick={() => { fake.foundation = { ...fake.foundation, ready: false, state: "failed", revision: "revision-2", documentCount: 2, failedCount: 1 }; onClose(); }}>Close after a failed upload</button></div> }));
vi.mock("@/lib/api", () => ({
  API_URL: "http://backend",
  apiJson: async (url: string, init?: RequestInit) => {
    if (url.endsWith("/foundation/confirm")) {
      fake.confirmation = JSON.parse(init?.body as string);
      if (fake.confirmError) { fake.foundation = { ...fake.foundation, revision: "revision-2" }; throw new Error(fake.confirmError); }
      fake.foundation = { ...fake.foundation, ready: true, state: "ready" };
      return fake.foundation;
    }
    if (url.endsWith("/foundation")) { if (fake.foundationError) throw new Error(fake.foundationError); return fake.foundation; }
    if (url.includes("/documents/detail/")) return { document: fake.documentRows[0] };
    if (url.includes("/documents/")) return { documents: fake.documentRows };
    return {};
  },
  apiFetch: async (url: string, init?: RequestInit) => {
    if (init?.method === "DELETE") { fake.documentRows = []; fake.foundation = { ...fake.foundation, ready: false, state: "missing", revision: "revision-2", documentCount: 0, completedCount: 0 }; }
    if (url.endsWith("/reanalyze") || url.endsWith("/prepare")) {
      fake.mutations.push(url);
      fake.documentRows[0] = { ...fake.documentRows[0], status: "completed", sourceRevision: "source-2", preparationStatus: "completed", guideStatus: "completed", guide: { version: 1, sourceRevision: "source-2", sections: [{ label: "Sorting", purpose: "Sort arrays", unitIds: ["page-1"] }], concepts: [], warnings: [] } };
      fake.foundation = { ...fake.foundation, state: "confirmation_required", revision: "revision-2", failedCount: 0, failedDocumentIds: [], completedCount: 1 };
    }
    return { ok: true, status: 202, json: async () => ({ status: "accepted", document_id: "doc-1" }) };
  },
}));

import CoursePage from "../../src/app/course/[id]/page";

async function visitCourseView(view: ReturnType<typeof render>, name: "Materials" | "Overview") {
  fireEvent.click(await screen.findByRole("link", { name }));
  view.rerender(<CoursePage />);
  await screen.findByRole("heading", { name: name === "Materials" ? "Course materials" : "Your study journey" });
}

beforeEach(() => {
  fake.search = "";
  fake.foundation = { ready: false, state: "confirmation_required", revision: "revision-1", documentCount: 1, completedCount: 1, pendingCount: 0, failedCount: 0, failedDocumentIds: [], message: "Confirm all lecture documents." };
  fake.mutations = [];
  fake.foundationError = ""; fake.confirmError = ""; fake.confirmation = null;
  fake.documentRows = [{ id: "doc-1", courseId: "course-1", userId: "student", title: "Lecture notes", fileType: "pdf", fileSize: 20, storagePath: "notes.pdf", status: "completed", uploadedAt: 1, sourceRevision: "source-1", preparationStatus: "completed", guideStatus: "completed", analysis: { topics: ["Sorting"], definitions: [], formulas: [], chapterMapping: [] } }];
  vi.stubGlobal("confirm", () => true); vi.stubGlobal("alert", vi.fn());
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("course document foundation", () => {
  it("shows four compact material panels on overview with details available on expansion", async () => {
    render(<CoursePage />);
    await screen.findByText("Algorithms");
    const documents = screen.getByRole("heading", { name: "Documents" }).closest("section")!;
    const panels = ["Documents", "Past Exams", "Tutorials", "Audio Recordings"].map(name => screen.getByRole("heading", { name }).closest("section")!);
    expect(new Set(panels.map(panel => panel.parentElement)).size).toBe(1);
    expect(panels.map(panel => panel.id)).toEqual(["documents", "past-exams", "tutorials", "recordings"]);
    for (const [index, name] of ["Documents", "Past Exams", "Tutorials", "Audio Recordings"].entries()) {
      expect(within(panels[index]).getByRole("button", { name }).getAttribute("aria-expanded")).toBe("false");
      expect(within(panels[index]).queryByRole("button", { name: /Upload/ })).toBeNull();
    }
    expect(within(documents).queryByRole("button", { name: /^Lecture notes/ })).toBeNull();
    fireEvent.click(within(documents).getByRole("button", { name: "Documents" }));
    expect(within(documents).getByRole("button", { name: /^Lecture notes/ })).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "Reminders" })).toBeNull();
    expect(screen.queryByRole("heading", { name: "Intelligence Summary" })).toBeNull();
  });

  it("keeps supporting uploads gated in the overview panels until lectures are confirmed", async () => {
    render(<CoursePage />);
    await screen.findByText("Algorithms");
    const sections = ["Past Exams", "Tutorials", "Audio Recordings"].map(name => {
      const section = screen.getByRole("heading", { name }).closest("section")!;
      fireEvent.click(within(section).getByRole("button", { name }));
      return section;
    });
    for (const section of sections) {
      for (const upload of within(section).getAllByRole("button", { name: /Upload/ })) expect((upload as HTMLButtonElement).disabled).toBe(true);
    }
    const documents = screen.getByRole("heading", { name: "Documents" }).closest("section")!;
    fireEvent.click(within(documents).getByRole("button", { name: "Documents" }));
    expect((within(documents).getByRole("button", { name: /Upload/ }) as HTMLButtonElement).disabled).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: /I've uploaded all lecture documents/ }));
    await screen.findByRole("link", { name: /Generate Exam/ });
    for (const section of sections) {
      for (const upload of within(section).getAllByRole("button", { name: /Upload/ })) expect((upload as HTMLButtonElement).disabled).toBe(false);
    }
  });

  it("keeps overview document actions open while their upload dialog is active", async () => {
    vi.stubGlobal("matchMedia", vi.fn((query: string) => ({ matches: query.includes("hover") })));
    const hover = (element: Element, entering: boolean) => {
      const event = new MouseEvent(entering ? "pointerover" : "pointerout", { bubbles: true, relatedTarget: entering ? null : document.body });
      Object.defineProperty(event, "pointerType", { value: "mouse" });
      fireEvent(element, event);
    };
    render(<CoursePage />);
    await screen.findByText("Algorithms");
    const documents = screen.getByRole("heading", { name: "Documents" }).closest("section")!;
    const toggle = within(documents).getByRole("button", { name: "Documents" });
    hover(documents, true);
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
    fireEvent.click(within(documents).getByRole("button", { name: /Upload/ }));
    await screen.findByRole("dialog", { name: "Document upload" });
    hover(documents, false);
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
    fireEvent.click(screen.getByRole("button", { name: "Close after a failed upload" }));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Document upload" })).toBeNull());
    const panel = (await screen.findByRole("heading", { name: "Documents" })).closest("section")!;
    const afterCloseToggle = within(panel).getByRole("button", { name: "Documents" });
    if (afterCloseToggle.getAttribute("aria-expanded") === "false") fireEvent.click(afterCloseToggle);
    expect((within(panel).getByRole("button", { name: /Upload/ }) as HTMLButtonElement).disabled).toBe(false);
  });

  it("locks every supporting upload and study action while keeping lecture upload available", async () => {
    const view = render(<CoursePage />);
    await screen.findByText("Algorithms");
    for (const name of [/Ask the Coach/, /Generate Exam/, /Make Flashcards/, /Make Summary/]) {
      expect((screen.getByRole("button", { name }) as HTMLButtonElement).disabled).toBe(true);
      expect(screen.queryByRole("link", { name })).toBeNull();
    }
    await visitCourseView(view, "Materials");
    for (const name of ["Past Exams", "Tutorials", "Audio Recordings"]) {
      const section = screen.getByRole("heading", { name }).closest("section")!;
      for (const upload of within(section).getAllByRole("button", { name: /Upload/ })) expect((upload as HTMLButtonElement).disabled).toBe(true);
      expect(section.textContent).toMatch(/lecture documents|locked/i);
    }
    const documents = screen.getByRole("heading", { name: "Documents" }).closest("section")!;
    expect((within(documents).getByRole("button", { name: /Upload/ }) as HTMLButtonElement).disabled).toBe(false);
  });

  it.each(["missing", "processing", "failed", "ready"])("does not offer completion confirmation in %s state", async (state) => {
    fake.foundation = { ...fake.foundation, state, ready: state === "ready" };
    render(<CoursePage />);
    await screen.findByText("Algorithms");
    expect(screen.queryByRole("button", { name: /I've uploaded all lecture documents/ })).toBeNull();
    if (state !== "ready") expect((screen.getByRole("button", { name: /Generate Exam/ }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("confirms the displayed revision and then unlocks all study actions", async () => {
    render(<CoursePage />);
    fireEvent.click(await screen.findByRole("button", { name: /I've uploaded all lecture documents/ }));
    await screen.findByRole("link", { name: /Generate Exam/ });
    expect(fake.confirmation).toEqual({ revision: "revision-1" });
    expect(screen.queryByRole("button", { name: /I've uploaded all lecture documents/ })).toBeNull();
  });

  it("keeps failed foundation requests locked and recovers through retry", async () => {
    fake.foundationError = "Foundation unavailable";
    render(<CoursePage />);
    await screen.findByText("Foundation unavailable");
    expect((screen.getByRole("button", { name: /Generate Exam/ }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByRole("link", { name: "View documents" }).getAttribute("href")).toBe("/course/course-1?section=documents");
    fake.foundationError = ""; fake.foundation = { ...fake.foundation, state: "ready", ready: true };
    fireEvent.click(screen.getByRole("button", { name: /Retry foundation/i }));
    await screen.findByRole("link", { name: /Generate Exam/ });
  });

  it("refreshes a stale confirmation and keeps study tools locked", async () => {
    fake.confirmError = "Documents changed. Review and confirm again.";
    render(<CoursePage />);
    fireEvent.click(await screen.findByRole("button", { name: /I've uploaded all lecture documents/ }));
    await screen.findByText("Documents changed. Review and confirm again.");
    expect((screen.getByRole("button", { name: /Generate Exam/ }) as HTMLButtonElement).disabled).toBe(true);
    fake.confirmError = "";
    fireEvent.click(screen.getByRole("button", { name: /I've uploaded all lecture documents/ }));
    await screen.findByRole("link", { name: /Generate Exam/ });
    expect(fake.confirmation).toEqual({ revision: "revision-2" });
  });

  it("locks a confirmed course again when a document upload changes its revision", async () => {
    fake.foundation = { ...fake.foundation, ready: true, state: "ready" };
    const view = render(<CoursePage />);
    await screen.findByRole("link", { name: /Generate Exam/ });
    await visitCourseView(view, "Materials");
    const documents = screen.getByRole("heading", { name: "Documents" }).closest("section")!;
    fireEvent.click(within(documents).getByRole("button", { name: /Upload/ }));
    fireEvent.click(await screen.findByRole("button", { name: /Finish document upload/ }));
    await visitCourseView(view, "Overview");
    await screen.findByRole("button", { name: /I've uploaded all lecture documents/ });
    expect((screen.getByRole("button", { name: /Generate Exam/ }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("keeps document reading and deletion available and locks again after deleting the foundation", async () => {
    fake.foundation = { ...fake.foundation, ready: true, state: "ready" };
    const view = render(<CoursePage />);
    await screen.findByRole("link", { name: /Generate Exam/ });
    await visitCourseView(view, "Materials");
    const documents = screen.getByRole("heading", { name: "Documents" }).closest("section")!;
    expect(within(documents).getByRole("button", { name: /^Lecture notes/ })).not.toBeNull();
    fireEvent.click(within(documents).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(within(documents).queryByText("Lecture notes")).toBeNull());
    await visitCourseView(view, "Overview");
    await screen.findByRole("button", { name: /Generate Exam/ });
    expect(screen.queryByRole("button", { name: /I've uploaded all lecture documents/ })).toBeNull();
  });

  it.each([undefined, { topics: [], definitions: [], formulas: [], chapterMapping: [] }])("offers document retry when a completed analysis is unusable (%j)", async (analysis) => {
    fake.foundation = { ...fake.foundation, ready: false, state: "failed", completedCount: 0, failedCount: 1 };
    fake.documentRows[0] = { ...fake.documentRows[0], analysis, sourceRevision: undefined, preparationStatus: undefined, guideStatus: undefined };
    const view = render(<CoursePage />);
    await visitCourseView(view, "Materials");
    const documents = screen.getByRole("heading", { name: "Documents" }).closest("section")!;
    const retry = within(documents).getByRole("button", { name: "Prepare document" }) as HTMLButtonElement;
    expect(retry.disabled).toBe(false);
    fireEvent.click(retry);
    expect(await within(documents).findByText(/Analyzed/)).not.toBeNull();
    await visitCourseView(view, "Overview");
    await screen.findByRole("button", { name: /I've uploaded all lecture documents/ });
    expect((screen.getByRole("button", { name: /Generate Exam/ }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("rechecks uploaded documents when the upload modal closes before its success callback", async () => {
    fake.foundation = { ...fake.foundation, ready: true, state: "ready" };
    const view = render(<CoursePage />);
    await screen.findByRole("link", { name: /Generate Exam/ });
    await visitCourseView(view, "Materials");
    const documents = screen.getByRole("heading", { name: "Documents" }).closest("section")!;
    fireEvent.click(within(documents).getByRole("button", { name: /Upload/ }));
    fireEvent.click(await screen.findByRole("button", { name: /Close after a failed upload/ }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    await visitCourseView(view, "Overview");
    const lockedAction = await screen.findByRole("button", { name: /Generate Exam/ });
    expect(screen.queryByRole("link", { name: /Generate Exam/ })).toBeNull();
    expect((lockedAction as HTMLButtonElement).disabled).toBe(true);
  });

  it("offers retry for completed documents rejected by the server analysis policy", async () => {
    fake.foundation = { ...fake.foundation, state: "failed", completedCount: 0, failedCount: 1, failedDocumentIds: ["doc-1"] };
    fake.documentRows[0] = { ...fake.documentRows[0], status: "completed", analysis: { topics: ["Trees"] } };
    const view = render(<CoursePage />);
    await visitCourseView(view, "Materials");
    const documents = screen.getByRole("heading", { name: "Documents" }).closest("section")!;
    expect(within(documents).queryByText(/Analyzed/)).toBeNull();
    const retry = within(documents).getByRole("button", { name: "retry" }) as HTMLButtonElement;
    expect(retry.disabled).toBe(false);
    fireEvent.click(retry);
    await visitCourseView(view, "Overview");
    await screen.findByRole("button", { name: /I've uploaded all lecture documents/ });
    expect((screen.getByRole("button", { name: /Generate Exam/ }) as HTMLButtonElement).disabled).toBe(true);
  });
});

it('requires both document stages before the confirmation button can be used', async () => {
  fake.documentRows[0] = { ...fake.documentRows[0], preparationStatus: 'completed', guideStatus: 'processing' };
  const view = render(<CoursePage />);
  await screen.findByText('Algorithms');
  const confirm = screen.getByRole('button', { name: /I've uploaded all lecture documents/ }) as HTMLButtonElement;
  expect(confirm.disabled).toBe(true);
  await visitCourseView(view, "Materials");
  expect(screen.getByText(/Creating lightweight analysis/)).toBeTruthy();
});
it('retries only lightweight analysis after preparation and respects authoritative guide failure', async () => {
  fake.foundation = { ...fake.foundation, state: 'failed', completedCount: 0, failedCount: 1, failedDocumentIds: ['doc-1'], failedStages: { 'doc-1': { stage: 'guide', error: 'Unsupported visual: provide a clearer PDF.' } } } as any;
  fake.documentRows[0] = { ...fake.documentRows[0], status: 'failed', guideStatus: 'failed', guideError: 'Unsupported visual: provide a clearer PDF.', unitCount: 4 };
  const view = render(<CoursePage />);
  await visitCourseView(view, "Materials");
  expect(screen.getByText('Unsupported visual: provide a clearer PDF.')).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: 'Retry lightweight analysis' }));
  await waitFor(() => expect(fake.mutations[0]).toMatch(/\/reanalyze$/));
});
it('does not claim lightweight guides extracted zero definitions or formulas', async () => {
  fake.documentRows[0] = { ...fake.documentRows[0], unitCount: 4, guide: { version: 1, sourceRevision: 'source-1', sections: [{ label: 'Arrays', purpose: 'Review arrays', unitIds: ['page-1'] }], concepts: [], warnings: [] }, analysis: { topics: [], definitions: [], formulas: [], chapterMapping: [], keyConceptCount: 0 } };
  const view = render(<CoursePage />);
  await visitCourseView(view, "Materials");
  expect(screen.getByText(/4 source units · 1 guide sections/)).toBeTruthy();
  expect(screen.queryByText('Empty')).toBeNull();
  expect(screen.queryByText(/0 definitions|0 formulas/)).toBeNull();
});

it('offers preparation retry when preparation failed while the required guide remains pending', async () => {
  fake.foundation = { ...fake.foundation, state: 'failed', failedDocumentIds: ['doc-1'], failedStages: { 'doc-1': { stage: 'preparation', error: 'Split this document into smaller files.' } } } as any;
  fake.documentRows[0] = { ...fake.documentRows[0], status: 'failed', preparationStatus: 'failed', guideStatus: 'pending' };
  const view = render(<CoursePage />);
  await visitCourseView(view, "Materials");
  fireEvent.click(screen.getByRole('button', { name: 'Retry preparation' }));
  await waitFor(() => expect(fake.mutations[0]).toMatch(/\/prepare$/));
});
