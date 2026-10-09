import React from "react";
import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const fake = vi.hoisted(() => ({
  auth: { currentUser: null as any },
  listener: null as any,
  documents: new Map<string, any>(),
  writeError: null as Error | null,
  popupError: null as any,
  redirectUser: null as any,
  trace: [] as string[],
  response: { ok: true, status: 200, json: async () => ({}) },
  signOutError: null as Error | null,
  readGate: null as Promise<void> | null,
  emitSignup: false,
  emitDuringPurge: false,
  apiGate: null as Promise<void> | null,
  updateGate: null as Promise<void> | null,
  requestedUid: null as string | null,
}));

vi.mock("../../src/lib/firebase", () => ({ auth: fake.auth, db: {}, googleProvider: {} }));
vi.mock("firebase/firestore", () => ({
  doc: (_db: unknown, collection: string, id: string) => `${collection}/${id}`,
  collection: (_db: unknown, name: string) => name,
  setDoc: async (key: string, data: any, options?: { merge?: boolean }) => {
    if (fake.writeError) throw fake.writeError;
    const validate = (value: any): void => {
      if (value === undefined) throw new Error("Firestore does not support undefined values");
      if (value && typeof value === "object") Object.values(value).forEach(validate);
    };
    validate(data);
    const previous = fake.documents.get(key);
    if (previous && data.createdAt !== undefined && previous.createdAt !== data.createdAt) {
      throw new Error("createdAt must remain unchanged");
    }
    fake.documents.set(key, options?.merge ? { ...fake.documents.get(key), ...data } : data);
  },
  getDoc: async (key: string) => {
    const exists = fake.documents.has(key);
    const data = fake.documents.get(key);
    if (fake.readGate) await fake.readGate;
    return { exists: () => exists, data: () => data };
  },
  runTransaction: async (_db: unknown, operation: any) => operation({
    get: async (key: string) => ({ exists: () => fake.documents.has(key), data: () => fake.documents.get(key) }),
    set: (key: string, data: any) => {
      if (fake.writeError) throw fake.writeError;
      const validate = (value: any): void => {
        if (value === undefined) throw new Error("Firestore does not support undefined values");
        if (value && typeof value === "object") Object.values(value).forEach(validate);
      };
      validate(data);
      fake.documents.set(key, data);
    },
    update: (key: string, data: any) => {
      if (fake.writeError) throw fake.writeError;
      fake.documents.set(key, { ...fake.documents.get(key), ...data });
    },
  }),
  deleteDoc: async (key: string) => { fake.trace.push(`client-delete:${key}`); fake.documents.delete(key); },
  updateDoc: async (key: string, data: any) => {
    const validate = (value: any): void => {
      if (value === undefined) throw new Error("Firestore does not support undefined values");
      if (value && typeof value === "object") Object.values(value).forEach(validate);
    };
    validate(data);
    fake.documents.set(key, { ...fake.documents.get(key), ...data });
  },
  addDoc: vi.fn(), getDocs: vi.fn(), query: vi.fn(), where: vi.fn(),
}));
vi.mock("firebase/auth", () => ({
  onAuthStateChanged: (_auth: unknown, callback: any) => { fake.listener = callback; return () => {}; },
  createUserWithEmailAndPassword: async () => {
    if (fake.emitSignup) await fake.listener(fake.auth.currentUser);
    return { user: fake.auth.currentUser };
  },
  signInWithEmailAndPassword: vi.fn(),
  updateProfile: async (user: any, data: any) => {
    if (fake.updateGate) await fake.updateGate;
    Object.assign(user, data);
  },
  getRedirectResult: async () => fake.redirectUser ? ({ user: fake.redirectUser }) : null,
  signInWithPopup: async () => { if (fake.popupError) throw fake.popupError; return { user: fake.auth.currentUser }; },
  signInWithRedirect: async () => { fake.trace.push("redirect"); },
  signOut: async () => {
    fake.trace.push("signout");
    if (fake.signOutError) throw fake.signOutError;
    fake.auth.currentUser = null;
  },
  EmailAuthProvider: { credential: () => ({}) },
  reauthenticateWithCredential: async () => { fake.trace.push("reauthenticate"); },
  reauthenticateWithPopup: async () => { fake.trace.push("reauthenticate"); },
  deleteUser: async () => { fake.trace.push("client-delete-auth"); },
  sendPasswordResetEmail: vi.fn(), updateEmail: async (user: any, email: string) => { user.email = email; }, verifyBeforeUpdateEmail: vi.fn(), updatePassword: vi.fn(),
}));
vi.mock("../../src/lib/api", () => ({
  API_URL: "https://backend.test",
  apiFetch: async (url: string, init: RequestInit) => {
    fake.trace.push(`${init.method} ${url}`);
    if (fake.apiGate) await fake.apiGate;
    fake.requestedUid = fake.auth.currentUser?.uid ?? null;
    if (fake.emitDuringPurge && url.endsWith("/api/account")) await fake.listener(fake.auth.currentUser);
    return fake.response;
  },
}));

