import React from "react";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import FlashcardsPage from "../../src/app/course/[id]/flashcards/page";
import ExamAnswerPage from "../../src/app/course/[id]/exam/[examId]/page";
import TutorPage from "../../src/app/course/[id]/tutor/page";
import { LanguageProvider } from "../../src/lib/i18n";

const mocks = vi.hoisted(() => ({ api: vi.fn(), object: vi.fn() }));
const course = { id: "c1", userId: "u1", code: "CS101", title: "Algorithms", color: "#526BCB" };
const user = { uid: "u1" };
vi.mock("@/lib/auth-context", () => ({ useAuth: () => ({ user, loading: false }) }));
vi.mock("@/lib/firestore-helpers", () => ({ getCourse: async () => course, getUserCourses: async () => [course] }));
vi.mock("@/lib/activity", () => ({ useTrackRecent: () => {} }));
vi.mock("@/components/Navbar", () => ({ default: () => null }));
vi.mock("@/components/Sidebar", () => ({ default: () => null }));
vi.mock("@/components/BookmarkButton", () => ({ default: () => null }));
vi.mock("next/navigation", () => ({ useParams: () => ({ id: "c1", examId: "e1" }), useSearchParams: () => new URLSearchParams(), useRouter: () => ({ push: vi.fn() }) }));
vi.mock("next/link", () => ({ default: ({ children, ...props }: any) => <a {...props}>{children}</a> }));
vi.mock("@/lib/api", () => ({ apiFetch: mocks.api, fetchObjectUrl: mocks.object, fetchFileObjectUrl: mocks.object, apiJson: async (url: string) => url.endsWith("/foundation") ? { ready: true, state: "ready", revision: "r1", documentCount: 1, completedCount: 1 } : (await mocks.api(url)).json() }));

const response = (data: unknown) => ({ ok: true, json: async () => data });
beforeEach(() => {
  vi.resetAllMocks();
  localStorage.clear();
  document.documentElement.lang = "en";
  document.documentElement.dir = "ltr";
  URL.revokeObjectURL = vi.fn();
  HTMLElement.prototype.scrollTo = vi.fn();
  mocks.object.mockResolvedValue("blob:document");
  mocks.api.mockImplementation(async (url: string) => {
    if (url.includes("/flashcards/list/")) return response({ sets: [{ id: "f1", title: "Saved cards", cardCount: 1, createdAt: 1 }] });
    if (url.includes("/flashcards/detail/")) return response({ set: { title: "Saved cards", cards: [{ front: "What is a graph?", back: "Vertices connected by edges." }] } });
    return response({});
  });
});

it("localizes tutor chrome and starter labels without changing the submitted prompt", async () => {
  localStorage.setItem("mudaris_lang", "ar");
  mocks.api.mockImplementation(async (_url: string, init?: RequestInit) => init?.method === "POST" ? response({ reply: "A course explanation" }) : response({}));
  render(<LanguageProvider><TutorPage /></LanguageProvider>);
  expect(await screen.findByRole("heading", { name: "اسألني عن CS101" })).toBeTruthy();
  expect(screen.getByText(/يعتمد على مواد مقررك/)).toBeTruthy();
  expect(screen.getByText("Enter للإرسال · Shift + Enter لسطر جديد")).toBeTruthy();
  const prompts = ["وش المواضيع اللي أركّز عليها للاختبار؟", "اشرح لي أصعب مفهوم ببساطة.", "اختبرني بثلاثة أسئلة.", "لخّص لي أهم التعاريف."];
  prompts.forEach(name => expect(screen.getByRole("button", { name })).toBeTruthy());
  fireEvent.click(screen.getByRole("button", { name: "المصادر" }));
  const sources = within(screen.getByRole("dialog", { name: "المصادر" }));
  ["المحاضرات", "التسجيلات", "الاختبارات السابقة", "التمارين"].forEach(label => expect(sources.getByText(label)).toBeTruthy());
  expect(sources.getAllByText("ما رفعت شي للحين")).toHaveLength(4);
  fireEvent.click(sources.getByRole("button", { name: "أغلق المصادر" }));
  fireEvent.click(screen.getByRole("button", { name: prompts[1] }));
  await waitFor(() => expect(mocks.api.mock.calls.some(([, init]) => init?.method === "POST")).toBe(true));
  const sent = mocks.api.mock.calls.find(([, init]) => init?.method === "POST")?.[1];
  expect(JSON.parse(sent.body).messages).toEqual([{ role: "user", content: "Explain the hardest concept simply." }]);
});

it("keeps the exam documents keyboard reachable and fetches answers only after an explicit reveal", async () => {
  mocks.api.mockResolvedValue(response({ exam: { id: "e1", courseId: "c1", examId: "Practice exam", questionStructure: [], status: "ready" } }));
  render(<ExamAnswerPage />);
  const exam = await screen.findByRole("tab", { name: "Exam" });
  const selfCheck = screen.getByRole("tab", { name: "Self-check" });
  exam.focus();
  fireEvent.keyDown(exam, { key: "End" });
  expect(document.activeElement).toBe(selfCheck);
  expect(selfCheck.getAttribute("aria-selected")).toBe("true");
  expect(mocks.object.mock.calls.some(([url]) => String(url).includes("answer-key"))).toBe(false);
  fireEvent.click(screen.getByRole("button", { name: /reveal model answers/i }));
  expect(await screen.findByRole("tab", { name: "Model answers" })).toBeTruthy();
});

