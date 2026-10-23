"use client";

import Icon, { type IconName } from "@/components/Icon";
import { useLang } from "@/lib/i18n";
import { supportingPresentation, type SupportingRow } from "@/lib/supporting-materials";
import "./study-workspace.css";

export function StudyHeader({ title, description, icon, libraryCount = 0 }: { title: string; description: string; icon: IconName; libraryCount?: number }) {
  const { t } = useLang();
  return (
    <header className="page-header study-page-header">
      <div className="study-heading-group">
        <span className="study-tool-icon"><Icon name={icon} size={24} /></span>
        <div>
          <h1 className="page-heading">{t(title)}</h1>
          <p className="page-subtitle">{t(description)}</p>
        </div>
      </div>
      {libraryCount > 0 && <a className="ui-button secondary" href="#study-library"><Icon name="history" size={18} />{t("Saved library")}<span className="study-count">{libraryCount}</span></a>}
    </header>
  );
}

export function StudyBusy({ opening = false, loading = false, title }: { opening?: boolean; loading?: boolean; title: string }) {
  const { t } = useLang();
  return (
    <section className="ui-panel study-busy" role="status" aria-live="polite">
      <span className="study-busy-icon"><Icon name="loader" size={28} className="animate-spin" /></span>
      <h2 className="section-heading">{t(opening ? "Opening saved item…" : title)}</h2>
      <p className="page-subtitle">{t(loading ? "Loading your course workspace." : opening ? "Your saved study material will appear here." : "Working with your selected course materials. Keep this tab open until it is ready.")}</p>
    </section>
  );
}

export function StudySourceStatus({ row }: { row: SupportingRow }) {
  const { t } = useLang();
  const state = supportingPresentation(row);
  const label = state === "usable" ? "Ready" : state === "waiting" ? "Analyzing" : state === "missing" ? "Missing" : row.stale ? "Needs refresh" : row.legacy ? "Needs preparation" : "Unavailable";
  return <span className={`study-source-status ${state}`}><Icon name={state === "usable" ? "check-circle" : state === "waiting" ? "clock" : "alert"} size={12} />{t(label)}</span>;
}
