import React, { useRef, useState } from "react";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { InputModalityProvider } from "../../src/lib/input-modality";
import { useSidebarLayoutMotion } from "../../src/lib/use-sidebar-layout-motion";

type Motion = { element: HTMLElement; frames: Keyframe[]; options: KeyframeAnimationOptions; finish: () => void; cancel: ReturnType<typeof vi.fn> };
let motions: Motion[];
let presentation: WeakMap<Element, DOMRect>;
let reduced = false;
let desktop = true;
const box = (left: number, top: number, width: number, height = 50) => ({ left, top, width, height, right: left + width, bottom: top + height, x: left, y: top, toJSON: () => ({}) }) as DOMRect;

beforeEach(() => {
  motions = []; presentation = new WeakMap(); reduced = false; desktop = true;
  document.documentElement.dir = "ltr";
  vi.stubGlobal("matchMedia", vi.fn((query: string) => ({ matches: query.includes("min-width") ? desktop : reduced })));
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function (this: HTMLElement) {
    if (presentation.has(this)) return presentation.get(this)!;
    const compact = this.closest<HTMLElement>(".app-shell")?.dataset.compact === "true";
    const rtl = document.documentElement.dir === "rtl";
    if (this.classList.contains("sidebar-glass")) return box(rtl ? 1200 - (compact ? 72 : 224) : 30, 112, compact ? 72 : 224, 700);
    if (this.classList.contains("sidebar-item")) return box(rtl ? 1132 : 42, compact ? 160 : 190, 46);
    if (this.classList.contains("app-workspace")) return rtl ? box(18, 112, compact ? 1062 : 910, 700) : box(compact ? 120 : 272, 112, compact ? 1062 : 910, 700);
    return box(0, 0, 0);
  });
  Object.defineProperty(HTMLElement.prototype, "animate", { configurable: true, value: vi.fn(function (this: HTMLElement, frames: Keyframe[], options: KeyframeAnimationOptions) {
    let finish!: () => void, reject!: (error: Error) => void;
    const finished = new Promise<void>((resolve, fail) => { finish = resolve; reject = fail; });
    const element = this;
    const cancel = vi.fn(() => { presentation.delete(element); reject(new Error("cancelled")); });
    motions.push({ element, frames, options, finish, cancel });
    return { finished, cancel };
  }) });
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); delete document.documentElement.dataset.inputModality; document.documentElement.dir = "ltr"; });

function Example({ initialCompact = true, dialog = false }: { initialCompact?: boolean; dialog?: boolean }) {
  const [compact, setCompact] = useState(initialCompact);
  const panel = useRef<HTMLDivElement>(null);
  const animateChange = useSidebarLayoutMotion(compact, panel);
  return <div className="app-shell" data-compact={compact}>
    <aside><div className="sidebar-panel" ref={panel}><div className="sidebar-glass" /><div className="sidebar-content">
      <button className="sidebar-item" onClick={() => animateChange(() => setCompact(value => !value))}>Toggle sidebar<span className="sidebar-label" style={{ display: compact ? "none" : "inline", opacity: 1 }}>Workspace labels</span></button>
    </div></div></aside>
    <main className="app-workspace"><button>Open source</button>{dialog && <div role="dialog">Sources</div>}</main>
  </div>;
}
function pointerToggle() { const button = screen.getByRole("button", { name: /Toggle sidebar/ }); fireEvent.pointerDown(button); fireEvent.click(button); }
const mount = (props: React.ComponentProps<typeof Example> = {}) => render(<InputModalityProvider><Example {...props} /></InputModalityProvider>);

