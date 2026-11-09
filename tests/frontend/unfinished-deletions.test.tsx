import React from "react";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import CoursePage from "../../src/app/course/[id]/page";

const mocks = vi.hoisted(() => ({ api: vi.fn(), user: { uid: "u1" }, course: { id: "c1", userId: "u1", title: "Algorithms", code: "CS", color: "sage" } }));
vi.mock("@/lib/api", () => ({ API_URL: "http://127.0.0.1:8000", apiFetch: mocks.api, apiJson: async (url: string, init?: RequestInit) => { const result = await mocks.api(url, init); const data = await result.json(); if (!result.ok) throw new Error(data.detail); return data; } }));
vi.mock("@/lib/auth-context", () => ({ useAuth: () => ({ user: mocks.user, loading: false }) }));
vi.mock("@/lib/firestore-helpers", () => ({ getCourse: async () => mocks.course, getUserCourses: async () => [mocks.course], updateCourse: vi.fn() }));
vi.mock("@/lib/activity", () => ({ useTrackRecent: () => {} }));
vi.mock("@/components/Navbar", () => ({ default: () => null }));
vi.mock("@/components/Sidebar", () => ({ default: () => null }));
vi.mock("@/components/BookmarkButton", () => ({ default: () => null }));
vi.mock("@/components/SupportingMaterialAction", () => ({ default: () => null }));
vi.mock("next/navigation", () => ({ useParams: () => ({ id: "c1" }), useSearchParams: () => new URLSearchParams("view=materials"), useRouter: () => ({ push: vi.fn() }) }));
vi.mock("next/link", () => ({ default: ({ children, ...props }: any) => <a {...props}>{children}</a> }));

const response = (data: unknown, status = 200) => ({ ok: status < 400, status, json: async () => data });
const tutorial = { id: "t1", title: "Tutorial 3", status: "completed", jobId: "j1", sourceRevision: "s1", reportRevision: "r1", stale: false, legacy: false, uploadedAt: 1 };

let deleteResponses: number[] = [];
beforeEach(() => {
  vi.resetAllMocks();
  deleteResponses = [];
  mocks.api.mockImplementation(async (url: string, init?: RequestInit) => {
    if (init?.method === "DELETE") return response({}, deleteResponses.shift() ?? 200);
    if (url.endsWith("/foundation")) return response({ ready: true, state: "ready", revision: "r1", documentCount: 1, completedCount: 1 });
    if (url.includes("/documents/")) return response({ documents: [] });
    if (url.includes("/tutorials/")) return response({ tutorials: [tutorial], unfinished_deletions: [{ id: "t9", kind: "tutorial", courseId: "c1", title: "Tutorial 4 (1)" }] });
    if (url.includes("/audio/")) return response({ audio_recordings: [], unfinished_deletions: [{ id: "n1", kind: "notes", courseId: "c1", title: null }] });
    if (url.includes("/historical-exams/")) return response({ historical_exams: [], unfinished_deletions: [] });
    return response({});
  });
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

it("names partly deleted materials apart from usable ones and finishes them through their DELETE endpoint", async () => {
  vi.spyOn(console, "error").mockImplementation(() => {});
  render(<CoursePage />);
  const notice = await screen.findByRole("region", { name: "Unfinished deletions" });
  expect(within(notice).getByText("Tutorial 4 (1)")).toBeTruthy();
  expect(within(notice).getByText("Untitled material")).toBeTruthy();

  // The stalled tutorial is not listed or counted as a usable tutorial.
  const tutorials = screen.getByRole("region", { name: "Tutorials" });
  expect(within(tutorials).queryByText("Tutorial 4 (1)")).toBeNull();
  expect(within(tutorials).getByText("Tutorial 3")).toBeTruthy();
  expect(screen.getByRole("navigation", { name: "Material groups" }).querySelector('a[href="#tutorials"] span')?.textContent).toBe("1");

  // A failed attempt keeps the item offered for another try.
  deleteResponses = [503];
  fireEvent.click(within(notice).getByRole("button", { name: "Finish deleting: Tutorial 4 (1)" }));
  expect((await within(notice).findByRole("alert")).textContent).toBe("The deletion still could not finish. Please retry.");
  expect(within(notice).getByText("Tutorial 4 (1)")).toBeTruthy();

  fireEvent.click(within(notice).getByRole("button", { name: "Finish deleting: Tutorial 4 (1)" }));
  await waitFor(() => expect(within(notice).queryByText("Tutorial 4 (1)")).toBeNull());
  expect(within(notice).queryByRole("alert")).toBeNull();
  const deletes = mocks.api.mock.calls.filter(([, init]) => init?.method === "DELETE").map(([url]) => url);
  expect(deletes).toEqual(["http://127.0.0.1:8000/api/tutorials/t9", "http://127.0.0.1:8000/api/tutorials/t9"]);

  // Typed notes finish through the audio route; an already-gone row counts as finished.
  deleteResponses = [404];
  fireEvent.click(within(notice).getByRole("button", { name: "Finish deleting: Untitled material" }));
  await waitFor(() => expect(screen.queryByRole("region", { name: "Unfinished deletions" })).toBeNull());
  expect(mocks.api.mock.calls.at(-1)?.[0]).toBe("http://127.0.0.1:8000/api/audio/n1");
});
