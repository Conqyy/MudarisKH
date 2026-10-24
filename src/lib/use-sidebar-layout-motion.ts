"use client";
import { useCallback, useEffect, useLayoutEffect, useRef, type RefObject } from "react";
import { isPointerInteraction } from "./input-modality";

type Presentation = { rect: DOMRect; opacity: string; visible: boolean };
type Snapshot = {
  panel: HTMLDivElement;
  elements: Map<HTMLElement, Presentation>;
  workspace: HTMLElement | null;
  workspaceRect?: DOMRect;
  rtl: boolean;
};
const desktop = () => window.matchMedia?.("(min-width: 768px)").matches ?? window.innerWidth >= 768;
const visible = (element: HTMLElement) => {
  const style = getComputedStyle(element);
  return style.display !== "none" && style.visibility !== "hidden";
};
const hasDialog = (element: HTMLElement) => !!element.querySelector('[role="dialog"], [aria-modal="true"], dialog[open]');

/** Invert one layout change with compositor motion, keeping readable content unscaled. */
export function useSidebarLayoutMotion(collapsed: boolean, panelRef: RefObject<HTMLDivElement | null>) {
  const pending = useRef<Snapshot | null>(null);
  const running = useRef<Animation[]>([]);
  const generation = useRef(0);
  const owner = useRef<{ panel: HTMLElement; boundary: HTMLElement | null } | null>(null);

  const cancel = useCallback(() => {
    generation.current += 1;
    pending.current = null;
    running.current.forEach(animation => animation.cancel());
    running.current = [];
    if (owner.current) {
      delete owner.current.panel.dataset.sidebarMotion;
      if (owner.current.boundary) delete owner.current.boundary.dataset.sidebarMotion;
      owner.current = null;
    }
  }, []);

  const animateChange = useCallback((update: () => void) => {
    const panel = panelRef.current;
    let snapshot: Snapshot | null = null;
    if (panel && desktop() && isPointerInteraction() && typeof panel.animate === "function") {
      const elements = new Map<HTMLElement, Presentation>();
      panel.querySelectorAll<HTMLElement>(".sidebar-glass, .sidebar-content .sidebar-item, .sidebar-label, .sidebar-heading").forEach(element => {
        elements.set(element, { rect: element.getBoundingClientRect(), opacity: getComputedStyle(element).opacity || "1", visible: visible(element) });
      });
      const workspace = panel.closest(".app-shell")?.querySelector<HTMLElement>(".app-workspace") || null;
      snapshot = { panel, elements, workspace, workspaceRect: workspace && !hasDialog(workspace) ? workspace.getBoundingClientRect() : undefined, rtl: document.documentElement.dir === "rtl" };
    }
    // Read the live presentation above before removing the previous animation.
    cancel();
    pending.current = snapshot;
    update();
  }, [cancel, panelRef]);

  useLayoutEffect(() => {
    const snapshot = pending.current;
    pending.current = null;
    if (!snapshot || !desktop() || !isPointerInteraction() || snapshot.rtl !== (document.documentElement.dir === "rtl")) return;
    const reduced = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches === true;
    const timing: KeyframeAnimationOptions = { duration: reduced ? 200 : 240, easing: getComputedStyle(document.documentElement).getPropertyValue("--ease-drawer").trim() || "cubic-bezier(0.32,0.72,0,1)", fill: "both" };
    // Batch destination reads before starting any compositor effects.
    const destinations = [...snapshot.elements].map(([element, previous]) => ({ element, previous, rect: element.getBoundingClientRect(), visible: visible(element), opacity: getComputedStyle(element).opacity || "1" }));
    const workspaceRect = snapshot.workspace && snapshot.workspaceRect && !hasDialog(snapshot.workspace) ? snapshot.workspace.getBoundingClientRect() : null;
    const token = generation.current;
    const play = (element: HTMLElement, frames: Keyframe[]) => { running.current.push(element.animate(frames, timing)); };
    for (const destination of destinations) {
      const { element, previous, rect, visible: isVisible, opacity } = destination;
      if (!isVisible) continue;
      if (element.classList.contains("sidebar-glass")) {
        if (reduced) play(element, [{ opacity: .78 }, { opacity: 1 }]);
        else if (previous.rect.width && rect.width) play(element, [{ transform: `scaleX(${previous.rect.width / rect.width})` }, { transform: "scaleX(1)" }]);
      } else if (element.classList.contains("sidebar-item")) {
        if (!reduced && previous.visible) {
          const x = previous.rect.left - rect.left, y = previous.rect.top - rect.top;
          if (Math.abs(x) > .5 || Math.abs(y) > .5) play(element, [{ transform: `translate(${x}px, ${y}px)` }, { transform: "translate(0px, 0px)" }]);
        }
      } else if (!previous.visible || previous.opacity !== opacity) {
        play(element, [{ opacity: previous.visible ? previous.opacity : 0 }, { opacity }]);
      }
    }
    if (!reduced && snapshot.workspace && snapshot.workspaceRect && workspaceRect) {
      const delta = snapshot.rtl ? snapshot.workspaceRect.right - workspaceRect.right : snapshot.workspaceRect.left - workspaceRect.left;
      if (Math.abs(delta) > .5) play(snapshot.workspace, [{ transform: `translateX(${delta}px)` }, { transform: "translateX(0px)" }]);
    }
    if (!running.current.length) return;
    const boundary = snapshot.workspace?.closest<HTMLElement>(".app-shell-body") || null;
    owner.current = { panel: snapshot.panel, boundary };
    snapshot.panel.dataset.sidebarMotion = "true";
    if (boundary) boundary.dataset.sidebarMotion = "true";
    void Promise.all(running.current.map(animation => animation.finished)).then(() => {
      if (token === generation.current) cancel();
    }).catch(() => { /* A newer toggle or context change owns the presentation. */ });
  }, [collapsed, cancel]);

  useEffect(() => {
    const pointer = (event: PointerEvent) => { if (!(event.target instanceof Node) || !panelRef.current?.contains(event.target)) cancel(); };
    document.addEventListener("pointerdown", pointer, true);
    document.addEventListener("keydown", cancel, true);
    window.addEventListener("resize", cancel);
    const direction = new MutationObserver(cancel);
    direction.observe(document.documentElement, { attributes: true, attributeFilter: ["dir"] });
    return () => {
      document.removeEventListener("pointerdown", pointer, true);
      document.removeEventListener("keydown", cancel, true);
      window.removeEventListener("resize", cancel);
      direction.disconnect();
      cancel();
    };
  }, [cancel, panelRef]);

  return animateChange;
}
