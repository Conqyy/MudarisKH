"use client";

import {
  createContext,
  useContext,
  useEffect,
  useState,
  useCallback,
  ReactNode,
} from "react";
import { AR } from "./translations";

export type Lang = "ar" | "en";

interface LangCtx {
  lang: Lang;
  dir: "rtl" | "ltr";
  /** Translate an English source string to the active language. */
  t: (s: string) => string;
  setLang: (l: Lang) => void;
  toggle: () => void;
}

const Ctx = createContext<LangCtx>({
  lang: "ar",
  dir: "rtl",
  t: (s) => s,
  setLang: () => {},
  toggle: () => {},
});

const STORAGE_KEY = "mudaris_lang";

export function LanguageProvider({ children }: { children: ReactNode }) {
  // Arabic is the default. The <html> tag is pre-rendered as ar/rtl in the
  // root layout, so the first paint is already correct for the common case.
  const [lang, setLangState] = useState<Lang>("ar");

  // Hydrate the saved choice (if any) on mount.
  useEffect(() => {
    try {
      const saved = localStorage.getItem(STORAGE_KEY) as Lang | null;
      if (saved === "ar" || saved === "en") setLangState(saved);
    } catch {
      /* ignore */
    }
  }, []);

  // Reflect the language on <html> (dir + lang) and persist it.
  useEffect(() => {
    const dir = lang === "ar" ? "rtl" : "ltr";
    document.documentElement.lang = lang;
    document.documentElement.dir = dir;
    try {
      localStorage.setItem(STORAGE_KEY, lang);
    } catch {
      /* ignore */
    }
  }, [lang]);

  const setLang = useCallback((l: Lang) => setLangState(l), []);
  const toggle = useCallback(
    () => setLangState((p) => (p === "ar" ? "en" : "ar")),
    []
  );
  const t = useCallback(
    (s: string) => (lang === "ar" ? AR[s] ?? s : s),
    [lang]
  );

  return (
    <Ctx.Provider
      value={{ lang, dir: lang === "ar" ? "rtl" : "ltr", t, setLang, toggle }}
    >
      {children}
    </Ctx.Provider>
  );
}

export const useLang = () => useContext(Ctx);
