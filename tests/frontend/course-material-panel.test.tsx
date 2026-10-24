import React from "react";
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import CourseMaterialPanel from "../../src/components/CourseMaterialPanel";

vi.mock("@/lib/i18n", () => ({ useLang: () => ({ t: (value: string) => value }) }));
let fine = true, reduced = false;
const disconnect = vi.fn();
beforeEach(() => {
  fine = true; reduced = false;
  vi.stubGlobal("matchMedia", vi.fn((query: string) => ({ matches: query.includes("hover") ? fine : reduced })));
  vi.stubGlobal("ResizeObserver", class { observe() {} disconnect = disconnect; });
  vi.spyOn(HTMLElement.prototype, "scrollHeight", "get").mockReturnValue(408);
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

function mount(props: Partial<React.ComponentProps<typeof CourseMaterialPanel>> = {}) {
  return render(<CourseMaterialPanel id="documents" title="Documents" icon="file" count={10} summary="Lecture sources" overview actions={<button>Upload</button>} {...props}><div className="course-material-panel-body"><button>Open lecture</button><input aria-label="Rename lecture" />{props.children}</div></CourseMaterialPanel>);
}
const toggle = () => screen.getByRole("button", { name: "Documents" });
const section = () => screen.getByRole("region", { name: "Documents" });
const details = () => document.getElementById("documents-details")!;
function pointer(type: "over" | "out", pointerType = "mouse") {
  const event = new MouseEvent(`pointer${type}`, { bubbles: true, relatedTarget: type === "out" ? document.body : null });
  Object.defineProperty(event, "pointerType", { value: pointerType });
  fireEvent(section(), event);
}

it("starts as a compact summary with details hidden from focus and accessibility", () => {
  mount();
  expect(toggle().getAttribute("aria-expanded")).toBe("false");
  expect(details().getAttribute("aria-hidden")).toBe("true");
  expect(details().hasAttribute("inert")).toBe(true);
  expect(screen.queryByRole("button", { name: "Upload" })).toBeNull();
  expect(within(section()).getByText("10")).toBeTruthy();
});

it("expands to measured content height on fine mouse hover and reverses on leave", () => {
  mount(); pointer("over");
  expect(toggle().getAttribute("aria-expanded")).toBe("true");
  expect(details().style.height).toBe("408px");
  expect(section().dataset.motion).toBe("pointer");
  pointer("out");
  expect(details().style.height).toBe("0px");
  expect(toggle().getAttribute("aria-expanded")).toBe("false");
  pointer("over");
  expect(details().style.height).toBe("408px");
});

it.each(["touch", "coarse"])("does not expand from %s hover and supports an explicit tap", mode => {
  fine = mode !== "coarse";
  mount(); pointer("over", mode === "touch" ? "touch" : "mouse");
  expect(toggle().getAttribute("aria-expanded")).toBe("false");
  fireEvent.click(toggle(), { detail: 1 });
  expect(toggle().getAttribute("aria-expanded")).toBe("true");
  fireEvent.click(toggle(), { detail: 1 });
  expect(toggle().getAttribute("aria-expanded")).toBe("false");
});

it("can explicitly close a hovered card until the pointer leaves and returns", () => {
  mount(); pointer("over"); fireEvent.click(toggle(), { detail: 1 });
  expect(toggle().getAttribute("aria-expanded")).toBe("false");
  pointer("out"); pointer("over");
  expect(toggle().getAttribute("aria-expanded")).toBe("true");
});

it("keeps keyboard toggles immediate and closes with Escape to its summary", () => {
  mount(); fireEvent.click(toggle(), { detail: 0 });
  expect(section().dataset.motion).toBe("instant");
  act(() => screen.getByRole("button", { name: "Open lecture" }).focus());
  fireEvent.keyDown(document.activeElement!, { key: "Escape" });
  expect(toggle().getAttribute("aria-expanded")).toBe("false");
  expect(document.activeElement).toBe(toggle());
  expect(section().dataset.motion).toBe("instant");
});

it("keeps hovered details open while editing and closes after focus leaves", () => {
  mount(); pointer("over");
  act(() => screen.getByLabelText("Rename lecture").focus()); pointer("out");
  expect(toggle().getAttribute("aria-expanded")).toBe("true");
  fireEvent.blur(screen.getByLabelText("Rename lecture"), { relatedTarget: document.body });
  expect(toggle().getAttribute("aria-expanded")).toBe("false");
});

it("holds details open for an owned viewer and leaves nested dialog Escape alone", () => {
  const view = mount({ holdOpen: true, children: <div role="dialog"><button>Close report</button></div> });
  expect(toggle().getAttribute("aria-expanded")).toBe("true");
  fireEvent.keyDown(screen.getByRole("button", { name: "Close report" }), { key: "Escape" });
  expect(toggle().getAttribute("aria-expanded")).toBe("true");
  view.rerender(<CourseMaterialPanel id="documents" title="Documents" icon="file" count={10} summary="Lecture sources" overview actions={null}><div>Sources</div></CourseMaterialPanel>);
  expect(toggle().getAttribute("aria-expanded")).toBe("true");
  fireEvent.keyDown(toggle(), { key: "Escape" });
  expect(toggle().getAttribute("aria-expanded")).toBe("false");
});

it("uses the reduced-motion presentation for pointer changes and cleans up observation", () => {
  reduced = true; const view = mount(); pointer("over");
  expect(section().dataset.motion).toBe("reduced");
  view.unmount(); expect(disconnect).toHaveBeenCalled();
});

it("keeps the viewer opener available when its external hold releases", () => {
  const content = <div className="course-material-panel-body"><button>Open viewer</button></div>;
  const props = { id: "documents", title: "Documents", icon: "file" as const, count: 10, summary: "Lecture sources", overview: true, actions: null };
  const view = render(<CourseMaterialPanel {...props} holdOpen>{content}</CourseMaterialPanel>);
  const opener = screen.getByRole("button", { name: "Open viewer" });
  const outside = document.createElement("button"); document.body.append(outside);
  act(() => outside.focus()); pointer("out");
  view.rerender(<CourseMaterialPanel {...props}>{content}</CourseMaterialPanel>);
  expect(details().hasAttribute("inert")).toBe(false);
  act(() => opener.focus());
  expect(document.activeElement).toBe(opener);
  expect(toggle().getAttribute("aria-expanded")).toBe("true");
  outside.remove();
});

it("leaves Escape with an editing control that already consumed the key", () => {
  mount({ children: <input aria-label="Nested editor" onKeyDown={event => event.preventDefault()} /> });
  fireEvent.click(toggle());
  fireEvent.keyDown(screen.getByLabelText("Nested editor"), { key: "Escape" });
  expect(toggle().getAttribute("aria-expanded")).toBe("true");
});

it("keeps the sequential Materials view fully open without a disclosure", () => {
  mount({ overview: false, description: "All lecture sources" });
  expect(screen.queryByRole("button", { name: "Documents" })).toBeNull();
  expect(screen.getByRole("heading", { name: "Documents" })).toBeTruthy();
  expect(screen.getByRole("button", { name: "Upload" })).toBeTruthy();
  expect(screen.getByRole("button", { name: "Open lecture" })).toBeTruthy();
});
