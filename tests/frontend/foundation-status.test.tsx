import React from "react";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const fake = vi.hoisted(() => ({ user: { uid: "student" }, api: vi.fn() }));
vi.mock("@/lib/auth-context", () => ({ useAuth: () => ({ user: fake.user, loading: false }) }));
vi.mock("@/lib/api", () => ({ apiJson: fake.api }));

import { useCourseFoundation } from "../../src/hooks/useCourseFoundation";

const ready = { ready: true, state: "ready", revision: "current", documentCount: 1, completedCount: 1, pendingCount: 0, failedCount: 0, message: "Confirmed" };
function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>(r => { resolve = r; }); return { promise, resolve }; }
function Probe({ courseId }: { courseId: string }) {
  const { foundation, loading, error, refresh, confirm } = useCourseFoundation(courseId);
  return <><p role="status">{loading ? "Checking" : foundation?.ready ? "Unlocked" : "Locked"}</p><p>Revision: {foundation?.revision || "unknown"}</p>{error && <p role="alert">{error}</p>}<button onClick={() => void refresh()}>Refresh</button>{foundation?.state === "confirmation_required" && <button onClick={() => void confirm()}>Confirm</button>}</>;
}
beforeEach(() => { fake.api.mockReset(); fake.user = { uid: "student" }; });
afterEach(() => { cleanup(); vi.useRealTimers(); });

describe("foundation request lifecycle", () => {
  it("stays locked before an authoritative response and after a failed refresh", async () => {
    const pending = deferred<typeof ready>();
    fake.api.mockReturnValueOnce(pending.promise);
    render(<Probe courseId="first" />);
    expect(screen.getByRole("status").textContent).toBe("Checking");
    expect(screen.queryByText("Revision: unknown")).not.toBeNull();
    await act(async () => pending.resolve(ready));
    expect(screen.getByRole("status").textContent).toBe("Unlocked");
    fake.api.mockRejectedValueOnce(new Error("offline"));
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    expect(screen.getByRole("status").textContent).toBe("Checking");
    await screen.findByRole("alert");
    expect(screen.getByRole("status").textContent).toBe("Locked");
  });

  it("aborts a previous course check and ignores its late ready result", async () => {
    const old = deferred<typeof ready>();
    let oldSignal!: AbortSignal;
    fake.api.mockImplementation((url: string, init: RequestInit) => {
      if (url.includes("/first/")) { oldSignal = init.signal as AbortSignal; return old.promise; }
      return Promise.resolve({ ...ready, ready: false, state: "missing", revision: "new" });
    });
    const page = render(<Probe courseId="first" />);
    page.rerender(<Probe courseId="second" />);
    await waitFor(() => expect(screen.getByRole("status").textContent).toBe("Locked"));
    expect(oldSignal.aborted).toBe(true);
    await act(async () => old.resolve(ready));
    expect(screen.getByRole("status").textContent).toBe("Locked");
  });

  it("does not carry readiness between signed-in accounts", async () => {
    const next = deferred<typeof ready>();
    fake.api.mockResolvedValueOnce(ready).mockReturnValueOnce(next.promise);
    const page = render(<Probe courseId="course" />);
    await waitFor(() => expect(screen.getByRole("status").textContent).toBe("Unlocked"));
    fake.user = { uid: "replacement" };
    page.rerender(<Probe courseId="course" />);
    expect(screen.getByRole("status").textContent).toBe("Checking");
    await act(async () => next.resolve({ ...ready, ready: false, state: "missing" }));
    expect(screen.getByRole("status").textContent).toBe("Locked");
  });

  it("aborts an unfinished status request when the page unmounts", () => {
    let signal!: AbortSignal;
    fake.api.mockImplementation((_url: string, init: RequestInit) => { signal = init.signal as AbortSignal; return new Promise(() => {}); });
    const page = render(<Probe courseId="course" />);
    page.unmount();
    expect(signal.aborted).toBe(true);
  });

  it("recovers processing status through polling without requiring navigation", async () => {
    vi.useFakeTimers();
    fake.api.mockResolvedValueOnce({ ...ready, ready: false, state: "processing", pendingCount: 1, completedCount: 0 }).mockResolvedValue(ready);
    render(<Probe courseId="course" />);
    await act(async () => {});
    expect(screen.getByRole("status").textContent).toBe("Locked");
    await act(async () => vi.advanceTimersByTimeAsync(5000));
    expect(screen.getByRole("status").textContent).toBe("Unlocked");
  });

  it("rechecks the foundation after confirmation when another document changes the course", async () => {
    fake.api.mockResolvedValueOnce({ ...ready, ready: false, state: "confirmation_required" })
      .mockResolvedValueOnce(ready)
      .mockResolvedValueOnce({ ...ready, ready: false, state: "processing", revision: "changed", documentCount: 2, pendingCount: 1 });
    render(<Probe courseId="course" />);
    fireEvent.click(await screen.findByRole("button", { name: "Confirm" }));
    await waitFor(() => expect(screen.getByRole("status").textContent).toBe("Locked"));
    expect(screen.queryByRole("button", { name: "Confirm" })).toBeNull();
  });

  it("resumes bounded processing checks after an explicit retry", async () => {
    vi.useFakeTimers();
    const processing = { ...ready, ready: false, state: "processing", pendingCount: 1, completedCount: 0 };
    fake.api.mockResolvedValue(processing);
    render(<Probe courseId="course" />);
    await act(async () => {});
    for (let check = 0; check < 120; check++) await act(async () => vi.advanceTimersByTimeAsync(5000));
    const automaticChecks = fake.api.mock.calls.length;
    await act(async () => vi.advanceTimersByTimeAsync(60_000));
    expect(fake.api.mock.calls.length).toBe(automaticChecks);
    fake.api.mockResolvedValueOnce(processing).mockResolvedValue(ready);
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    await act(async () => {});
    await act(async () => vi.advanceTimersByTimeAsync(5000));
    expect(screen.getByRole("status").textContent).toBe("Unlocked");
  });

  it("retains the known revision during a background check until the server reports a change", async () => {
    const background = deferred<typeof ready>();
    fake.api.mockResolvedValueOnce(ready).mockReturnValueOnce(background.promise);
    render(<Probe courseId="course" />);
    await waitFor(() => expect(screen.getByRole("status").textContent).toBe("Unlocked"));
    fireEvent(window, new Event("focus"));
    expect(screen.getByRole("status").textContent).toBe("Checking");
    expect(screen.queryByText("Revision: current")).not.toBeNull();
    await act(async () => background.resolve({ ...ready, ready: false, state: "processing", revision: "changed" }));
    expect(screen.getByRole("status").textContent).toBe("Locked");
    expect(screen.queryByText("Revision: changed")).not.toBeNull();
  });
});