import { AuthProvider, useAuth } from "../../src/lib/auth-context";
import { deleteCourse, updateCourse } from "../../src/lib/firestore-helpers";

const wrapper = ({ children }: { children: React.ReactNode }) => <AuthProvider>{children}</AuthProvider>;
async function signedIn() {
  const hook = renderHook(() => useAuth(), { wrapper });
  await act(async () => { await fake.listener(fake.auth.currentUser); });
  return hook;
}

beforeEach(() => {
  fake.documents.clear(); fake.trace = []; fake.writeError = null; fake.popupError = null;
  fake.redirectUser = null; fake.signOutError = null;
  fake.readGate = null;
  fake.emitSignup = false;
  fake.emitDuringPurge = false;
  fake.apiGate = null; fake.updateGate = null; fake.requestedUid = null;
  fake.response = { ok: true, status: 200, json: async () => ({}) };
  fake.auth.currentUser = {
    uid: "student", email: "student@example.test", displayName: "Student", photoURL: null,
    providerData: [{ providerId: "password" }],
    getIdToken: async (force: boolean) => { fake.trace.push(`token:${force}`); return "fresh-token"; },
  };
  window.localStorage.clear();
  vi.spyOn(globalThis, "fetch").mockImplementation(async (url, init) => {
    fake.trace.push(`${init?.method} ${url}`);
    if (fake.apiGate) await fake.apiGate;
    fake.requestedUid = new Headers(init?.headers).get("Authorization") === "Bearer fresh-token" ? "student" : "wrong-user";
    if (fake.emitDuringPurge) await fake.listener(fake.auth.currentUser);
    return fake.response as Response;
  });
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("profile persistence", () => {
  it("creates a signup profile when optional academic fields are undefined", async () => {
    const { result } = renderHook(() => useAuth(), { wrapper });
    await act(async () => {
      await result.current.signUp("student@example.test", "password", "Khalid", {
        university: undefined, major: undefined, academicYear: undefined,
      });
    });
    expect(fake.documents.get("users/student")).toMatchObject({ fullName: "Khalid", uid: "student" });
    expect(fake.documents.get("users/student")).not.toHaveProperty("university");
    expect(result.current.profile?.fullName).toBe("Khalid");
  });

  it("persists a healed profile without a photo URL", async () => {
    const { result } = await signedIn();
    expect(fake.documents.get("users/student")).toMatchObject({ fullName: "Student" });
    expect(result.current.profile).not.toHaveProperty("photoURL");
  });

  it("signup does not race profile healing and violate immutable createdAt rules", async () => {
    fake.emitSignup = true;
    vi.spyOn(Date, "now").mockReturnValueOnce(1).mockReturnValue(2);
    const { result } = renderHook(() => useAuth(), { wrapper });
    await act(async () => { await result.current.signUp("student@example.test", "password", "Khalid"); });
    expect(fake.documents.get("users/student").fullName).toBe("Khalid");
  });

  it.each(["popup", "redirect"])("persists a missing Google profile after %s sign-in", async (mode) => {
    if (mode === "redirect") fake.redirectUser = fake.auth.currentUser;
    const { result } = renderHook(() => useAuth(), { wrapper });
    await act(async () => {
      if (mode === "popup") await result.current.signInWithGoogle();
    });
    expect(fake.documents.get("users/student")).toMatchObject({ uid: "student" });
    expect(fake.documents.get("users/student")).not.toHaveProperty("photoURL");
  });

  it("Google sign-in preserves a profile concurrently created by session healing", async () => {
    let release!: () => void;
    fake.readGate = new Promise<void>((resolve) => { release = resolve; });
    const { result } = renderHook(() => useAuth(), { wrapper });
    let login!: Promise<void>;
    await act(async () => { login = result.current.signInWithGoogle(); });
    fake.documents.set("users/student", { uid: "student", email: "student@example.test", fullName: "Student", createdAt: 123 });
    await act(async () => { release(); await login; });
    expect(fake.documents.get("users/student").createdAt).toBe(123);
  });

  it("reports that Auth signup succeeded when saving the profile fails", async () => {
    fake.writeError = new Error("offline");
    const { result } = renderHook(() => useAuth(), { wrapper });
    await act(async () => {
      await expect(result.current.signUp("student@example.test", "password", "Khalid"))
        .rejects.toThrow(/account was created/i);
    });
    expect(result.current.profile?.fullName).toBe("Khalid");
    expect(fake.trace).not.toContain("client-delete-auth");
  });

  it("a profile edit recreates complete required fields when the profile is missing", async () => {
    const { result } = renderHook(() => useAuth(), { wrapper });
    await act(async () => { await result.current.updateUserProfile({ fullName: "Khalid", major: undefined }); });
    expect(fake.documents.get("users/student")).toMatchObject({ uid: "student", email: "student@example.test", fullName: "Khalid" });
    expect(result.current.profile?.fullName).toBe("Khalid");
  });

  it("a profile edit preserves existing createdAt even before profile hydration", async () => {
    fake.documents.set("users/student", { uid: "student", email: "student@example.test", fullName: "Student", createdAt: 123 });
    const { result } = renderHook(() => useAuth(), { wrapper });
    await act(async () => { await result.current.updateUserProfile({ fullName: "Khalid" }); });
    expect(fake.documents.get("users/student")).toMatchObject({ fullName: "Khalid", createdAt: 123 });
  });

  it("changing email recreates a complete profile when its document is missing", async () => {
    const { result } = renderHook(() => useAuth(), { wrapper });
    await act(async () => { await result.current.changeEmail("new@example.test", "password"); });
    expect(fake.documents.get("users/student")).toMatchObject({ uid: "student", email: "new@example.test", fullName: "Student" });
    expect(result.current.profile?.email).toBe("new@example.test");
  });

  it("does not redirect when a user deliberately closes Google sign-in", async () => {
    fake.popupError = { code: "auth/popup-closed-by-user" };
    const { result } = renderHook(() => useAuth(), { wrapper });
    await act(async () => { await expect(result.current.signInWithGoogle()).rejects.toMatchObject(fake.popupError); });
    expect(fake.trace).not.toContain("redirect");
  });

  it("does not restore a signed-out user's profile when Google profile loading finishes late", async () => {
    let release!: () => void;
    fake.readGate = new Promise<void>((resolve) => { release = resolve; });
    const { result } = renderHook(() => useAuth(), { wrapper });
    let login!: Promise<void>;
    await act(async () => { login = result.current.signInWithGoogle(); });
    await act(async () => { await result.current.signOut(); });
    await act(async () => { release(); await login; });
    expect(result.current.profile).toBeNull();
    expect(fake.documents.has("users/student")).toBe(false);
  });

  it("does not restore an old signup profile after switching accounts mid-signup", async () => {
    let release!: () => void;
    fake.updateGate = new Promise<void>((resolve) => { release = resolve; });
    fake.emitSignup = true;
    const { result } = renderHook(() => useAuth(), { wrapper });
    let signup!: Promise<void>;
    await act(async () => {
      signup = result.current.signUp("student@example.test", "password", "Old student").catch(() => {});
    });
    fake.auth.currentUser = { ...fake.auth.currentUser, uid: "replacement", email: "replacement@example.test" };
    fake.documents.set("users/replacement", { uid: "replacement", email: "replacement@example.test", fullName: "New student", createdAt: 1 });
    await act(async () => { await fake.listener(fake.auth.currentUser); release(); await signup; });
    expect(result.current.user?.uid).toBe("replacement");
    expect(result.current.profile?.uid).toBe("replacement");
    expect(fake.documents.has("users/student")).toBe(false);
  });
});

describe("course writes and deletion", () => {
  it("cleans undefined array entries and nested reminder values before writing", async () => {
    await updateCourse("course", { reminders: [undefined, { id: "r", title: "Quiz", type: "quiz", done: false, createdAt: 1, date: undefined }] as any });
    expect(fake.documents.get("courses/course").reminders).toEqual([{ id: "r", title: "Quiz", type: "quiz", done: false, createdAt: 1 }]);
  });

  it("routes course deletion through the server cascade and clears only that course's activity", async () => {
    window.localStorage.setItem("mudaris.recent.student", JSON.stringify([
      { kind: "exam", id: "exam", href: "/course/course/exam/exam" },
      { kind: "course", id: "other", href: "/course/other" },
    ]));
    await deleteCourse("course");
    expect(fake.trace).toContain("DELETE https://backend.test/api/courses/course");
    expect(fake.trace).not.toContain("client-delete:courses/course");
    expect(JSON.parse(window.localStorage.getItem("mudaris.recent.student")!)).toEqual([{ kind: "course", id: "other", href: "/course/other" }]);
  });

  it("rejects a failed course purge and retains local activity", async () => {
    fake.response = { ok: false, status: 503, json: async () => ({ detail: "Storage cleanup failed; retry deletion" }) };
    window.localStorage.setItem("mudaris.recent.student", "[]");
    await expect(deleteCourse("course")).rejects.toThrow(/Storage cleanup failed/);
    expect(window.localStorage.getItem("mudaris.recent.student")).toBe("[]");
  });

  it("preserves a reminder added on another device while completing a known reminder", async () => {
    const first = { id: "one", title: "Quiz", type: "quiz", done: false, createdAt: 1 };
    const second = { id: "two", title: "New assignment", type: "assignment", done: false, createdAt: 2 };
    fake.documents.set("courses/course", { reminders: [first, second] });
    const saved = await updateCourse("course", { reminders: [{ ...first, done: true }] as any }, { reminders: [first] } as any);
    expect(fake.documents.get("courses/course").reminders).toEqual([{ ...first, done: true }, second]);
    expect(saved).toMatchObject({ reminders: [{ ...first, done: true }, second] });
  });

  it("rejects conflicting edits to the same reminder without losing the newer server value", async () => {
    const first = { id: "one", title: "Quiz", type: "quiz", done: false, createdAt: 1 };
    fake.documents.set("courses/course", { reminders: [{ ...first, title: "Server title" }] });
    await expect(updateCourse("course", { reminders: [{ ...first, title: "Stale edit" }] as any }, { reminders: [first] } as any))
      .rejects.toThrow(/changed.*device|conflict/i);
    expect(fake.documents.get("courses/course").reminders[0].title).toBe("Server title");
  });

  it("preserves an independent completion when editing a reminder and clearing its optional date", async () => {
    const first = { id: "one", title: "Quiz", type: "quiz", done: false, createdAt: 1, date: "2026-10-11" };
    fake.documents.set("courses/course", { reminders: [{ ...first, done: true }] });
    await updateCourse("course", { reminders: [{ ...first, title: "Revision", date: undefined }] as any }, { reminders: [first] } as any);
    expect(fake.documents.get("courses/course").reminders).toEqual([{ id: "one", title: "Revision", type: "quiz", done: true, createdAt: 1 }]);
  });

  it("deleting a known reminder preserves new reminders from another device", async () => {
    const first = { id: "one", title: "Quiz", type: "quiz", done: false, createdAt: 1 };
    const second = { id: "two", title: "Assignment", type: "assignment", done: false, createdAt: 2 };
    fake.documents.set("courses/course", { reminders: [first, second] });
    await updateCourse("course", { reminders: [] }, { reminders: [first] } as any);
    expect(fake.documents.get("courses/course").reminders).toEqual([second]);
  });

  it("rejects editing a reminder deleted by another device instead of resurrecting it", async () => {
    const first = { id: "one", title: "Quiz", type: "quiz", done: false, createdAt: 1 };
    fake.documents.set("courses/course", { reminders: [] });
    await expect(updateCourse("course", { reminders: [{ ...first, done: true }] as any }, { reminders: [first] } as any))
      .rejects.toThrow(/changed.*device|conflict/i);
    expect(fake.documents.get("courses/course").reminders).toEqual([]);
  });

  it("merges a new title override without deleting another device's title override", async () => {
    fake.documents.set("courses/course", { titleOverrides: { one: "First title", two: "Server title" } });
    await updateCourse("course", { titleOverrides: { one: "Updated first title" } }, { titleOverrides: { one: "First title" } });
    expect(fake.documents.get("courses/course").titleOverrides).toEqual({ one: "Updated first title", two: "Server title" });
  });

  it("rejects a stale material order rather than overwriting another device's reorder", async () => {
    fake.documents.set("courses/course", { documentOrder: ["three", "one", "two"] });
    await expect(updateCourse("course", { documentOrder: ["two", "one"] }, { documentOrder: ["one", "two"] }))
      .rejects.toThrow(/changed.*device|conflict/i);
    expect(fake.documents.get("courses/course").documentOrder).toEqual(["three", "one", "two"]);
  });
});

describe("account deletion", () => {
  it("binds deletion to the reauthenticated account and preserves a replacement session", async () => {
    let release!: () => void;
    fake.apiGate = new Promise<void>((resolve) => { release = resolve; });
    const { result } = await signedIn();
    let deletion!: Promise<void>;
    await act(async () => { deletion = result.current.deleteAccount("password"); });
    fake.auth.currentUser = { ...fake.auth.currentUser, uid: "replacement", email: "replacement@example.test" };
    fake.documents.set("users/replacement", { uid: "replacement", email: "replacement@example.test", fullName: "New student", createdAt: 1 });
    await act(async () => { await fake.listener(fake.auth.currentUser); release(); await deletion; });
    expect(fake.requestedUid).toBe("student");
    expect(result.current.user?.uid).toBe("replacement");
    expect(result.current.profile?.uid).toBe("replacement");
    expect(fake.trace).not.toContain("signout");
  });
  it("reauthenticates and refreshes the token before the server purge, then clears local session and owned activity", async () => {
    const { result } = await signedIn();
    window.localStorage.setItem("mudaris.recent.student", "[]");
    window.localStorage.setItem("mudaris.bookmarks.student", "[]");
    window.localStorage.setItem("mudaris.recent.other", "[]");
    await act(async () => { await result.current.deleteAccount("password"); });
    expect(fake.trace).toEqual(["reauthenticate", "token:true", "DELETE https://backend.test/api/account", "signout"]);
    expect(result.current.user).toBeNull(); expect(result.current.profile).toBeNull();
    expect(window.localStorage.getItem("mudaris.recent.student")).toBeNull();
    expect(window.localStorage.getItem("mudaris.bookmarks.student")).toBeNull();
    expect(window.localStorage.getItem("mudaris.recent.other")).toBe("[]");
  });

  it("retains the account state and activity when a backend purge fails", async () => {
    const { result } = await signedIn();
    fake.response = { ok: false, status: 503, json: async () => ({ detail: "Cleanup incomplete; retry deletion" }) };
    window.localStorage.setItem("mudaris.bookmarks.student", "[]");
    await act(async () => { await expect(result.current.deleteAccount("password")).rejects.toThrow(/Cleanup incomplete/); });
    expect(result.current.user?.uid).toBe("student");
    expect(result.current.profile?.uid).toBe("student");
    expect(window.localStorage.getItem("mudaris.bookmarks.student")).toBe("[]");
    expect(fake.trace).not.toContain("signout");
    expect(fake.trace).not.toContain("client-delete:users/student");
  });

  it("preserves the profile across a session callback while an unsuccessful purge is pending", async () => {
    const { result } = await signedIn();
    fake.emitDuringPurge = true;
    fake.response = { ok: false, status: 503, json: async () => ({ detail: "Cleanup incomplete; retry deletion" }) };
    await act(async () => { await expect(result.current.deleteAccount("password")).rejects.toThrow(/Cleanup incomplete/); });
    expect(result.current.profile?.uid).toBe("student");
  });

  it("clears app state after successful server deletion even if local Firebase sign-out fails", async () => {
    const { result } = await signedIn();
    fake.signOutError = new Error("local persistence unavailable");
    vi.spyOn(console, "error").mockImplementation(() => {});
    await act(async () => { await result.current.deleteAccount("password"); });
    expect(result.current.user).toBeNull(); expect(result.current.profile).toBeNull();
    await act(async () => { await fake.listener(fake.auth.currentUser); });
    expect(result.current.user).toBeNull(); expect(result.current.profile).toBeNull();
  });
});
