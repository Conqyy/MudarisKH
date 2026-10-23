"use client";

import { useCallback, useLayoutEffect, useRef } from "react";
import { isPointerInteraction } from "./input-modality";
import { useDialog } from "./use-dialog";

type OverlayKind = "dialog" | "drawer" | "popover";
type Options = { enabled?: boolean; kind?: OverlayKind; trapFocus?: boolean; canClose?: boolean; side?: "start" | "end" };
const EASE_OUT = "cubic-bezier(0.23,1,0.32,1)";
const EASE_DRAWER = "cubic-bezier(0.32,0.72,0,1)";

/** Keep the real overlay mounted through pointer dismissal; keyboard actions stay instant. */
export function useOverlayMotion(onClose: () => void, { enabled = true, kind = "dialog", trapFocus = true, canClose = true, side = "end" }: Options = {}) {
  const latest = useRef({ onClose, enabled, canClose });
  latest.current = { onClose, enabled, canClose };
  const animations = useRef<Animation[]>([]);
  const generation = useRef(0);
  const closing = useRef(false);
  const closeCallback = useRef<() => void>(() => {});
  const ref = useDialog(() => closeCallback.current(), enabled && trapFocus);

  const cancel = useCallback(() => {
    generation.current += 1;
    animations.current.forEach(animation => animation.cancel());
    animations.current = [];
    closing.current = false;
  }, []);

  const play = useCallback((exiting: boolean, fromCurrent = false) => {
    const element = ref.current;
    if (!element || typeof element.animate !== "function" || !isPointerInteraction()) return null;
    const root = element.closest<HTMLElement>(".material-viewer,.tutor-overlay,.dialog-overlay,.sidebar-rail") || element;
    const panel = element.matches(".dialog-panel,.material-viewer-panel,.tutor-context-panel,.sidebar-panel,.account-dropdown")
      ? element : element.querySelector<HTMLElement>(".dialog-panel,.material-viewer-panel,.tutor-context-panel,.sidebar-panel") || element;
    const reduced = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches === true;
    const rtl = document.documentElement.dir === "rtl";
    const fromStart = side === "start" || panel.classList.contains("sidebar-panel");
    const direction = (fromStart ? -1 : 1) * (rtl ? -1 : 1);
    const closed = reduced ? "none" : kind === "drawer" ? `translateX(${direction * 100}%)` : `scale(${kind === "popover" ? ".95" : ".96"})`;
    const currentOpacity = getComputedStyle(root).opacity;
    const currentTransform = getComputedStyle(panel).transform;
    const startOpacity = fromCurrent ? currentOpacity : 0;
    const startTransform = fromCurrent ? currentTransform : closed;
    cancel();
    const duration = exiting ? (kind === "popover" ? 125 : 200) : (kind === "popover" ? 180 : 200);
    const easingToken = getComputedStyle(document.documentElement).getPropertyValue(kind === "drawer" ? "--ease-drawer" : "--ease-out").trim();
    const options: KeyframeAnimationOptions = { duration, easing: easingToken || (kind === "drawer" ? EASE_DRAWER : EASE_OUT), fill: "both" };
    root.dataset.motionPhase = exiting ? "closing" : "opening";
    animations.current = root === panel
      ? [panel.animate(exiting
        ? [{ opacity: currentOpacity, transform: currentTransform }, { opacity: 0, transform: closed }]
        : [{ opacity: startOpacity, transform: startTransform }, { opacity: 1, transform: "none" }], options)]
      : [root.animate(exiting ? [{ opacity: currentOpacity }, { opacity: 0 }] : [{ opacity: startOpacity }, { opacity: 1 }], options),
        panel.animate(exiting ? [{ transform: currentTransform }, { transform: closed }] : [{ transform: startTransform }, { transform: "none" }], options)];
    return { root, finished: Promise.all(animations.current.map(animation => animation.finished)), token: generation.current };
  }, [cancel, kind, ref, side]);

  const close = useCallback(() => {
    if (!latest.current.enabled || !latest.current.canClose) return;
    if (closing.current) {
      if (!isPointerInteraction()) { cancel(); latest.current.onClose(); }
      return;
    }
    const motion = play(true);
    if (!motion) { cancel(); latest.current.onClose(); return; }
    closing.current = true;
    void motion.finished.then(() => {
      if (motion.token !== generation.current || !latest.current.enabled) return;
      if (latest.current.canClose) { cancel(); latest.current.onClose(); }
      else { cancel(); delete motion.root.dataset.motionPhase; }
    }).catch(() => { /* Retargeting or unmounting cancels the obsolete completion. */ });
  }, [cancel, play]);
  closeCallback.current = close;

  const toggle = useCallback((open: () => void) => {
    if (!latest.current.enabled) { open(); return; }
    if (!closing.current) { close(); return; }
    const motion = play(false, true);
    if (!motion) {
      cancel();
      if (ref.current) delete (ref.current.closest<HTMLElement>(".material-viewer,.tutor-overlay,.dialog-overlay,.sidebar-rail") || ref.current).dataset.motionPhase;
      return;
    }
    void motion.finished.then(() => {
      if (motion.token === generation.current && !closing.current) {
        cancel(); delete motion.root.dataset.motionPhase;
      }
    }).catch(() => {});
  }, [cancel, close, play, ref]);

  useLayoutEffect(() => {
    if (!enabled) return;
    const motion = play(false);
    if (motion) void motion.finished.then(() => {
      if (motion.token === generation.current && !closing.current) {
        cancel(); delete motion.root.dataset.motionPhase;
      }
    }).catch(() => {});
    return () => { cancel(); if (motion) delete motion.root.dataset.motionPhase; };
  }, [enabled, play, cancel]);

  useLayoutEffect(() => {
    if (!canClose && closing.current) {
      cancel();
      if (ref.current) delete (ref.current.closest<HTMLElement>(".material-viewer,.tutor-overlay,.dialog-overlay,.sidebar-rail") || ref.current).dataset.motionPhase;
    }
  }, [canClose, cancel, ref]);

  return { ref, close, toggle };
}
