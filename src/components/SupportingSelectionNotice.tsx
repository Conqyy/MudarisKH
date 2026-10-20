"use client";

import { useLang } from "@/lib/i18n";
import { SupportingPresentation } from "@/lib/supporting-materials";

export function selectionReasonText(reason: SupportingPresentation): string {
  if (reason === "waiting") return "Selected material is still being analyzed. Wait or deselect it.";
  if (reason === "missing") return "This selected material was removed. Deselect it to continue.";
  return "Selected material is unavailable. Retry or deselect it.";
}
export default function SupportingSelectionNotice({ blocker, onDeselect, onRefresh }: { blocker: { id: string; row?: { title?: string }; reason: SupportingPresentation } | null; onDeselect: (id: string) => void; onRefresh: () => void }) {
  const { t } = useLang();
  if (!blocker) return null;
  return <div className="border border-gold/40 rounded-xl bg-gold/10 p-3 text-sm" role="alert"><p>{blocker.row?.title && <strong dir="auto">{blocker.row.title}: </strong>}{t(selectionReasonText(blocker.reason))}</p><div className="flex gap-4 mt-2"><button type="button" className="underline" onClick={onRefresh}>{t("Refresh material status")}</button><button type="button" className="underline" onClick={() => onDeselect(blocker.id)}>{t("Deselect material")}</button></div></div>;
}
