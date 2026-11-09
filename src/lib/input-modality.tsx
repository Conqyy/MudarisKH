"use client";

import { useEffect, type ReactNode } from "react";

/** Pointer feedback includes touch; keyboard navigation never inherits its motion. */
export function InputModalityProvider({ children }: { children: ReactNode }) {
  useEffect(() => {
    document.documentElement.dataset.inputModality = "keyboard";
    const pointer = () => { document.documentElement.dataset.inputModality = "pointer"; };
    const keyboard = () => { document.documentElement.dataset.inputModality = "keyboard"; };
    document.addEventListener("pointerdown", pointer, true);
    document.addEventListener("keydown", keyboard, true);
    return () => {
      document.removeEventListener("pointerdown", pointer, true);
      document.removeEventListener("keydown", keyboard, true);
    };
  }, []);
  return children;
}

export function isPointerInteraction() {
  return document.documentElement.dataset.inputModality === "pointer";
}
