import React, { Children, isValidElement, StrictMode, type ReactElement } from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { LanguageProvider, useLang } from "../../src/lib/i18n";
import { SidebarProvider, useSidebar } from "../../src/lib/sidebar";
import RootLayout from "../../src/app/layout";

vi.mock("@/lib/auth-context", () => ({ AuthProvider: ({ children }: { children: React.ReactNode }) => children }));

function Controls() {
  const language = useLang(); const sidebar = useSidebar();
  return <><output>{`${language.lang}/${sidebar.collapsed ? "compact" : "expanded"}`}</output>
    <button onClick={language.toggle}>Language</button><button onClick={sidebar.toggle}>Rail</button></>;
}
function mount() { return render(<StrictMode><LanguageProvider><SidebarProvider><Controls /></SidebarProvider></LanguageProvider></StrictMode>); }
beforeEach(() => { localStorage.clear(); document.documentElement.removeAttribute("data-theme"); document.documentElement.removeAttribute("data-sidebar"); document.documentElement.lang = "en"; document.documentElement.dir = "ltr"; });
afterEach(cleanup);

it("starts light despite a retired dark preference and still applies saved navigation preferences before paint", () => {
  localStorage.setItem("mudaris_theme", "dark");
  localStorage.setItem("mudaris_lang", "ar");
  localStorage.setItem("mudaris_sidebar", "expanded");
  const layout = RootLayout({ children: null });
  if (layout.props["data-theme"]) document.documentElement.dataset.theme = layout.props["data-theme"];
  const head = Children.toArray(layout.props.children).find(child => isValidElement(child) && child.type === "head") as ReactElement<{ children: React.ReactNode }>;
  const script = Children.toArray(head.props.children).find(child => isValidElement(child) && child.type === "script") as ReactElement<{ dangerouslySetInnerHTML: { __html: string } }>;
  new Function(script.props.dangerouslySetInnerHTML.__html)();
  expect(document.documentElement.dataset.theme).toBe("light");
  expect(document.documentElement.lang).toBe("ar");
  expect(document.documentElement.dir).toBe("rtl");
  expect(document.documentElement.dataset.sidebar).toBe("expanded");
});

it("adopts saved pre-paint preferences without overwriting them during effect replay", () => {
  localStorage.setItem("mudaris_lang", "ar"); localStorage.setItem("mudaris_sidebar", "expanded");
  document.documentElement.lang = "ar"; document.documentElement.dir = "rtl"; document.documentElement.dataset.sidebar = "expanded";
  mount();
  expect(screen.getByText("ar/expanded")).toBeTruthy();
  expect(localStorage.getItem("mudaris_lang")).toBe("ar");
  fireEvent.click(screen.getByText("Language")); fireEvent.click(screen.getByText("Rail"));
  expect(screen.getByText("en/compact")).toBeTruthy();
  expect(document.documentElement.dir).toBe("ltr");
  expect(localStorage.getItem("mudaris_sidebar")).toBe("collapsed");
});

it("defaults the unconfigured rail to compact without creating saved preference values", () => {
  mount(); expect(screen.getByText("en/compact")).toBeTruthy();
  expect(localStorage.getItem("mudaris_lang")).toBeNull(); expect(localStorage.getItem("mudaris_sidebar")).toBeNull();
});
