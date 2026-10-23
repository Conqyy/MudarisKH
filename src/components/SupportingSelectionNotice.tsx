"use client";

import { useLang } from "@/lib/i18n";
import Icon from "@/components/Icon";
import { SupportingPresentation } from "@/lib/supporting-materials";

export function selectionReasonText(reason: SupportingPresentation): string {
  if (reason === "waiting") return "Selected material is still being analyzed. Wait or deselect it.";
  if (reason === "missing") return "This selected material was removed. Deselect it to continue.";
  return "Selected material is unavailable. Retry or deselect it.";
}
export default function SupportingSelectionNotice({ blocker, onDeselect, onRefresh }: { blocker: { id: string; row?: { title?: string }; reason: SupportingPresentation } | null; onDeselect: (id: string) => void; onRefresh: () => void }) {
  const { t } = useLang();
  if (!blocker) return null;
  return <div className="material-inline-notice warning" role="alert"><div className="flex items-start gap-2"><Icon name="alert" size={18} className="shrink-0 mt-0.5" /><p>{blocker.row?.title && <strong dir="auto">{blocker.row.title}: </strong>}{t(selectionReasonText(blocker.reason))}</p></div><div className="flex flex-wrap gap-2 mt-3"><button type="button" className="ui-button secondary" onClick={onRefresh}><Icon name="refresh" size={16} />{t("Refresh material status")}</button><button type="button" className="ui-button ghost" onClick={() => onDeselect(blocker.id)}>{t("Deselect material")}</button></div></div>;
}
