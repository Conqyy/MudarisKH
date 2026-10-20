import React from "react";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import DocumentViewer from "../../src/components/DocumentViewer";
import ExamPage from "../../src/app/course/[id]/exam/[examId]/page";
import ExamGenerationPage from "../../src/app/course/[id]/exam/page";
import TutorPage from "../../src/app/course/[id]/tutor/page";
import SummaryPage from "../../src/app/course/[id]/summary/page";
import FlashcardsPage from "../../src/app/course/[id]/flashcards/page";
import ReorderableList from "../../src/components/ReorderableList";
import CoursePage from "../../src/app/course/[id]/page";

const mocks = vi.hoisted(() => ({ api: vi.fn(), file: vi.fn(), object: vi.fn(), recent: vi.fn(), updateCourse: vi.fn(), user: { uid: "u1" }, routeId: "c1", course: { id: "c1", userId: "u1", code: "CS", name: "Course", color: "sage" } }));
vi.mock("@/lib/api", () => ({ apiFetch: mocks.api, apiJson: async (url: string, init?: RequestInit) => {
  // These regressions exercise saved content and asynchronous work in a course
  // whose document prerequisite has already been satisfied.
  if (url.endsWith("/foundation") && (!init?.method || init.method === "GET")) return { ready: true, state: "ready", revision: "confirmed-documents", documentCount: 1, completedCount: 1, pendingCount: 0, failedCount: 0, message: "Confirmed" };
  const res = await mocks.api(url, init); const data = await res.json(); if (!res.ok) throw new Error(data?.detail || `Request failed (${res.status})`); return data;
}, fetchFileObjectUrl: mocks.file, fetchObjectUrl: mocks.object }));
vi.mock("@/lib/auth-context", () => ({ useAuth: () => ({ user: mocks.user, loading: false }) }));
vi.mock("@/lib/firestore-helpers", () => ({ getCourse: async () => mocks.course, getUserCourses: async () => [mocks.course], updateCourse: mocks.updateCourse }));
vi.mock("@/lib/activity", () => ({ useTrackRecent: mocks.recent }));
vi.mock("@/components/Navbar", () => ({ default: () => null }));
vi.mock("@/components/Sidebar", () => ({ default: () => null }));
vi.mock("@/components/BookmarkButton", () => ({ default: () => null }));
vi.mock("next/navigation", () => ({ useParams: () => ({ id: mocks.routeId, examId: "e1" }), useSearchParams: () => new URLSearchParams(), useRouter: () => ({ push: vi.fn() }) }));
vi.mock("next/link", () => ({ default: ({ children, ...props }: any) => <a {...props}>{children}</a> }));

const response = (data: unknown, ok = true) => ({ ok, status: ok ? 200 : 500, json: async () => data });
const doc: any = { id: "d1", courseId: "c1", title: "Notes", fileType: "txt", fileSize: 15, uploadedAt: Date.now() };
function deferred<T>() { let resolve!: (v: T) => void; const promise = new Promise<T>(r => { resolve = r; }); return { promise, resolve }; }

