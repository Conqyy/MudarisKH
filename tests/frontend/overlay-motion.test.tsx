import React, { useState } from "react";
import { cleanup, fireEvent, render, screen, act } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { InputModalityProvider } from "../../src/lib/input-modality";
import { useOverlayMotion } from "../../src/lib/use-overlay-motion";

type PendingAnimation = { finish: () => void; cancel: ReturnType<typeof vi.fn>; frames: Keyframe[]; options: KeyframeAnimationOptions };
let pending: PendingAnimation[];

beforeEach(() => {
  pending = [];
  vi.stubGlobal("matchMedia", vi.fn(() => ({ matches: false })));
  Object.defineProperty(HTMLElement.prototype, "animate", { configurable: true, value: vi.fn((frames: Keyframe[], options: KeyframeAnimationOptions) => {
    let finish!: () => void;
    let reject!: (error: Error) => void;
    const finished = new Promise<void>((resolve, fail) => { finish = resolve; reject = fail; });
    const cancel = vi.fn(() => reject(new Error("cancelled")));
    pending.push({ finish, cancel, frames, options });
    return { finished, cancel };
  }) });
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); delete document.documentElement.dataset.inputModality; });

function Example({ onClose, busy = false }: { onClose: () => void; busy?: boolean }) {
  const [open, setOpen] = useState(false);
  const { ref, close } = useOverlayMotion(() => { onClose(); setOpen(false); }, { enabled: open, canClose: !busy });
  return <><button onClick={() => setOpen(true)}>Open</button>{open && <div ref={ref} className="dialog-overlay" role="dialog" tabIndex={-1}><div className="dialog-panel"><button onClick={close}>Close</button></div></div>}</>;
}
function openWithPointer() {
  fireEvent.pointerDown(screen.getByText("Open"));
  fireEvent.click(screen.getByText("Open"));
}

function MenuExample({ onClose }: { onClose: () => void }) {
  const [open, setOpen] = useState(false);
  const { ref, toggle } = useOverlayMotion(() => { onClose(); setOpen(false); }, { enabled: open, kind: "popover", trapFocus: false });
  return <><button onClick={() => toggle(() => setOpen(true))}>Account</button>{open && <div ref={ref} className="account-dropdown" role="menu">Account actions</div>}</>;
}

it("reverses a pending menu dismissal from its current presentation without committing the obsolete close", async () => {
  const onClose = vi.fn();
  render(<InputModalityProvider><MenuExample onClose={onClose} /></InputModalityProvider>);
  const trigger = screen.getByText("Account");
  fireEvent.pointerDown(trigger);
  fireEvent.click(trigger);
  await act(async () => { pending[0].finish(); });
  fireEvent.click(trigger);
  const menu = screen.getByRole("menu");
  menu.style.opacity = ".65";
  menu.style.transform = "scale(.98)";
  fireEvent.click(trigger);
  expect(pending).toHaveLength(3);
  expect(pending[1].cancel).toHaveBeenCalledOnce();
  expect(pending[2].frames[0]).toEqual({ opacity: "0.65", transform: "scale(.98)" });
  menu.style.opacity = "";
  menu.style.transform = "";
  await act(async () => { pending.slice(1).forEach(animation => animation.finish()); });
  expect(onClose).not.toHaveBeenCalled();
  expect(screen.getByRole("menu")).toBeTruthy();
});

it("keeps the real dialog and focus owner until pointer exit completes, then closes exactly once", async () => {
  const onClose = vi.fn();
  render(<InputModalityProvider><Example onClose={onClose} /></InputModalityProvider>);
  openWithPointer();
  expect(pending).toHaveLength(2);
  fireEvent.click(screen.getByText("Close"));
  fireEvent.click(screen.getByText("Close"));
  expect(onClose).not.toHaveBeenCalled();
  expect(screen.getByRole("dialog").contains(document.activeElement)).toBe(true);
  expect(pending).toHaveLength(4);
  expect(pending[0].cancel).toHaveBeenCalledOnce();
  await act(async () => { pending.slice(2).forEach(animation => animation.finish()); });
  expect(onClose).toHaveBeenCalledOnce();
  expect(screen.queryByRole("dialog")).toBeNull();
});

it("opens and dismisses keyboard-triggered dialogs immediately", () => {
  const onClose = vi.fn();
  render(<InputModalityProvider><Example onClose={onClose} /></InputModalityProvider>);
  fireEvent.keyDown(screen.getByText("Open"), { key: "Enter" });
  fireEvent.click(screen.getByText("Open"));
  expect(pending).toHaveLength(0);
  fireEvent.keyDown(document, { key: "Escape" });
  expect(onClose).toHaveBeenCalledOnce();
  expect(screen.queryByRole("dialog")).toBeNull();
});

it("lets Escape finish an in-flight pointer dismissal immediately", () => {
  const onClose = vi.fn();
  render(<InputModalityProvider><Example onClose={onClose} /></InputModalityProvider>);
  openWithPointer();
  fireEvent.click(screen.getByText("Close"));
  fireEvent.keyDown(document, { key: "Escape" });
  expect(onClose).toHaveBeenCalledOnce();
  expect(screen.queryByRole("dialog")).toBeNull();
});

it("never animates or dismisses a busy dialog", () => {
  const onClose = vi.fn();
  render(<InputModalityProvider><Example onClose={onClose} busy /></InputModalityProvider>);
  openWithPointer();
  fireEvent.click(screen.getByText("Close"));
  expect(pending).toHaveLength(2);
  fireEvent.keyDown(document, { key: "Escape" });
  expect(onClose).not.toHaveBeenCalled();
  expect(screen.getByRole("dialog")).toBeTruthy();
});

it("cancels a pending dismissal if the dialog becomes busy", async () => {
  const onClose = vi.fn();
  const view = render(<InputModalityProvider><Example onClose={onClose} /></InputModalityProvider>);
  openWithPointer();
  fireEvent.click(screen.getByText("Close"));
  view.rerender(<InputModalityProvider><Example onClose={onClose} busy /></InputModalityProvider>);
  await act(async () => { pending.forEach(animation => animation.finish()); });
  expect(onClose).not.toHaveBeenCalled();
  expect(screen.getByRole("dialog")).toBeTruthy();
});

it("cancels motion ownership on unmount without firing an obsolete close callback", async () => {
  const onClose = vi.fn();
  const view = render(<InputModalityProvider><Example onClose={onClose} /></InputModalityProvider>);
  openWithPointer();
  fireEvent.click(screen.getByText("Close"));
  view.unmount();
  await act(async () => { pending.forEach(animation => animation.finish()); });
  expect(pending.every(animation => animation.cancel.mock.calls.length > 0)).toBe(true);
  expect(onClose).not.toHaveBeenCalled();
});

it("retains opacity feedback without spatial movement for reduced motion", () => {
  vi.stubGlobal("matchMedia", vi.fn(() => ({ matches: true })));
  render(<InputModalityProvider><Example onClose={() => {}} /></InputModalityProvider>);
  openWithPointer();
  const transformFrames = pending.flatMap(animation => animation.frames).filter(frame => "transform" in frame);
  expect(transformFrames.every(frame => frame.transform === "none")).toBe(true);
  expect(pending[0].frames.map(frame => frame.opacity)).toEqual([0, 1]);
});
