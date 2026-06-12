"use client";

import {
  createContext,
  useContext,
  useEffect,
  useState,
  useCallback,
  ReactNode,
} from "react";

export type Theme = "light" | "dark";

interface ThemeCtx {
  theme: Theme;
  setTheme: (t: Theme) => void;
  toggle: () => void;
}

const Ctx = createContext<ThemeCtx>({
  theme: "light",
  setTheme: () => {},
  toggle: () => {},
});

const STORAGE_KEY = "mudaris_theme";

export function ThemeProvider({ children }: { children: ReactNode }) {
  // Light is the default. A tiny inline script in the root layout applies the
  // saved theme to <html> BEFORE first paint, so there's no flash; this state
  // just keeps React in sync for the toggle button.
  const [theme, setThemeState] = useState<Theme>("light");

  // Hydrate the saved choice (if any) on mount.
  useEffect(() => {
    try {
      const saved = localStorage.getItem(STORAGE_KEY) as Theme | null;
      if (saved === "dark" || saved === "light") setThemeState(saved);
    } catch {
      /* ignore */
    }
  }, []);

  // Reflect the theme on <html data-theme> and persist it.
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try {
      localStorage.setItem(STORAGE_KEY, theme);
    } catch {
      /* ignore */
    }
  }, [theme]);

  const setTheme = useCallback((t: Theme) => setThemeState(t), []);
  const toggle = useCallback(
    () => setThemeState((p) => (p === "dark" ? "light" : "dark")),
    []
  );

  return (
    <Ctx.Provider value={{ theme, setTheme, toggle }}>{children}</Ctx.Provider>
  );
}

export const useTheme = () => useContext(Ctx);