beforeEach(() => {
  vi.resetAllMocks();
  mocks.routeId = "c1"; mocks.user = { uid: "u1" }; mocks.course = { id: "c1", userId: "u1", code: "CS", name: "Course", color: "sage" };
  vi.stubGlobal("alert", vi.fn()); vi.stubGlobal("confirm", () => true);
  URL.revokeObjectURL = vi.fn();
  HTMLElement.prototype.scrollTo = vi.fn();
  mocks.object.mockResolvedValue("blob:exam");
  mocks.api.mockImplementation(async (url: string) => {
    if (url.includes("exams/detail")) return response({ exam: { id: "e1", courseId: "c1", examId: "Exam", questionStructure: [], status: "ready" } });
    if (url.includes("tutor/chats")) return response({ chats: [{ id: "chat1", title: "Saved chat" }] });
    return response({});
  });
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("authenticated previews", () => {
  it("ignores and revokes a PDF result that completes after switching documents", async () => {
    const old = deferred<string>();
    mocks.object.mockImplementation((url: string) => url.includes("/d1/original") ? old.promise : Promise.resolve("blob:new"));
    const { rerender, unmount } = render(<DocumentViewer document={{ ...doc, fileType: "pdf", storagePath: "old.pdf" }} onClose={() => {}} />);
    rerender(<DocumentViewer document={{ ...doc, id: "d2", title: "New notes", fileType: "pdf", storagePath: "new.pdf" }} onClose={() => {}} />);
    await screen.findByTitle("New notes");
    await act(async () => old.resolve("blob:old"));
    expect(screen.getByTitle("New notes").getAttribute("src")).toBe("blob:new");
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:old");
    unmount(); expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:new");
  });
  it("keeps failed Office source requests terminal until retry and then displays recovered units", async () => {
    mocks.api.mockRejectedValueOnce(new Error("offline")).mockResolvedValueOnce(response({ source: { available: true, sourceRevision: 'rev1', units: [{ unitId: 'b1', label: 'Recovered notes', kind: 'docx_block' }] } }));
    render(<DocumentViewer document={{ ...doc, fileType: 'docx', sourceRevision: 'rev1' }} onClose={() => {}} />);
    await screen.findByRole("alert");
    expect(mocks.api).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: /retry source/i }));
    await screen.findByText("Recovered notes");
    expect(mocks.api).toHaveBeenCalledTimes(2);
  });
  it("supports Escape and restores focus when the viewer closes", async () => {
    const onClose = vi.fn();
    const opener = document.createElement("button"); document.body.append(opener); opener.focus();
    render(<DocumentViewer document={{ ...doc, fileType: 'pdf' }} onClose={onClose} />);
    const dialog = screen.getByRole("dialog");
    expect(dialog.contains(document.activeElement)).toBe(true);
    fireEvent.keyDown(document, { key: "Tab", shiftKey: true });
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Content" }));
    fireEvent.keyDown(document, { key: "Tab" });
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Close document" }));
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).toHaveBeenCalledOnce();
    cleanup(); expect(document.activeElement).toBe(opener); opener.remove();
  });
  it("explains preparation for legacy Office documents without a dead Content tab or detail request", async () => {
    render(<DocumentViewer document={{ ...doc, fileType: 'docx' }} onClose={() => {}} />);
    await screen.findByText(/Prepare this document from the course page/);
    expect(screen.queryByRole('button', { name: 'Content' })).toBeNull();
    expect(mocks.api).not.toHaveBeenCalled();
  });
  it("shows a PDF failure and retries once", async () => {
    mocks.object.mockRejectedValueOnce(new Error("offline")).mockResolvedValueOnce("blob:doc");
    render(<DocumentViewer document={{ ...doc, fileType: "pdf", storagePath: "safe.pdf" }} onClose={() => {}} />);
    fireEvent.click(await screen.findByRole("button", { name: /retry pdf/i }));
    await screen.findByTitle("Notes");
    expect(mocks.object).toHaveBeenCalledTimes(2);
    cleanup(); expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:doc");
  });
  it("offers a working retry after answer-key failure", async () => {
    mocks.object.mockImplementation(async (url: string) => {
      if (url.includes("answer-key")) throw new Error("failed"); return "blob:exam";
    });
    render(<ExamPage />);
    fireEvent.click(await screen.findByRole("button", { name: /reveal model answers/i }));
    const retry = await screen.findByRole("button", { name: /retry answer key/i });
    mocks.object.mockResolvedValue("blob:answers");
    fireEvent.click(retry);
    await screen.findByTitle("Model Answers PDF");
  });
});

