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
  collapsed: true,
  setCollapsed: () => {},
  toggle: () => {},
});

const STORAGE_KEY = "mudaris_sidebar";

export function SidebarProvider({ children }: { children: ReactNode }) {
  // Compact is the unconfigured default. The root pre-paint script puts the
  // saved choice on <html data-sidebar> BEFORE first paint and globals.css
  // sizes the rail from that attribute, so a collapsed rail never renders wide
  // and then snaps narrow. This state only mirrors it for the toggle button.
  const [collapsed, setCollapsedState] = useState(true);

  // Adopt whatever the pre-paint script decided.
  useEffect(() => {
    let expanded = document.documentElement.dataset.sidebar === "expanded";
    try { const saved = localStorage.getItem(STORAGE_KEY); if (saved === "expanded" || saved === "collapsed") expanded = saved === "expanded"; } catch { /* storage can be unavailable */ }
    document.documentElement.dataset.sidebar = expanded ? "expanded" : "collapsed";
    setCollapsedState(!expanded);
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
