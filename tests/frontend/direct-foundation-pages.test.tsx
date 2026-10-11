import React from "react";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import ExamPage from "../../src/app/course/[id]/exam/page";
import SummaryPage from "../../src/app/course/[id]/summary/page";
import FlashcardsPage from "../../src/app/course/[id]/flashcards/page";
import TutorPage from "../../src/app/course/[id]/tutor/page";

const mocks = vi.hoisted(() => ({
  api: vi.fn(),
  user: { uid: "u1" },
  router: { push: vi.fn() },
  course: { id: "c1", userId: "u1", code: "CS", title: "Course", color: "sage" },
  foundation: {
    ready: false, state: "confirmation_required", revision: "revision-1",
    documentCount: 1, completedCount: 1, pendingCount: 0, failedCount: 0,
    message: "Confirm that all lecture documents are uploaded.",
  },
  search: "",
}));
vi.mock("@/lib/api", () => ({
  API_URL: "http://127.0.0.1:8000",
  apiFetch: mocks.api,
  apiJson: async (url: string, init?: RequestInit) => {
    const res = await mocks.api(url, init);
    const data = await res.json();
    if (!res.ok) throw new Error(data?.detail || `Request failed (${res.status})`);
    return data;
  },
}));
vi.mock("@/lib/auth-context", () => ({ useAuth: () => ({ user: mocks.user, loading: false }) }));
vi.mock("@/lib/firestore-helpers", () => ({ getCourse: async () => mocks.course, getUserCourses: async () => [mocks.course] }));
vi.mock("@/lib/activity", () => ({ useTrackRecent: () => {} }));
vi.mock("@/components/Navbar", () => ({ default: () => null }));
vi.mock("@/components/Sidebar", () => ({ default: () => null }));
vi.mock("@/components/BookmarkButton", () => ({ default: () => null }));
vi.mock("next/navigation", () => ({ useParams: () => ({ id: "c1" }), useSearchParams: () => new URLSearchParams(mocks.search), useRouter: () => mocks.router }));
vi.mock("next/link", () => ({ default: ({ children, ...props }: any) => <a {...props}>{children}</a> }));

const response = (data: unknown, status = 200) => ({ ok: status < 400, status, json: async () => data });
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => { resolve = r; });
  return { promise, resolve };
}
const pages = [
  ["exam", ExamPage, /generate exam/i],
  ["summary", SummaryPage, /generate summary/i],
  ["flashcards", FlashcardsPage, /generate flashcards/i],
  ["tutor", TutorPage, /explain the hardest concept simply/i],
] as const;
const generationPages = pages.slice(0, 3);
const agentRequests = () => mocks.api.mock.calls.filter(([, init]) => init?.method === "POST");
const foundationReads = () => mocks.api.mock.calls.filter(([url]) => url.endsWith("/foundation"));

beforeEach(() => {
  vi.clearAllMocks();
  mocks.search = "";
  mocks.foundation = {
    ready: false, state: "confirmation_required", revision: "revision-1",
    documentCount: 1, completedCount: 1, pendingCount: 0, failedCount: 0,
    message: "Confirm that all lecture documents are uploaded.",
  };
  HTMLElement.prototype.scrollTo = vi.fn();
  mocks.api.mockImplementation(async (url: string, init?: RequestInit) => {
    if (url.endsWith("/foundation")) return response(mocks.foundation);
    if (init?.method === "POST") return new Promise(() => {});
    if (url.includes("/documents/")) return response({ documents: [{ id: "d1", title: "Lecture one", status: "completed", fileType: "txt", analysis: { topics: ["Matrices"] } }] });
    return response({});
  });
});
afterEach(cleanup);

