import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const session = vi.hoisted(() => ({ user: { uid: "student" } as { uid: string } | null }));
vi.mock("../../src/lib/auth-context", () => ({ useAuth: () => ({ user: session.user }) }));

import { removeRecent, toggleBookmark, useBookmarks, useIsBookmarked, useRecents, useTrackRecent } from "../../src/lib/activity";

const item = { kind: "course" as const, id: "course", title: "Algorithms", href: "/course/course" };
const recent = { ...item, lastAt: 100 };
const bookmark = { ...item, addedAt: 100 };
beforeEach(() => { localStorage.clear(); session.user = { uid: "student" }; });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("device-local activity", () => {
  it.each(["null", "{}", "42", '"text"', "{malformed"])("uses an empty recent list and repairs the user's key for malformed payload %s", (raw) => {
    localStorage.setItem("mudaris.recent.student", raw);
    localStorage.setItem("mudaris.recent.other", JSON.stringify([recent]));
    const { result } = renderHook(useRecents);
    expect(result.current).toEqual([]);
    expect(JSON.parse(localStorage.getItem("mudaris.recent.student")!)).toEqual([]);
    expect(JSON.parse(localStorage.getItem("mudaris.recent.other")!)).toEqual([recent]);
  });

  it("keeps valid recents while removing null items, unknown kinds, unsafe links and invalid timestamps", () => {
    localStorage.setItem("mudaris.recent.student", JSON.stringify([
      null, 1, {}, recent, { ...recent, kind: "unknown" }, { ...recent, id: null },
      { ...recent, title: 7 }, { ...recent, title: " " }, { ...recent, href: "javascript:alert(1)" },
      { ...recent, href: "//other.example/course" }, { ...recent, href: "/course/../settings" },
      { ...recent, lastAt: "yesterday" }, { ...recent, lastAt: null }, { ...recent, lastAt: -1 },
    ]));
    const { result } = renderHook(useRecents);
    expect(result.current).toEqual([recent]);
    expect(JSON.parse(localStorage.getItem("mudaris.recent.student")!)).toEqual([recent]);
  });

  it("repairs bookmark items before lookup and toggle without discarding valid bookmarks", () => {
    localStorage.setItem("mudaris.bookmarks.student", JSON.stringify([null, bookmark, { ...bookmark, addedAt: "bad" }]));
    const { result } = renderHook(() => ({ marked: useIsBookmarked("course", "course"), bookmarks: useBookmarks() }));
    expect(result.current.marked).toBe(true);
    expect(result.current.bookmarks).toEqual([bookmark]);
    act(() => { expect(toggleBookmark("student", item)).toBe(false); });
    expect(result.current.marked).toBe(false);
    expect(result.current.bookmarks).toEqual([]);
  });

  it("handles non-array bookmark data before adding a valid bookmark", () => {
    localStorage.setItem("mudaris.bookmarks.student", "{}");
    expect(toggleBookmark("student", item)).toBe(true);
    expect(JSON.parse(localStorage.getItem("mudaris.bookmarks.student")!)).toMatchObject([item]);
  });

  it("drops invalid optional metadata while preserving the valid study link", () => {
    const summary = { kind: "summary", id: "summary", title: "النهايات", href: "/course/course/summary?summary=summary", lastAt: 100, courseCode: {}, courseColor: 1 };
    localStorage.setItem("mudaris.recent.student", JSON.stringify([summary]));
    const { result } = renderHook(useRecents);
    expect(result.current).toEqual([{ kind: "summary", id: "summary", title: "النهايات", href: "/course/course/summary?summary=summary", lastAt: 100 }]);
  });

  it("does not write invalid newly tracked items or unsafe new bookmarks", () => {
    renderHook(() => useTrackRecent({ ...item, href: "https://other.example" }));
    expect(localStorage.getItem("mudaris.recent.student")).toBeNull();
    expect(toggleBookmark("student", { ...item, href: "javascript:alert(1)" })).toBe(false);
    expect(localStorage.getItem("mudaris.bookmarks.student")).toBeNull();
  });

  it("removes a recent item from malformed input without touching another user's data", () => {
    localStorage.setItem("mudaris.recent.student", JSON.stringify([null, recent]));
    localStorage.setItem("mudaris.recent.other", JSON.stringify([recent]));
    removeRecent("student", "course", "course");
    expect(JSON.parse(localStorage.getItem("mudaris.recent.student")!)).toEqual([]);
    expect(JSON.parse(localStorage.getItem("mudaris.recent.other")!)).toEqual([recent]);
  });

  it("keeps the safe in-memory result if the browser prevents storage cleanup", () => {
    localStorage.setItem("mudaris.recent.student", JSON.stringify([null, recent]));
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("storage unavailable"); });
    const { result } = renderHook(useRecents);
    expect(result.current).toEqual([recent]);
  });
});
