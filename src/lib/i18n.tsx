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
  // English is the default. The <html> tag is pre-rendered as en/ltr in the
  // root layout, so the first paint is already correct for the common case.
  const [lang, setLangState] = useState<Lang>("en");

  // Hydrate the saved choice (if any) on mount.
  useEffect(() => {
    let choice: Lang = document.documentElement.lang === "ar" ? "ar" : "en";
    try {
      const saved = localStorage.getItem(STORAGE_KEY) as Lang | null;
      if (saved === "ar" || saved === "en") choice = saved;
    } catch {
      /* ignore */
    }
    document.documentElement.lang = choice;
    document.documentElement.dir = choice === "ar" ? "rtl" : "ltr";
    setLangState(choice);
  }, []);

  const setLang = useCallback((value: Lang) => {
    setLangState(value);
    document.documentElement.lang = value;
    document.documentElement.dir = value === "ar" ? "rtl" : "ltr";
    try {
      localStorage.setItem(STORAGE_KEY, value);
    } catch {
      /* ignore */
    }
  }, []);
  const toggle = useCallback(
    () => setLang(document.documentElement.lang === "ar" ? "en" : "ar"),
    [setLang]
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
