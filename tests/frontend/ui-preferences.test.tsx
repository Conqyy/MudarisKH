import React, { StrictMode } from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it } from "vitest";
import { ThemeProvider, useTheme } from "../../src/lib/theme";
import { LanguageProvider, useLang } from "../../src/lib/i18n";
import { SidebarProvider, useSidebar } from "../../src/lib/sidebar";

function Controls() {
  const theme = useTheme(); const language = useLang(); const sidebar = useSidebar();
  return <><output>{`${theme.theme}/${language.lang}/${sidebar.collapsed ? "compact" : "expanded"}`}</output>
    <button onClick={theme.toggle}>Theme</button><button onClick={language.toggle}>Language</button><button onClick={sidebar.toggle}>Rail</button></>;
}
function mount() { return render(<StrictMode><ThemeProvider><LanguageProvider><SidebarProvider><Controls /></SidebarProvider></LanguageProvider></ThemeProvider></StrictMode>); }
beforeEach(() => { localStorage.clear(); document.documentElement.removeAttribute("data-theme"); document.documentElement.removeAttribute("data-sidebar"); document.documentElement.lang = "en"; document.documentElement.dir = "ltr"; });
afterEach(cleanup);

it("adopts saved pre-paint preferences without overwriting them during effect replay", () => {
  localStorage.setItem("mudaris_theme", "dark"); localStorage.setItem("mudaris_lang", "ar"); localStorage.setItem("mudaris_sidebar", "expanded");
  document.documentElement.dataset.theme = "dark"; document.documentElement.lang = "ar"; document.documentElement.dir = "rtl"; document.documentElement.dataset.sidebar = "expanded";
  mount();
  expect(screen.getByText("dark/ar/expanded")).toBeTruthy();
  expect(localStorage.getItem("mudaris_theme")).toBe("dark"); expect(localStorage.getItem("mudaris_lang")).toBe("ar");
  fireEvent.click(screen.getByText("Theme")); fireEvent.click(screen.getByText("Language")); fireEvent.click(screen.getByText("Rail"));
  expect(screen.getByText("light/en/compact")).toBeTruthy();
  expect(document.documentElement.dir).toBe("ltr"); expect(document.documentElement.dataset.theme).toBe("light");
  expect(localStorage.getItem("mudaris_sidebar")).toBe("collapsed");
});

it("defaults the unconfigured rail to compact without creating saved preference values", () => {
  mount(); expect(screen.getByText("light/en/compact")).toBeTruthy();
  expect(localStorage.getItem("mudaris_theme")).toBeNull(); expect(localStorage.getItem("mudaris_lang")).toBeNull(); expect(localStorage.getItem("mudaris_sidebar")).toBeNull();
});
