"use client";

import { ReactNode } from "react";
import Link from "next/link";
import Navbar from "@/components/Navbar";
import Icon from "@/components/Icon";
import { useLang } from "@/lib/i18n";
import "@/app/entry.css";

export default function EntryShell({ children, footer }: { children: ReactNode; footer?: ReactNode }) {
  const { t } = useLang();
  return (
    <>
      <Navbar />
      <main className="entry-main">
        <aside className="entry-story" aria-label={t("Your study workspace")}>
          <Link href="/" className="entry-wordmark">{t("Mudaris")}<span aria-hidden="true">.</span></Link>
          <h2>{t("Your lectures. A clearer way to study.")}</h2>
          <p>{t("Bring your course material together, confirm your lecture foundation, and make room for understanding.")}</p>
          <div className="entry-story-path">
            {([
              ["file", "Add your lectures", "Start with the material you learn from."],
              ["check-circle", "Confirm your foundation", "Keep study tools grounded in your course."],
              ["layers", "Build your study collection", "Practice, review, and ask better questions."],
            ] as const).map(([icon, title, description]) => (
              <div className="entry-story-step" key={title}>
                <span className="entry-story-icon"><Icon name={icon} size={19} /></span>
                <div><strong>{t(title)}</strong><span>{t(description)}</span></div>
              </div>
            ))}
          </div>
          <p className="entry-language-note"><Icon name="globe" size={17} />{t("Made for studying in Arabic and English.")}</p>
        </aside>
        <div className="entry-form-column">
          <div className="entry-form-panel">{children}</div>
          {footer && <div className="entry-form-footer">{footer}</div>}
        </div>
      </main>
    </>
  );
}

export function GoogleButton({ onClick, disabled }: { onClick: () => void; disabled: boolean }) {
  const { t } = useLang();
  return (
    <button type="button" onClick={onClick} disabled={disabled} className="ui-button secondary entry-google">
      <svg width="19" height="19" viewBox="0 0 24 24" aria-hidden="true">
        <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" />
        <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" />
        <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" />
        <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" />
      </svg>
      {t("Continue with Google")}
    </button>
  );
}

export function AuthDivider() {
  const { t } = useLang();
  return <div className="entry-divider"><span>{t("or use email")}</span></div>;
}

export function EntryError({ error }: { error: string }) {
  const { t } = useLang();
  return error ? <div className="entry-notice error" role="alert"><Icon name="alert" size={18} /><span>{t(error)}</span></div> : null;
}