it.each(["ltr", "rtl"])("animates expansion and collapse without scaling readable content in %s", async dir => {
  document.documentElement.dir = dir;
  mount();
  expect(motions).toHaveLength(0);
  pointerToggle();
  const glass = motions.find(motion => motion.element.classList.contains("sidebar-glass"))!;
  const workspace = motions.find(motion => motion.element.classList.contains("app-workspace"))!;
  expect(glass.frames[0].transform).toBe(`scaleX(${72 / 224})`);
  expect(workspace.frames[0].transform).toBe(`translateX(${dir === "rtl" ? 152 : -152}px)`);
  expect(motions.filter(motion => !motion.element.classList.contains("sidebar-glass")).every(motion => motion.frames.every(frame => !String(frame.transform).includes("scale")))).toBe(true);
  expect(glass.options.duration).toBe(240);
  await act(async () => { motions.forEach(motion => motion.finish()); });
  const previous = motions.length;
  pointerToggle();
  const collapse = motions.slice(previous).find(motion => motion.element.classList.contains("sidebar-glass"))!;
  expect(collapse.frames[0].transform).toBe(`scaleX(${224 / 72})`);
});

it("reverses from the currently presented geometry and cancels obsolete completions", async () => {
  mount(); pointerToggle();
  const glass = screen.getByRole("button", { name: /Toggle sidebar/ }).closest(".sidebar-panel")!.querySelector<HTMLElement>(".sidebar-glass")!;
  presentation.set(glass, box(30, 112, 125, 700));
  const previous = motions.length;
  pointerToggle();
  expect(motions.slice(0, previous).every(motion => motion.cancel.mock.calls.length === 1)).toBe(true);
  expect(motions.slice(previous).find(motion => motion.element === glass)!.frames[0].transform).toBe(`scaleX(${125 / 72})`);
  await act(async () => { motions.slice(0, previous).forEach(motion => motion.finish()); });
  expect(glass.closest<HTMLElement>(".sidebar-panel")!.dataset.sidebarMotion).toBe("true");
});

it("keeps hydration and keyboard toggles immediate", () => {
  mount({ initialCompact: false });
  expect(motions).toHaveLength(0);
  const button = screen.getByRole("button", { name: /Toggle sidebar/ });
  fireEvent.keyDown(button, { key: "Enter" }); fireEvent.click(button);
  expect(motions).toHaveLength(0);
});

it("retains opacity feedback without spatial motion for reduced motion", () => {
  reduced = true; mount(); pointerToggle();
  expect(motions.length).toBeGreaterThan(0);
  expect(motions.every(motion => motion.frames.every(frame => !("transform" in frame)))).toBe(true);
  expect(motions.every(motion => motion.options.duration === 200)).toBe(true);
});

it.each(["outside pointer", "keyboard", "resize", "direction"])("clears temporary transforms before %s context changes", async action => {
  mount(); pointerToggle();
  if (action === "outside pointer") fireEvent.pointerDown(screen.getByRole("button", { name: "Open source" }));
  if (action === "keyboard") fireEvent.keyDown(document, { key: "Tab" });
  if (action === "resize") fireEvent(window, new Event("resize"));
  if (action === "direction") await act(async () => { document.documentElement.dir = "rtl"; });
  expect(motions.every(motion => motion.cancel.mock.calls.length > 0)).toBe(true);
  expect(document.querySelector<HTMLElement>(".sidebar-panel")!.dataset.sidebarMotion).toBeUndefined();
});

it("does not transform a workspace that already owns a fixed dialog", () => {
  mount({ dialog: true }); pointerToggle();
  expect(motions.some(motion => motion.element.classList.contains("sidebar-glass"))).toBe(true);
  expect(motions.some(motion => motion.element.classList.contains("app-workspace"))).toBe(false);
});

it("leaves mobile drawer ownership alone and cancels running desktop motion on unmount", () => {
  desktop = false; const view = mount(); pointerToggle(); expect(motions).toHaveLength(0);
  desktop = true; pointerToggle(); expect(motions.length).toBeGreaterThan(0);
  view.unmount(); expect(motions.every(motion => motion.cancel.mock.calls.length > 0)).toBe(true);
});
