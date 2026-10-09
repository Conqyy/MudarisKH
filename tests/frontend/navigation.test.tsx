import React from "react";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import Navbar from "../../src/components/Navbar";
import ProcessingPage from "../../src/app/lecture/[id]/processing/page";
import { LanguageProvider } from "../../src/lib/i18n";
import CreateCourseModal from "../../src/components/CreateCourseModal";
import EditCourseModal from "../../src/components/EditCourseModal";
import UploadDocumentModal from "../../src/components/UploadDocumentModal";
import UploadAudioModal from "../../src/components/UploadAudioModal";
import AudioViewer from "../../src/components/AudioViewer";
import CourseReminders from "../../src/components/CourseReminders";
import ActivityListView from "../../src/components/ActivityListView";
import WeeklySchedule from "../../src/components/WeeklySchedule";

const mocks = vi.hoisted(() => ({ api: vi.fn(), updateLecture: vi.fn(), push: vi.fn(), user: { uid: "u1", email: "student@example.com" } }));
vi.mock("@/lib/auth-context", () => ({ useAuth: () => ({ user: mocks.user, profile: { fullName: "Student" }, loading: false, signOut: vi.fn() }) }));
vi.mock("@/lib/firestore-helpers", () => ({ getLecture: async () => ({ id: "l1", courseId: "c1", userId: "u1", status: "uploaded" }), updateLecture: mocks.updateLecture }));
vi.mock("@/lib/api", () => ({ apiFetch: mocks.api, fetchObjectUrl: vi.fn() }));
vi.mock("next/navigation", () => { const router = { push: mocks.push }; return { useParams: () => ({ id: "l1" }), useRouter: () => router }; });
vi.mock("next/link", () => ({ default: ({ children, ...props }: any) => <a {...props}>{children}</a> }));
beforeEach(() => { vi.clearAllMocks(); localStorage.clear(); });
afterEach(cleanup);

it("exposes the actual language toggle and changes the document direction", async () => {
  render(<LanguageProvider><Navbar /></LanguageProvider>);
  fireEvent.click(screen.getByRole("button", { name: /switch to arabic/i }));
  await waitFor(() => expect(document.documentElement.dir).toBe("rtl"));
  expect(localStorage.getItem("mudaris_lang")).toBe("ar");
  fireEvent.click(screen.getByRole("button", { name: /switch to english/i }));
  await waitFor(() => expect(document.documentElement.dir).toBe("ltr"));
});

it("provides Recent and Bookmarked navigation in the account menu", () => {
  render(<Navbar />);
  fireEvent.click(screen.getByTitle("Account"));
  expect(screen.getByRole("link", { name: /recent/i }).getAttribute("href")).toBe("/dashboard/recent");
  expect(screen.getByRole("link", { name: /bookmarked/i }).getAttribute("href")).toBe("/dashboard/bookmarked");
});

it("replaces the legacy simulated processing route with a usable destination", async () => {
  render(<ProcessingPage />);
  await screen.findByText(/legacy.*processing|processing.*retired/i);
  expect(screen.getByRole("link", { name: /back to dashboard/i }).getAttribute("href")).toBe("/dashboard");
  expect(mocks.updateLecture).not.toHaveBeenCalled();
  expect(mocks.push).not.toHaveBeenCalledWith("/lecture/l1");
});

it.each([
  ["create course", CreateCourseModal, { existingCoursesCount: 0 }],
  ["edit course", EditCourseModal, { course: { id: "c1", code: "CS", title: "Course", instructor: "Teacher", color: "sage" } }],
  ["upload document", UploadDocumentModal, { courseId: "c1" }],
  ["upload recording", UploadAudioModal, { courseId: "c1" }],
  ["audio viewer", AudioViewer, { recording: { id: "a1", title: "Audio", uploadedAt: 1 } }],
] as const)("supports Escape, focus containment and restoration in %s", (_, Component, props) => {
  const close = vi.fn();
  const opener = document.createElement("button"); document.body.append(opener); opener.focus();
  render(React.createElement(Component as any, { ...props, onClose: close, onSuccess: vi.fn() }));
  const dialog = screen.getByRole("dialog");
  expect(dialog.contains(document.activeElement)).toBe(true);
  fireEvent.keyDown(document, { key: "Escape" }); expect(close).toHaveBeenCalledOnce();
  cleanup(); expect(document.activeElement).toBe(opener); opener.remove();
});

it("associates course form labels with their input controls", () => {
  render(<CreateCourseModal onClose={() => {}} onSuccess={() => {}} existingCoursesCount={0} />);
  expect(screen.getByLabelText(/course code/i).tagName).toBe("INPUT");
  expect(screen.getByLabelText(/course title/i).tagName).toBe("INPUT");
});

it("keeps the reminder form and draft open when persistence fails", async () => {
  render(<CourseReminders reminders={[]} onChange={async () => { throw new Error("offline"); }} />);
  fireEvent.click(screen.getByRole("button", { name: /add your first/i }));
  const title = screen.getByPlaceholderText(/quiz 2/i);
  fireEvent.change(title, { target: { value: "Exam revision" } });
  fireEvent.click(screen.getByRole("button", { name: /save|add reminder/i }));
  await screen.findByText(/offline|could not save/i);
  expect(screen.getByRole("dialog").contains(title)).toBe(true);
  expect((title as HTMLInputElement).value).toBe("Exam revision");
});

it("keeps activity actions outside the navigation link", () => {
  render(<ActivityListView items={[{ id: "s1", kind: "summary", title: "My summary", href: "/course/c1/summary?summary=s1", ts: 1 }]} mode="recent" />);
  const star = screen.getByTitle("Add bookmark");
  expect(star.closest("a")).toBeNull();
  fireEvent.click(star);
  expect(JSON.parse(localStorage.getItem("mudaris.bookmarks.u1") || "[]")[0].id).toBe("s1");
});

it("shows schedule load failures and permits a successful retry", async () => {
  mocks.api.mockResolvedValueOnce({ ok: false, status: 500, json: async () => ({ detail: "offline" }) });
  render(<WeeklySchedule courses={[]} userId="u1" />);
  await screen.findByRole("alert");
  mocks.api.mockResolvedValue({ ok: true, json: async () => ({ entries: [] }) });
  fireEvent.click(screen.getByRole("button", { name: /retry schedule/i }));
  await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
});
