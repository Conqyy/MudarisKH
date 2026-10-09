import React from "react";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import DocumentViewer from "../../src/components/DocumentViewer";
import ExamPage from "../../src/app/course/[id]/exam/[examId]/page";
import TutorPage from "../../src/app/course/[id]/tutor/page";
import SummaryPage from "../../src/app/course/[id]/summary/page";
import FlashcardsPage from "../../src/app/course/[id]/flashcards/page";
import ReorderableList from "../../src/components/ReorderableList";
import CoursePage from "../../src/app/course/[id]/page";

const mocks = vi.hoisted(() => ({ api: vi.fn(), file: vi.fn(), object: vi.fn(), recent: vi.fn(), updateCourse: vi.fn(), user: { uid: "u1" }, course: { id: "c1", userId: "u1", code: "CS", name: "Course", color: "sage" } }));
vi.mock("@/lib/api", () => ({ apiFetch: mocks.api, apiJson: async (url: string, init?: RequestInit) => { const res = await mocks.api(url, init); const data = await res.json(); if (!res.ok) throw new Error(data?.detail || `Request failed (${res.status})`); return data; }, fetchFileObjectUrl: mocks.file, fetchObjectUrl: mocks.object }));
vi.mock("@/lib/auth-context", () => ({ useAuth: () => ({ user: mocks.user, loading: false }) }));
vi.mock("@/lib/firestore-helpers", () => ({ getCourse: async () => mocks.course, getUserCourses: async () => [mocks.course], updateCourse: mocks.updateCourse }));
vi.mock("@/lib/activity", () => ({ useTrackRecent: mocks.recent }));
vi.mock("@/components/Navbar", () => ({ default: () => null }));
vi.mock("@/components/Sidebar", () => ({ default: () => null }));
vi.mock("@/components/BookmarkButton", () => ({ default: () => null }));
vi.mock("next/navigation", () => ({ useParams: () => ({ id: "c1", examId: "e1" }), useSearchParams: () => new URLSearchParams(), useRouter: () => ({ push: vi.fn() }) }));
vi.mock("next/link", () => ({ default: ({ children, ...props }: any) => <a {...props}>{children}</a> }));

const response = (data: unknown, ok = true) => ({ ok, status: ok ? 200 : 500, json: async () => data });
const doc: any = { id: "d1", courseId: "c1", title: "Notes", fileType: "txt", fileSize: 15, uploadedAt: Date.now() };
function deferred<T>() { let resolve!: (v: T) => void; const promise = new Promise<T>(r => { resolve = r; }); return { promise, resolve }; }

beforeEach(() => {
  vi.resetAllMocks();
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
    mocks.file.mockImplementation((path: string) => path === "old.pdf" ? old.promise : Promise.resolve("blob:new"));
    const { rerender, unmount } = render(<DocumentViewer document={{ ...doc, fileType: "pdf", storagePath: "old.pdf" }} onClose={() => {}} />);
    rerender(<DocumentViewer document={{ ...doc, id: "d2", title: "New notes", fileType: "pdf", storagePath: "new.pdf" }} onClose={() => {}} />);
    await screen.findByTitle("New notes");
    await act(async () => old.resolve("blob:old"));
    expect(screen.getByTitle("New notes").getAttribute("src")).toBe("blob:new");
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:old");
    unmount(); expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:new");
  });
  it("keeps failed text requests terminal until retry and then displays recovered content", async () => {
    mocks.api.mockRejectedValueOnce(new Error("offline")).mockResolvedValueOnce(response({ document: { extractedText: "Recovered notes" } }));
    render(<DocumentViewer document={doc} onClose={() => {}} />);
    await screen.findByRole("alert");
    expect(mocks.api).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: /retry content/i }));
    await screen.findByText("Recovered notes");
    expect(mocks.api).toHaveBeenCalledTimes(2);
  });
  it("supports Escape and restores focus when the viewer closes", async () => {
    const onClose = vi.fn();
    const opener = document.createElement("button"); document.body.append(opener); opener.focus();
    render(<DocumentViewer document={{ ...doc, extractedText: "Ready" }} onClose={onClose} />);
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
  it("does not refetch empty extracted text until an explicit retry", async () => {
    mocks.api.mockResolvedValue(response({ document: { extractedText: "" } }));
    render(<DocumentViewer document={doc} onClose={() => {}} />);
    await screen.findByText("No content available for this document.");
    expect(mocks.api).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: /retry content/i }));
    await waitFor(() => expect(mocks.api).toHaveBeenCalledTimes(2));
  });
  it("shows a PDF failure and retries once", async () => {
    mocks.file.mockRejectedValueOnce(new Error("offline")).mockResolvedValueOnce("blob:doc");
    render(<DocumentViewer document={{ ...doc, fileType: "pdf", storagePath: "safe.pdf" }} onClose={() => {}} />);
    fireEvent.click(await screen.findByRole("button", { name: /retry pdf/i }));
    await screen.findByTitle("Notes");
    expect(mocks.file).toHaveBeenCalledTimes(2);
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