describe("tutor request ownership", () => {
  it("keeps a real pending tutor request alive through an unchanged supporting status refresh", async () => {
    const pending = deferred<any>(); let sendSignal: AbortSignal | undefined;
    mocks.api.mockImplementation(async (url: string, init?: RequestInit) => {
      if (url.includes("historical-exams/")) return response({ historical_exams: [{ id: "h1", title: "Pending exam", status: "queued", jobId: "j1" }] });
      if (init?.method === "POST") { sendSignal = init.signal as AbortSignal; return pending.promise; }
      return response({});
    });
    render(<TutorPage />);
    await screen.findByRole("button", { name: /pending exam/i });
    fireEvent.click(await screen.findByRole("button", { name: "Explain the hardest concept simply." }));
    await waitFor(() => expect(sendSignal).toBeDefined());
    fireEvent.click(screen.getByRole("button", { name: /pending exam/i }));
    fireEvent.click(screen.getByRole("button", { name: "Refresh material status" }));
    await waitFor(() => expect(mocks.api.mock.calls.filter(([url]) => String(url).includes("historical-exams/")).length).toBeGreaterThan(1));
    expect(sendSignal?.aborted).toBe(false);
    await act(async () => pending.resolve(response({ reply: "Reply after refresh", chat_id: "chat1" })));
    await screen.findByText("Reply after refresh");
    expect(sendSignal?.aborted).toBe(false);
  });
  it("discards a pending reply after opening a different saved conversation", async () => {
    const pending = deferred<any>();
    mocks.api.mockImplementation(async (url: string, init?: RequestInit) => {
      if (init?.method === "POST") return pending.promise;
      if (url.includes("tutor/chats")) return response({ chats: [{ id: "chat1", title: "Saved chat" }] });
      if (url.endsWith("/chat/chat1")) return response({ chat: { messages: [{ role: "assistant", content: "Saved conversation reply" }] } });
      return response({});
    });
    render(<TutorPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Explain the hardest concept simply." }));
    fireEvent.click(screen.getAllByRole("button", { name: /saved chat/i })[0]);
    await screen.findByText("Saved conversation reply");
    await act(async () => pending.resolve(response({ reply: "Stale reply", chat_id: "old" })));
    expect(screen.queryByText("Stale reply")).toBeNull();
    expect(screen.getByText("Saved conversation reply")).toBeTruthy();
  });
  it("aborts an in-flight tutor request on unmount and prevents a history refresh", async () => {
    const pending = deferred<any>(); let signal: AbortSignal | undefined;
    mocks.api.mockImplementation(async (_url: string, init?: RequestInit) => { if (init?.method === "POST") { signal = init.signal as AbortSignal; return pending.promise; } return response({}); });
    const { unmount } = render(<TutorPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Explain the hardest concept simply." }));
    const calls = mocks.api.mock.calls.length;
    unmount(); expect(signal?.aborted).toBe(true);
    await act(async () => pending.resolve(response({ reply: "Stale reply", chat_id: "old" })));
    expect(mocks.api.mock.calls.length).toBe(calls);
  });
  it("does not resurrect a conversation deleted during a pending reply", async () => {
    const pending = deferred<any>();
    mocks.api.mockImplementation(async (url: string, init?: RequestInit) => {
      if (init?.method === "POST") return pending.promise;
      if (init?.method === "DELETE") return response({});
      if (url.includes("tutor/chats")) return response({ chats: [{ id: "chat1", title: "Saved chat" }] });
      if (url.endsWith("/chat/chat1")) return response({ chat: { messages: [{ role: "assistant", content: "Saved conversation reply" }] } });
      return response({});
    });
    render(<TutorPage />);
    fireEvent.click((await screen.findAllByRole("button", { name: /saved chat/i }))[0]);
    await screen.findByText("Saved conversation reply");
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "New question" } });
    fireEvent.click(screen.getByRole("button", { name: /send/i }));
    fireEvent.click(screen.getAllByTitle("Delete")[0]);
    await waitFor(() => expect(screen.queryByText("Saved conversation reply")).toBeNull());
    await act(async () => pending.resolve(response({ reply: "Stale reply", chat_id: "chat1" })));
    expect(screen.queryByText("Stale reply")).toBeNull();
    expect(screen.queryByText("Saved chat")).toBeNull();
  });
  it("restores a pending draft when deletion fails so the turn can be retried", async () => {
    const pending = deferred<any>();
    mocks.api.mockImplementation(async (url: string, init?: RequestInit) => {
      if (init?.method === "POST") return pending.promise;
      if (init?.method === "DELETE") return response({}, false);
      if (url.includes("tutor/chats")) return response({ chats: [{ id: "chat1", title: "Saved chat" }] });
      if (url.endsWith("/chat/chat1")) return response({ chat: { messages: [{ role: "assistant", content: "Saved conversation reply" }] } });
      return response({});
    });
    render(<TutorPage />);
    fireEvent.click((await screen.findAllByRole("button", { name: /saved chat/i }))[0]);
    await screen.findByText("Saved conversation reply");
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "New question" } });
    fireEvent.click(screen.getByRole("button", { name: /send/i }));
    fireEvent.click(screen.getAllByTitle("Delete")[0]);
    await waitFor(() => expect(alert).toHaveBeenCalled());
    expect((screen.getByRole("textbox") as HTMLTextAreaElement).value).toBe("New question");
    expect(screen.queryByText("New question", { selector: "div" })).toBeNull();
    await act(async () => pending.resolve(response({ reply: "Stale reply", chat_id: "chat1" })));
    expect(screen.queryByText("Stale reply")).toBeNull();
  });
  it("keeps failed tutor turns out of persisted history and restores the draft for retry", async () => {
    const payloads: any[] = [];
    mocks.api.mockImplementation(async (url: string, init?: RequestInit) => {
      if (init?.method === "POST") { payloads.push(JSON.parse(init.body as string)); return payloads.length === 1 ? response({ detail: "Provider unavailable" }, false) : response({ reply: "A good reply", chat_id: "chat1" }); }
      return response({});
    });
    render(<TutorPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Explain the hardest concept simply." }));
    await screen.findByRole("alert");
    const textbox = screen.getByRole("textbox") as HTMLTextAreaElement;
    expect(textbox.value).toBe("Explain the hardest concept simply.");
    fireEvent.click(screen.getByRole("button", { name: /send/i }));
    await screen.findByText("A good reply");
    expect(payloads[1].messages).toEqual([{ role: "user", content: "Explain the hardest concept simply." }]);
  });
  it("discards a reply from the previous conversation after New chat", async () => {
    const pending = deferred<any>();
    mocks.api.mockImplementation(async (url: string, init?: RequestInit) => {
      if (init?.method === "POST") return pending.promise;
      if (url.includes("tutor/chats")) return response({ chats: [] });
      return response({});
    });
    render(<TutorPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Explain the hardest concept simply." }));
    fireEvent.click(screen.getAllByRole("button", { name: /new chat/i })[0]);
    await act(async () => pending.resolve(response({ reply: "Stale reply", chat_id: "old" })));
    expect(screen.queryByText("Stale reply")).toBeNull();
  });
  it("keeps a saved chat visible when deletion returns HTTP failure", async () => {
    mocks.api.mockImplementation(async (url: string, init?: RequestInit) => {
      if (init?.method === "DELETE") return response({}, false);
      if (url.includes("tutor/chats")) return response({ chats: [{ id: "chat1", title: "Saved chat" }] });
      return response({});
    });
    render(<TutorPage />);
    await screen.findAllByText("Saved chat");
    fireEvent.click(screen.getAllByTitle("Delete")[0]);
    await waitFor(() => expect(alert).toHaveBeenCalled());
    expect(screen.getAllByText("Saved chat").length).toBeGreaterThan(0);
  });
});

