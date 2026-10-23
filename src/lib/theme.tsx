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

  // Adopt the pre-paint choice. Mounting never writes a default to storage.
  useEffect(() => {
    let choice: Theme = document.documentElement.dataset.theme === "dark" ? "dark" : "light";
    try {
      const saved = localStorage.getItem(STORAGE_KEY) as Theme | null;
      if (!document.documentElement.dataset.theme && (saved === "dark" || saved === "light")) choice = saved;
    } catch {
      /* ignore */
    }
    document.documentElement.dataset.theme = choice;
    setThemeState(choice);
  }, []);

  const setTheme = useCallback((value: Theme) => {
    setThemeState(value);
    document.documentElement.dataset.theme = value;
    try {
      localStorage.setItem(STORAGE_KEY, value);
    } catch {
      /* ignore */
    }
  }, []);
  const toggle = useCallback(
    () => setTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark"),
    [setTheme]
  );

  return (
    <Ctx.Provider value={{ theme, setTheme, toggle }}>{children}</Ctx.Provider>
  );
}

export const useTheme = () => useContext(Ctx);
