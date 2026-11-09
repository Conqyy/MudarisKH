import React from "react";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import SettingsPage from "../../src/app/settings/page";
import { LanguageProvider } from "../../src/lib/i18n";

const account = vi.hoisted(() => ({
  user: { uid: "student", email: "student@example.com", emailVerified: true },
  profile: { fullName: "Student", university: "", major: "", academicYear: "", photoURL: "" },
  updateUserProfile: vi.fn(), changeEmail: vi.fn(), changePassword: vi.fn(), deleteAccount: vi.fn(), signOut: vi.fn(),
  push: vi.fn(),
}));
vi.mock("@/lib/auth-context", () => ({ useAuth: () => ({ ...account, loading: false, hasPasswordProvider: () => false }) }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: account.push }) }));
vi.mock("@/components/AppShell", () => ({ default: ({ children }: { children: React.ReactNode }) => <>{children}</> }));

const mount = () => render(<LanguageProvider><SettingsPage /></LanguageProvider>);
beforeEach(() => {
  vi.clearAllMocks(); localStorage.clear();
  document.documentElement.lang = "en"; document.documentElement.dir = "ltr";
});
afterEach(cleanup);

it("adopts a saved Arabic preference and persists an English change across remounts", async () => {
  localStorage.setItem("mudaris_lang", "ar");
  const first = mount();
  const language = await screen.findByRole("combobox", { name: "لغة الواجهة" });
  expect((language as HTMLSelectElement).value).toBe("ar");
  expect(document.documentElement.dir).toBe("rtl");

  fireEvent.change(language, { target: { value: "en" } });
  await waitFor(() => expect(document.documentElement.dir).toBe("ltr"));
  expect(document.documentElement.lang).toBe("en");
  expect(localStorage.getItem("mudaris_lang")).toBe("en");
  first.unmount();
  document.documentElement.lang = "ar"; document.documentElement.dir = "rtl";
  mount();
  expect((await screen.findByRole("combobox", { name: "Interface language" }) as HTMLSelectElement).value).toBe("en");
  expect(document.documentElement.dir).toBe("ltr");
});

it("switches to Arabic immediately without submitting any account changes", async () => {
  mount();
  fireEvent.change(await screen.findByRole("combobox", { name: "Interface language" }), { target: { value: "ar" } });
  await waitFor(() => expect(document.documentElement.dir).toBe("rtl"));
  expect(document.documentElement.lang).toBe("ar");
  expect(localStorage.getItem("mudaris_lang")).toBe("ar");
  expect((screen.getByRole("combobox", { name: "لغة الواجهة" }) as HTMLSelectElement).value).toBe("ar");
  for (const mutation of [account.updateUserProfile, account.changeEmail, account.changePassword, account.deleteAccount, account.signOut]) expect(mutation).not.toHaveBeenCalled();
  expect(account.push).not.toHaveBeenCalled();
});