describe("study loaders", () => {
  it.each([["summary", SummaryPage], ["exam", ExamGenerationPage], ["flashcards", FlashcardsPage], ["tutor", TutorPage]] as const)("clears %s supporting rows immediately on a course switch", async (_, Page) => {
    mocks.api.mockImplementation(async (url: string) => {
      if (url.includes("historical-exams/")) return response({ historical_exams: [{ id: mocks.routeId === "c1" ? "old" : "new", title: mocks.routeId === "c1" ? "Old private exam" : "New course exam", status: "queued", jobId: "j1" }] });
      return response({});
    });
    const view = render(<Page />);
    await screen.findByText("Old private exam");
    mocks.routeId = "c2"; mocks.course = { id: "c2", userId: "u1", code: "CS", name: "New course", color: "sage" };
    view.rerender(<Page />);
    expect(screen.queryByText("Old private exam")).toBeNull();
    await screen.findByText("New course exam");
  });
  it("clears a summary source from the previous account before the next load resolves", async () => {
    mocks.api.mockImplementation(async (url: string) => url.includes("historical-exams/") ? response({ historical_exams: [{ id: "old", title: "Old account exam", status: "queued", jobId: "j1" }] }) : response({}));
    const view = render(<SummaryPage />);
    await screen.findByText("Old account exam");
    mocks.user = { uid: "u2" }; mocks.course = { id: "c1", userId: "u2", code: "CS", name: "Course", color: "sage" };
    view.rerender(<SummaryPage />);
    expect(screen.queryByText("Old account exam")).toBeNull();
  });
  it.each([["summary", SummaryPage], ["flashcards", FlashcardsPage]] as const)("tracks a saved %s opened with the keyboard", async (kind, Page) => {
    mocks.api.mockImplementation(async (url: string) => {
      if (url.includes("/detail/")) return response(kind === "summary" ? { summary: { title: "Saved study", sections: [] } } : { set: { title: "Saved study", cards: [{ front: "Question", back: "Answer" }] } });
      if (url.includes("/list/")) return response(kind === "summary" ? { summaries: [{ id: "s1", title: "Saved study", createdAt: 1, sectionCount: 0 }] } : { sets: [{ id: "s1", title: "Saved study", createdAt: 1, cardCount: 1 }] });
      return response({});
    });
    render(<Page />);
    const row = await screen.findByRole("button", { name: /saved study/i });
    fireEvent.keyDown(row, { key: "Enter" });
    await waitFor(() => expect(mocks.recent).toHaveBeenCalledWith(expect.objectContaining({ id: "s1", kind, title: "Saved study" })));
  });
  it.each([["summary", SummaryPage], ["flashcards", FlashcardsPage]] as const)("shows a retryable load error for %s instead of empty sources", async (_, Page) => {
    mocks.api.mockResolvedValue(response({ detail: "Backend unavailable" }, false));
    render(<Page />);
    const error = await screen.findByRole("alert");
    expect(error.textContent).toMatch(/unavailable|500|load/i);
    mocks.api.mockResolvedValue(response({}));
    fireEvent.click(screen.getByRole("button", { name: /retry/i }));
    await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
  });
  it.each([["summary", SummaryPage], ["flashcards", FlashcardsPage]] as const)("aborts %s generation when leaving the page", async (kind, Page) => {
    const pending = deferred<any>(); let signal: AbortSignal | undefined;
    mocks.api.mockImplementation(async (url: string, init?: RequestInit) => {
      if (init?.method === "POST") { signal = init.signal as AbortSignal; return pending.promise; }
      return response(url.includes("/documents/") ? { documents: [{ ...doc, status: "completed" }] } : {});
    });
    const { unmount } = render(<Page />);
    fireEvent.click(await screen.findByRole("button", { name: /generate.*(summary|flashcards)/i }));
    await waitFor(() => expect(signal).toBeDefined());
    unmount(); expect(signal?.aborted).toBe(true);
    await act(async () => pending.resolve(response(kind === "summary" ? { doc_id: "s1", title: "Saved summary", sections: [] } : { doc_id: "f1", cards: [] })));
  });
});

