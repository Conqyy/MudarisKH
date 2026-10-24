"use client";
import { useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { useLang } from "@/lib/i18n";
import { isPointerInteraction } from "@/lib/input-modality";
import Icon, { type IconName } from "./Icon";
import "./course-material-panel.css";

type Props = { id: string; title: string; icon: IconName; count: number; summary: string; description?: string; overview: boolean; actions: ReactNode; holdOpen?: boolean; children: ReactNode };

export default function CourseMaterialPanel({ id, title, icon, count, summary, description, overview, actions, holdOpen = false, children }: Props) {
  const { t } = useLang();
  const [hovered, setHovered] = useState(false);
  const [pinned, setPinned] = useState(false);
  const [focused, setFocused] = useState(false);
  const [height, setHeight] = useState(0);
  const [motion, setMotion] = useState<"instant" | "pointer" | "reduced">("instant");
  const ignoreHover = useRef(false);
  const trigger = useRef<HTMLButtonElement>(null);
  const inner = useRef<HTMLDivElement>(null);
  const details = useRef<HTMLDivElement>(null);
  const expanded = !overview || hovered || pinned || focused || holdOpen;

  const feedback = (animate: boolean) => setMotion(!animate ? "instant" : window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ? "reduced" : "pointer");
  const close = () => {
    if (details.current?.contains(document.activeElement)) trigger.current?.focus();
    ignoreHover.current = true;
    setHovered(false); setPinned(false); setFocused(false);
  };
  useLayoutEffect(() => {
    if (!overview) {
      ignoreHover.current = false;
      setHovered(false); setPinned(false); setFocused(false); setMotion("instant");
    } else if (holdOpen) {
      // Keep the opener available until the viewer has restored its focus.
      setPinned(true);
    }
  }, [overview, holdOpen]);
  useLayoutEffect(() => {
    if (!overview || !expanded) { setHeight(0); return; }
    const measure = () => setHeight(inner.current?.scrollHeight || 0);
    measure();
    if (typeof ResizeObserver === "undefined" || !inner.current) return;
    const observer = new ResizeObserver(measure);
    observer.observe(inner.current);
    return () => observer.disconnect();
  }, [expanded, overview]);

  return <section id={id} aria-label={title} className={`course-material-panel ${overview ? "is-overview" : "mb-12"}`} data-expanded={expanded} data-motion={motion}
    onPointerEnter={event => {
      if (!overview || ignoreHover.current || !["mouse", "pen"].includes(event.pointerType) || !window.matchMedia?.("(hover: hover) and (pointer: fine)").matches) return;
      feedback(true); setHovered(true);
    }}
    onPointerLeave={() => { if (overview) { feedback(true); ignoreHover.current = false; setHovered(false); setFocused(!!details.current?.contains(document.activeElement)); } }}
    onFocusCapture={event => { if (overview && details.current?.contains(event.target)) { if (!isPointerInteraction()) feedback(false); setFocused(true); } }}
    onBlurCapture={event => {
      if (!overview || details.current?.contains(event.relatedTarget as Node | null)) return;
      if (!isPointerInteraction()) feedback(false);
      setFocused(false);
    }}
    onKeyDown={event => {
      if (!overview || event.defaultPrevented || event.key !== "Escape" || !expanded || holdOpen || (event.target as HTMLElement).closest('[role="dialog"], [aria-modal="true"], dialog')) return;
      event.preventDefault(); event.stopPropagation(); feedback(false); close();
    }}>
    <header className="course-material-panel-header">
      <div className="course-material-panel-heading">
        <h2 aria-label={title}>{overview ? <button ref={trigger} type="button" className="course-material-panel-toggle" aria-label={title} aria-describedby={`${id}-count ${id}-summary`} aria-expanded={expanded} aria-controls={`${id}-details`} title={t(expanded ? "Hide details" : "Show details")}
          onClick={event => { feedback(event.detail > 0); if (expanded) close(); else setPinned(true); }}>
          <span className="course-material-panel-symbol"><Icon name={icon} size={22} /></span>
          <span className="course-material-panel-title">{title}</span>
          <span className="course-material-panel-count" id={`${id}-count`}>{count}</span>
          <Icon name="chevron-down" size={18} className="course-material-panel-chevron" />
        </button> : title}</h2>
        {!overview && description && <p className="text-ink-soft text-sm mt-1">{description}</p>}
      </div>
      {!overview && actions}
    </header>
    {overview && <p className="course-material-panel-summary" id={`${id}-summary`}>{summary}</p>}
    <div ref={details} className="course-material-panel-disclosure" id={`${id}-details`} aria-hidden={overview && !expanded ? true : undefined} inert={overview && !expanded ? true : undefined} style={overview ? { height: `${height}px`, opacity: expanded ? 1 : 0 } : undefined}>
      <div className="course-material-panel-content" ref={inner}>
        {overview && <div className="course-material-panel-detail-heading">{description && <p>{description}</p>}{actions}</div>}
        {children}
      </div>
    </div>
  </section>;
}