it("reveals and focuses model answers after self-check with an attached solution", async () => {
  mocks.api.mockResolvedValue(response({ exam: { id: "e1", courseId: "c1", examId: "Practice exam", questionStructure: [], status: "ready", solutionPath: "solutions/work.pdf", solutionType: "pdf", solutionName: "My work" } }));
  render(<ExamAnswerPage />);
  const selfCheck = await screen.findByRole("tab", { name: "Self-check" });
  fireEvent.click(selfCheck);
  expect(selfCheck.getAttribute("aria-selected")).toBe("true");
  const reveal = screen.getByRole("button", { name: /reveal model answers/i });
  reveal.focus();
  fireEvent.click(reveal);
  const modelAnswers = await screen.findByRole("tab", { name: "Model answers" });
  expect(modelAnswers.getAttribute("aria-selected")).toBe("true");
  expect(document.activeElement).toBe(screen.getByRole("tabpanel", { name: "Model answers" }));
  expect(screen.getByTitle("Your solution")).toBeTruthy();
});

it("returns focus from the tutor source panel and preserves the explicit source selection", async () => {
  mocks.api.mockImplementation(async (url: string) => url.includes("/documents/") ? response({ documents: [{ id: "d1", title: "Graph lectures", status: "completed" }] }) : response({}));
  render(<TutorPage />);
  const sourceButton = await screen.findByRole("button", { name: "Sources" });
  sourceButton.focus();
  fireEvent.click(sourceButton);
  expect(await screen.findByRole("dialog", { name: "Sources" })).toBeTruthy();
  const lecture = screen.getByRole("button", { name: /graph lectures/i });
  fireEvent.click(lecture);
  expect(lecture.getAttribute("aria-pressed")).toBe("false");
  fireEvent.keyDown(document, { key: "Escape" });
  expect(screen.queryByRole("dialog", { name: "Sources" })).toBeNull();
  expect(document.activeElement).toBe(sourceButton);
  fireEvent.click(sourceButton);
  expect(screen.getByRole("button", { name: /graph lectures/i }).getAttribute("aria-pressed")).toBe("false");
});
afterEach(() => { cleanup(); localStorage.clear(); document.documentElement.lang = "en"; document.documentElement.dir = "ltr"; });

it("gives an empty saved deck a recoverable error instead of a blank study surface", async () => {
  mocks.api.mockImplementation(async (url: string) => url.includes("/flashcards/list/") ? response({ sets: [{ id: "f1", title: "Saved cards", cardCount: 0 }] }) : response({ set: { cards: [] } }));
  render(<FlashcardsPage />);
  fireEvent.click(await screen.findByRole("button", { name: /saved cards/i }));
  expect(await screen.findByRole("alert")).toHaveProperty("textContent", expect.stringContaining("This set has no cards"));
  fireEvent.click(screen.getByRole("button", { name: /try again/i }));
  expect(await screen.findByRole("button", { name: /saved cards/i })).toBeTruthy();
});

it("explains a zero-card generation without automatically starting another job", async () => {
  mocks.api.mockImplementation(async (url: string, init?: RequestInit) => {
    if (url.includes("/documents/")) return response({ documents: [{ id: "d1", title: "Lecture", status: "completed", fileType: "pdf" }] });
    if (init?.method === "POST") return response({ doc_id: "empty", cards: [] });
    return response({});
  });
  render(<FlashcardsPage />);
  fireEvent.click(await screen.findByRole("button", { name: /generate flashcards/i }));
  expect(await screen.findByRole("alert")).toHaveProperty("textContent", expect.stringContaining("This set has no cards"));
  fireEvent.click(screen.getByRole("button", { name: /try again/i }));
  expect(await screen.findByRole("button", { name: /generate flashcards/i })).toBeTruthy();
  expect(mocks.api.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(1);
});

it("supports a keyboard card reveal and exposes only the current side", async () => {
  render(<FlashcardsPage />);
  fireEvent.click(await screen.findByRole("button", { name: /saved cards/i }));
  const card = await screen.findByRole("button", { name: /Question What is a graph\?/i, description: /select to reveal the answer/i });
  expect(card.textContent).toContain("What is a graph?");
  expect(card.textContent).not.toContain("Vertices connected by edges.");
  expect(screen.getByRole("status").textContent).toContain("Question");
  fireEvent.keyDown(card, { key: "Enter" });
  expect(await screen.findByRole("button", { name: /Answer Vertices connected by edges\./i, description: /select to see the question/i })).toHaveProperty("textContent", expect.stringContaining("Vertices connected by edges."));
  expect(screen.getByRole("status").textContent).toContain("Answer");
  expect(screen.queryByText("What is a graph?")).toBeNull();
});
