"use client";

import {
  createContext,
  useContext,
  useEffect,
  useState,
  useCallback,
  ReactNode,
} from "react";

interface SidebarCtx {
  collapsed: boolean;
  setCollapsed: (c: boolean) => void;
  toggle: () => void;
}

const Ctx = createContext<SidebarCtx>({
  collapsed: false,
  setCollapsed: () => {},
  toggle: () => {},
});

const STORAGE_KEY = "mudaris_sidebar";

export function SidebarProvider({ children }: { children: ReactNode }) {
  // Expanded is the default. A tiny inline script in the root layout puts the
  // saved choice on <html data-sidebar> BEFORE first paint and globals.css
  // sizes the rail from that attribute, so a collapsed rail never renders wide
  // and then snaps narrow. This state only mirrors it for the toggle button.
  const [collapsed, setCollapsedState] = useState(false);

  // Adopt whatever the pre-paint script decided.
  useEffect(() => {
    setCollapsedState(document.documentElement.dataset.sidebar === "collapsed");
  }, []);

  // Persisting happens here rather than in an effect on `collapsed`: an effect
  // would also fire on mount with the pre-hydration default and overwrite the
  // saved choice before the line above has read it.
  const setCollapsed = useCallback((c: boolean) => {
    setCollapsedState(c);
    const value = c ? "collapsed" : "expanded";
    document.documentElement.dataset.sidebar = value;
    try {
      localStorage.setItem(STORAGE_KEY, value);
    } catch {
      /* ignore */
    }
  }, []);

  const toggle = useCallback(
    () => setCollapsed(document.documentElement.dataset.sidebar !== "collapsed"),
    [setCollapsed]
  );

  return (
    <Ctx.Provider value={{ collapsed, setCollapsed, toggle }}>
      {children}
    </Ctx.Provider>
  );
}

export const useSidebar = () => useContext(Ctx);
