import React from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import UploadDocumentModal from "../../src/components/UploadDocumentModal";
import UploadAudioModal from "../../src/components/UploadAudioModal";
import SupportingMaterialAction from "../../src/components/SupportingMaterialAction";

vi.mock("@/lib/auth-context", () => ({ useAuth: () => ({ user: { uid: "u1" } }) }));
vi.mock("@/lib/api", () => ({ apiFetch: vi.fn(), apiJson: vi.fn() }));
vi.mock("@/lib/i18n", () => ({ useLang: () => ({ t: (value: string) => value }) }));
vi.mock("@/hooks/useSupportingAnalysis", () => ({ useSupportingAnalysis: () => ({ status: { status: "completed", reportRevision: "r1" }, report: null, error: "", retry: vi.fn() }) }));
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

it.each([["documents", UploadDocumentModal], ["recordings", UploadAudioModal]] as const)("offers a native keyboard browse control for %s", (_, Component) => {
  const click = vi.spyOn(HTMLInputElement.prototype, "click");
  render(<Component courseId="c1" onClose={() => {}} onSuccess={() => {}} />);
  const browse = screen.getByRole("button", { name: /browse/i });
  expect(browse.tagName).toBe("BUTTON");
  fireEvent.click(browse);
  expect(click).toHaveBeenCalledOnce();
});

it("owns focus and restores the report trigger when a supporting report closes", () => {
  render(<SupportingMaterialAction kind="tutorial" materialId="t1" courseId="c1" />);
  const trigger = screen.getByRole("button", { name: "Supporting material report" });
  trigger.focus();
  fireEvent.click(trigger);
  const dialog = screen.getByRole("dialog", { name: "Supporting material report" });
  expect(dialog.contains(document.activeElement)).toBe(true);
  fireEvent.keyDown(document, { key: "Escape" });
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(document.activeElement).toBe(trigger);
});
