import React from "react";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const fake = vi.hoisted(() => ({
  user: { uid: "student" },
  loadError: null as Error | null,
  saveError: null as Error | null,
  countsGate: null as Promise<void> | null,
  saveGate: null as Promise<void> | null,
  queriedUsers: [] as string[],
}));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock("../../src/lib/auth-context", () => ({ useAuth: () => ({ user: fake.user, profile: { fullName: "Khalid" }, loading: false }) }));
vi.mock("../../src/lib/i18n", () => ({ useLang: () => ({ t: (value: string) => value }) }));
vi.mock("../../src/components/Navbar", () => ({ default: () => null }));
vi.mock("../../src/components/Sidebar", () => ({ default: () => null }));
vi.mock("../../src/components/CreateCourseModal", () => ({ default: () => null }));
vi.mock("../../src/components/WeeklySchedule", () => ({ default: () => null }));
vi.mock("../../src/lib/firestore-helpers", () => ({
  getUserCourses: async (uid: string) => {
    fake.queriedUsers.push(uid);
    if (fake.loadError) throw fake.loadError;
    return [{ id: uid === "student" ? "course" : "replacement-course", code: "CS101", title: uid === "student" ? "Algorithms" : "Replacement course", instructor: "Professor", color: "red", userId: uid, createdAt: 1,
      reminders: [{ id: "reminder", title: "Review sorting", type: "quiz", done: false, createdAt: 1 }] }];
  },
  updateCourse: async (_id: string, data: unknown) => {
    if (fake.saveGate) await fake.saveGate;
    if (fake.saveError) throw fake.saveError; return data;
  },
  deleteCourse: async () => { if (fake.saveError) throw fake.saveError; },
}));
vi.mock("../../src/lib/api", () => ({
  apiFetch: async (url: string) => {
    if (fake.countsGate) await fake.countsGate;
    return { ok: true, json: async () => url.includes("intelligence") ? { counts: {} } : { exams: [] } };
  },
}));

import DashboardPage from "../../src/app/dashboard/page";

beforeEach(() => {
  fake.loadError = null; fake.saveError = null; fake.countsGate = null;
  fake.user = { uid: "student" }; fake.saveGate = null; fake.queriedUsers = [];
  vi.spyOn(console, "error").mockImplementation(() => {});
  vi.spyOn(window, "confirm").mockReturnValue(true);
  vi.spyOn(window, "alert").mockImplementation(() => {});
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("dashboard data lifecycle", () => {
  it("renders courses while their optional statistics are still loading", async () => {
    let release!: () => void;
    fake.countsGate = new Promise<void>((resolve) => { release = resolve; });
    render(<DashboardPage />);
    try {
      await waitFor(() => { expect(screen.queryByText("Algorithms")).not.toBeNull(); });
    } finally {
      await act(async () => { release(); });
    }
  });

  it("shows a retry action instead of an empty account when loading courses fails", async () => {
    fake.loadError = new Error("Course data unavailable");
    render(<DashboardPage />);
    await waitFor(() => { expect(screen.queryByRole("alert")).not.toBeNull(); });
    expect(screen.queryByText("No courses yet")).toBeNull();
    fake.loadError = null;
    fireEvent.click(screen.getByRole("button", { name: /retry/i }));
    await screen.findByText("Algorithms");
  });

  it("keeps a reminder open and exposes the error when completing it cannot persist", async () => {
    fake.saveError = new Error("Could not save reminder");
    render(<DashboardPage />);
    await screen.findByText("Review sorting");
    fireEvent.click(screen.getByTitle("Mark as done"));
    await waitFor(() => { expect(screen.queryByRole("alert")).not.toBeNull(); });
    expect(screen.queryByText("Review sorting")).not.toBeNull();
    expect(screen.queryByTitle("Mark as done")).not.toBeNull();
  });

  it("retains a course and reports the real purge error when deletion fails", async () => {
    fake.saveError = new Error("Storage cleanup failed; retry deletion");
    render(<DashboardPage />);
    await screen.findByText("Algorithms");
    fireEvent.click(screen.getByTitle("Delete course"));
    await waitFor(() => { expect(window.alert).toHaveBeenCalledWith("Storage cleanup failed; retry deletion"); });
    expect(screen.queryByText("Algorithms")).not.toBeNull();
  });

  it("does not reload the previous account after its archive save completes late", async () => {
    let release!: () => void;
    fake.saveGate = new Promise<void>((resolve) => { release = resolve; });
    const page = render(<DashboardPage />);
    await screen.findByText("Algorithms");
    fireEvent.click(screen.getByTitle("Archive course"));
    fake.user = { uid: "replacement" };
    page.rerender(<DashboardPage />);
    await screen.findByText("Replacement course");
    fake.queriedUsers = [];
    await act(async () => { release(); });
    expect(fake.queriedUsers).not.toContain("student");
    expect(screen.queryByText("Algorithms")).toBeNull();
    expect(screen.queryByText("Replacement course")).not.toBeNull();
  });
});