it("offers keyboard reorder controls and awaits persistence", async () => {
  const reorder = vi.fn();
  render(<ReorderableList items={[{ id: "a", title: "First" }, { id: "b", title: "Second" }]} onReorder={reorder} onRename={async () => {}} renderIcon={() => null} renderMeta={() => null} renderStatus={() => null} />);
  fireEvent.click(screen.getByRole("button", { name: /move second up/i }));
  await waitFor(() => expect(reorder).toHaveBeenCalledWith(["b", "a"]));
});

it("retains the persisted material order when saving a reorder fails", async () => {
  mocks.updateCourse.mockRejectedValue(new Error("offline"));
  mocks.api.mockImplementation(async (url: string) => response(url.includes("/documents/") ? { documents: [{ ...doc, id: "a", title: "First notes" }, { ...doc, id: "b", title: "Second notes" }] } : {}));
  render(<CoursePage />);
  const first = (await screen.findByText("First notes")).closest('[draggable]')!;
  const second = screen.getByText("Second notes").closest('[draggable]')!;
  fireEvent.dragStart(second, { dataTransfer: {} }); fireEvent.drop(first, { dataTransfer: {} });
  await waitFor(() => expect(mocks.updateCourse).toHaveBeenCalled());
  await waitFor(() => expect(alert).toHaveBeenCalled());
  const titles = Array.from(document.querySelectorAll('[draggable]')).map(row => row.textContent);
  expect(titles[0]).toContain("First notes");
  expect(titles[1]).toContain("Second notes");
});