describe("direct study-page foundation gates", () => {
  it.each(pages)("preserves a pending %s request through an unchanged background check", async (_, Page, actionName) => {
    mocks.foundation = { ...mocks.foundation, ready: true, state: "ready" };
    const pending = deferred<any>();
    const check = deferred<any>();
    let signal: AbortSignal | undefined;
    let reads = 0;
    const normalApi = mocks.api.getMockImplementation()!;
    mocks.api.mockImplementation(async (url: string, init?: RequestInit) => {
      if (init?.method === "POST") { signal = init.signal as AbortSignal; return pending.promise; }
      if (url.endsWith('/foundation') && ++reads > 1) return check.promise;
      return normalApi(url, init);
    });
    render(<Page />);
    fireEvent.click(await screen.findByRole('button', { name: actionName }));
    await waitFor(() => expect(signal).toBeDefined());
    fireEvent(window, new Event('focus'));
    await waitFor(() => expect(reads).toBe(2));
    expect(signal?.aborted).toBe(false);
    await act(async () => check.resolve(response(mocks.foundation)));
    expect(signal?.aborted).toBe(false);
    expect(agentRequests()).toHaveLength(1);
  });

  it.each(pages)("keeps %s actions inaccessible until the complete foundation is confirmed", async (_, Page, actionName) => {
    render(<Page />);
    const back = await screen.findByRole("link", { name: /back to course/i });
    expect(back.getAttribute("href")).toBe("/course/c1");
    expect(screen.getByRole("link", { name: /lecture documents/i }).getAttribute("href")).toBe("/course/c1?section=documents");
    expect(screen.queryByRole("button", { name: actionName })).toBeNull();
    expect(agentRequests()).toHaveLength(0);
  });

  it.each(pages)("does not expose %s actions while foundation status is still unknown", async (_, Page, actionName) => {
    const pending = deferred<any>();
    const normalApi = mocks.api.getMockImplementation()!;
    mocks.api.mockImplementation((url: string, init?: RequestInit) => url.endsWith("/foundation") ? pending.promise : normalApi(url, init));
    render(<Page />);
    await screen.findByRole("link", { name: /back to course/i });
    expect(screen.queryByRole("button", { name: actionName })).toBeNull();
    expect(agentRequests()).toHaveLength(0);
    await act(async () => pending.resolve(response({ ...mocks.foundation, ready: true, state: "ready" })));
    fireEvent.click(await screen.findByRole("button", { name: actionName }));
    await waitFor(() => expect(agentRequests()).toHaveLength(1));
  });

  it.each(pages)("refreshes %s readiness after a stale backend refusal", async (_, Page, actionName) => {
    mocks.foundation = { ...mocks.foundation, ready: true, state: "ready" };
    const normalApi = mocks.api.getMockImplementation()!;
    mocks.api.mockImplementation(async (url: string, init?: RequestInit) => {
      if (init?.method === "POST") {
        mocks.foundation = { ...mocks.foundation, ready: false, state: "processing", pendingCount: 1, message: "Lecture document analysis is pending." };
        return response({ detail: "Lecture documents must be analyzed and confirmed first." }, 409);
      }
      return normalApi(url, init);
    });
    render(<Page />);
    fireEvent.click(await screen.findByRole("button", { name: actionName }));
    await screen.findByRole("link", { name: /back to course/i });
    expect(foundationReads().length).toBeGreaterThanOrEqual(2);
    expect(screen.queryByRole("button", { name: actionName })).toBeNull();
    expect(agentRequests()).toHaveLength(1);
  });

  it.each(pages)("aborts a pending %s action when a refresh revokes readiness", async (_, Page, actionName) => {
    mocks.foundation = { ...mocks.foundation, ready: true, state: "ready" };
    const pending = deferred<any>();
    let signal: AbortSignal | undefined;
    const normalApi = mocks.api.getMockImplementation()!;
    mocks.api.mockImplementation(async (url: string, init?: RequestInit) => {
      if (init?.method === "POST") { signal = init.signal as AbortSignal; return pending.promise; }
      return normalApi(url, init);
    });
    render(<Page />);
    fireEvent.click(await screen.findByRole("button", { name: actionName }));
    await waitFor(() => expect(signal).toBeDefined());
    mocks.foundation = { ...mocks.foundation, ready: false, state: "processing", pendingCount: 1 };
    fireEvent(window, new Event("focus"));
    await screen.findByRole("link", { name: /back to course/i });
    await waitFor(() => expect(signal?.aborted).toBe(true));
    mocks.foundation = { ...mocks.foundation, ready: true, state: "ready", pendingCount: 0 };
    fireEvent(window, new Event("focus"));
    await screen.findByRole("button", { name: actionName });
    await act(async () => pending.resolve(response({
      doc_id: "stale-output", title: "Stale generated output", reply: "Stale generated output", chat_id: "stale-chat",
      overview: "Stale generated output", sections: [], cards: [{ front: "Stale generated output", back: "Stale answer" }],
    })));
    expect(screen.queryByText("Stale generated output")).toBeNull();
    expect(mocks.router.push).not.toHaveBeenCalled();
    expect(agentRequests()).toHaveLength(1);
  });

  it.each(pages)("keeps %s locked when the foundation request fails", async (_, Page, actionName) => {
    const normalApi = mocks.api.getMockImplementation()!;
    mocks.api.mockImplementation((url: string, init?: RequestInit) => url.endsWith("/foundation")
      ? Promise.resolve(response({ detail: "Foundation status unavailable" }, 503))
      : normalApi(url, init));
    render(<Page />);
    expect((await screen.findByRole("alert")).textContent).toBe("Foundation status unavailable");
    expect(screen.queryByRole("button", { name: actionName })).toBeNull();
    expect(screen.getByRole("link", { name: /lecture documents/i }).getAttribute("href")).toBe("/course/c1?section=documents");
    expect(agentRequests()).toHaveLength(0);
  });

  it.each(pages)("preserves a %s conflict error when the foundation is still ready", async (kind, Page, actionName) => {
    mocks.foundation = { ...mocks.foundation, ready: true, state: "ready" };
    const check = deferred<any>();
    let checks = 0;
    const normalApi = mocks.api.getMockImplementation()!;
    mocks.api.mockImplementation(async (url: string, init?: RequestInit) => {
      if (url.endsWith("/foundation") && ++checks > 1) return check.promise;
      if (init?.method === "POST") return response({ detail: "Selected source changed. Please retry." }, 409);
      return normalApi(url, init);
    });
    render(<Page />);
    fireEvent.click(await screen.findByRole("button", { name: actionName }));
    await screen.findByRole("link", { name: /back to course/i });
    await act(async () => check.resolve(response(mocks.foundation)));
    expect(await screen.findByText(kind === "tutor"
      ? "This conversation changed. Reopen it from History, then send your draft again."
      : "Selected source changed. Please retry.")).toBeTruthy();
    expect(agentRequests()).toHaveLength(1);
  });

  it.each(generationPages)("requires at least one selected lecture document for %s generation", async (_, Page, actionName) => {
    mocks.foundation = { ...mocks.foundation, ready: true, state: "ready" };
    render(<Page />);
    const generate = await screen.findByRole("button", { name: actionName });
    fireEvent.click(screen.getByRole("checkbox", { name: /lecture one/i }));
    expect((generate as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(generate);
    expect(agentRequests()).toHaveLength(0);
  });

  it.each(generationPages)("keeps the selected lecture scope in the %s generation request", async (_, Page, actionName) => {
    mocks.foundation = { ...mocks.foundation, ready: true, state: "ready", documentCount: 2, completedCount: 2 };
    const normalApi = mocks.api.getMockImplementation()!;
    mocks.api.mockImplementation((url: string, init?: RequestInit) => url.includes("/documents/")
      ? Promise.resolve(response({ documents: [
        { id: "d1", title: "Lecture one", status: "completed", fileType: "txt", analysis: { topics: ["Matrices"] } },
        { id: "d2", title: "Lecture two", status: "completed", fileType: "txt", analysis: { topics: ["Probability"] } },
      ] }))
      : normalApi(url, init));
    render(<Page />);
    const generate = await screen.findByRole("button", { name: actionName });
    fireEvent.click(screen.getByRole("checkbox", { name: /lecture two/i }));
    fireEvent.click(generate);
    await waitFor(() => expect(agentRequests()).toHaveLength(1));
    expect(JSON.parse(agentRequests()[0][1].body as string).document_ids).toEqual(["d1"]);
  });

  it.each([["summary", SummaryPage], ["flashcards", FlashcardsPage]] as const)("keeps a saved %s readable while the foundation is locked", async (kind, Page) => {
    mocks.search = `${kind}=saved-1`;
    const normalApi = mocks.api.getMockImplementation()!;
    mocks.api.mockImplementation(async (url: string, init?: RequestInit) => {
      if (url.includes("/detail/")) return response(kind === "summary"
        ? { summary: { title: "Saved chapter", overview: "Existing content", sections: [{ heading: "Matrices", content: "Saved explanation" }] } }
        : { set: { title: "Saved chapter", cards: [{ front: "Saved question", back: "Saved answer" }] } });
      return normalApi(url, init);
    });
    render(<Page />);
    await screen.findByText(kind === "summary" ? "Saved explanation" : "Saved question");
    expect(agentRequests()).toHaveLength(0);
  });
});