const citation = { documentId: 'd1', sourceRevision: 'rev1', unitId: 'page-1', label: 'Lecture page 1' };
describe('saved output source citations', () => {
  it.each([['summary', SummaryPage], ['flashcards', FlashcardsPage]] as const)('preserves exact citations in a saved %s', async (kind, Page) => {
    mocks.api.mockImplementation(async (url: string) => {
      if (url.includes('/detail/')) return response(kind === 'summary' ? { summary: { title: 'Saved cited study', sections: [{ heading: 'Evidence section', content: 'Content', sourceRefs: [citation] }] } } : { set: { title: 'Saved cited study', cards: [{ front: 'Question', back: 'Answer', sourceRefs: [citation] }] } });
      if (url.includes('/list/')) return response(kind === 'summary' ? { summaries: [{ id: 's1', title: 'Saved cited study', createdAt: 1, sectionCount: 1 }] } : { sets: [{ id: 's1', title: 'Saved cited study', createdAt: 1, cardCount: 1 }] });
      return response({});
    });
    render(<Page />);
    fireEvent.click(await screen.findByRole('button', { name: /saved cited study/i }));
    await screen.findByRole('button', { name: 'Lecture page 1' });
  });
  it('renders saved exam question citations in the normal child route', async () => {
    mocks.api.mockResolvedValue(response({ exam: { id: 'e1', courseId: 'c1', examId: 'Cited exam', questionStructure: [{ id: 'q1', type: 'short', sourceRefs: [citation] }], status: 'ready' } }));
    render(<ExamPage />);
    await screen.findByRole('button', { name: 'Lecture page 1' });
  });
  it('attaches saved tutor sourceTurns only to their assistant message and strips display metadata from POST', async () => {
    let sent: any;
    mocks.api.mockImplementation(async (url: string, init?: RequestInit) => {
      if (url.includes('/tutor/chats')) return response({ chats: [{ id: 'chat1', title: 'Saved chat' }] });
      if (url.includes('/tutor/chat/chat1')) return response({ chat: { messages: [{ role: 'user', content: 'Saved question' }, { role: 'assistant', content: 'Saved reply' }], sourceTurns: [{ messageIndex: 1, sourceRefs: [citation] }, { messageIndex: 0, sourceRefs: [{ ...citation, label: 'Wrong user citation' }] }] } });
      if (url.endsWith('/tutor/chat') && init?.method === 'POST') { sent = JSON.parse(init.body as string); return response({ reply: 'New cited reply', sourceRefs: [citation] }); }
      return response({});
    });
    render(<TutorPage />);
    fireEvent.click((await screen.findAllByRole('button', { name: /saved chat/i }))[0]);
    await screen.findByRole('button', { name: 'Lecture page 1' });
    expect(screen.queryByText('Wrong user citation')).toBeNull();
    fireEvent.change(screen.getByPlaceholderText(/ask/i), { target: { value: 'Follow up' } });
    fireEvent.keyDown(screen.getByPlaceholderText(/ask/i), { key: 'Enter' });
    await screen.findByText('New cited reply');
    expect(sent.messages[1]).toEqual({ role: 'assistant', content: 'Saved reply' });
    expect(screen.getAllByRole('button', { name: 'Lecture page 1' })).toHaveLength(2);
  });
});

it('revokes a late original PDF blob after changing signed-in account', async () => {
  const pending = deferred<string>();
  mocks.object.mockReturnValueOnce(pending.promise).mockResolvedValueOnce('blob:current-account');
  const view = render(<DocumentViewer document={{ ...doc, fileType: 'pdf' }} onClose={() => {}} />);
  mocks.user = { uid: 'u2' };
  view.rerender(<DocumentViewer document={{ ...doc, fileType: 'pdf' }} onClose={() => {}} />);
  await screen.findByTitle('Notes');
  await act(async () => pending.resolve('blob:old-account'));
  expect(screen.getByTitle('Notes').getAttribute('src')).toBe('blob:current-account');
  expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:old-account');
  expect(mocks.object.mock.calls[0][0]).toMatch(/\/api\/documents\/d1\/original$/);
  mocks.user = { uid: 'u1' };
});
it('navigates prepared source units and guide sections without storage paths or invented rich counts', async () => {
  const prepared = { ...doc, fileType: 'pdf', sourceRevision: 'rev1', unitCount: 2, preparationStatus: 'completed', guideStatus: 'completed', guide: { version: 1, sourceRevision: 'rev1', sections: [{ label: 'Arrays guide', purpose: 'Navigate array content', unitIds: ['page-1'] }], concepts: [], warnings: ['Read the original diagram.'] } };
  mocks.api.mockImplementation(async (url: string) => {
    if (url.endsWith('/sources')) return response({ source: { available: true, sourceRevision: 'rev1', units: [{ unitId: 'page-1', kind: 'pdf_page', label: 'Page 1' }], warnings: [] } });
    return response({ unit: { documentId: 'd1', sourceRevision: 'rev1', unitId: 'page-1', text: 'Original arrays' }, images: [] });
  });
  render(<DocumentViewer document={prepared as any} onClose={() => {}} />);
  expect(screen.getByRole('heading', { name: 'Guide sections' })).toBeTruthy();
  expect(await screen.findByRole('button', { name: 'Arrays guide' })).toBeTruthy();
  expect(screen.queryByText(/Definitions \(0\)|Formulas \(0\)/)).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: 'Source units' }));
  fireEvent.click(await screen.findByRole('button', { name: 'Page 1' }));
  await screen.findByText('Original arrays');
});

it('keeps guide references on their original revision while the current source changes', async () => {
  const staleGuide = { ...doc, fileType: 'pdf', sourceRevision: 'replacement', guide: { version: 1, sourceRevision: 'guide-original', sections: [{ label: 'Retained guide', purpose: 'Older original', unitIds: ['page-1'] }], concepts: [], warnings: [] } };
  mocks.api.mockResolvedValue(response({ source: { available: true, sourceRevision: 'replacement', units: [], warnings: [] } }));
  render(<DocumentViewer document={staleGuide as any} onClose={() => {}} />);
  fireEvent.click(await screen.findByRole('button', { name: 'page-1' }));
  await waitFor(() => expect(mocks.api.mock.calls.some(([url]) => url.includes('source_revision=guide-original'))).toBe(true));
});

it.each(['docx', 'pptx'])('opens prepared %s content through exact source units without a dead Content tab', async fileType => {
  mocks.api.mockImplementation(async (url: string) => url.endsWith('/sources')
    ? response({ source: { available: true, sourceRevision: 'rev1', units: [{ unitId: 'unit1', label: 'Original unit', kind: 'office' }] } })
    : response({ unit: { documentId: 'd1', sourceRevision: 'rev1', unitId: 'unit1', text: 'Original Office content' }, images: [] }));
  render(<DocumentViewer document={{ ...doc, fileType, sourceRevision: 'rev1' }} onClose={() => {}} />);
  expect(screen.queryByRole('button', { name: 'Content' })).toBeNull();
  fireEvent.click(await screen.findByRole('button', { name: 'Original unit' }));
  await screen.findByText('Original Office content');
  expect(mocks.api.mock.calls.every(([url]) => !url.includes('/detail/'))).toBe(true);
});

it('discards late Office unit lists on document and account changes', async () => {
  const old = deferred<any>();
  mocks.api.mockReturnValueOnce(old.promise).mockResolvedValue(response({ source: { available: true, sourceRevision: 'rev2', units: [{ unitId: 'new', label: 'Current unit', kind: 'office' }] } }));
  const view = render(<DocumentViewer document={{ ...doc, fileType: 'pptx', sourceRevision: 'rev1' }} onClose={() => {}} />);
  const signal = mocks.api.mock.calls[0][1].signal;
  mocks.user = { uid: 'u2' };
  view.rerender(<DocumentViewer document={{ ...doc, id: 'd2', courseId: 'c2', fileType: 'pptx', sourceRevision: 'rev2' }} onClose={() => {}} />);
  await screen.findByRole('button', { name: 'Current unit' });
  await act(async () => old.resolve(response({ source: { available: true, sourceRevision: 'rev1', units: [{ unitId: 'old', label: 'Old private unit', kind: 'office' }] } })));
  expect(signal.aborted).toBe(true);
  expect(screen.queryByRole('button', { name: 'Old private unit' })).toBeNull();
  mocks.user = { uid: 'u1' };
});
