"use client";

import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { useLang } from "@/lib/i18n";

export interface SourceRef { documentId: string; sourceRevision: string; unitId: string; label?: string; }
/** Only server citation identity can open evidence; labels are display metadata. */
export function validatedSourceRefs(value: unknown): SourceRef[] {
  if (!Array.isArray(value)) return [];
  const seen = new Set<string>();
  return value.flatMap(ref => {
    if (!ref || [ref.documentId, ref.sourceRevision, ref.unitId].some(v => typeof v !== "string" || !v.trim())) return [];
    const key = JSON.stringify([ref.documentId, ref.sourceRevision, ref.unitId]);
    if (seen.has(key)) return [];
    seen.add(key);
    return [{ documentId: ref.documentId, sourceRevision: ref.sourceRevision, unitId: ref.unitId, ...(typeof ref.label === "string" && ref.label.trim() ? { label: ref.label } : {}) }];
  });
}
const API_URL = process.env.NEXT_PUBLIC_BACKEND_URL || "http://127.0.0.1:8000";
export default function SourceCitation({ sourceRefs, courseId }: { sourceRefs: unknown; courseId: string }) {
  const { user } = useAuth();
  const { t } = useLang();
  const refs = validatedSourceRefs(sourceRefs);
  const identity = JSON.stringify([user?.uid, courseId, refs]);
  const [selection, setSelection] = useState<{ identity: string; ref: SourceRef } | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [preview, setPreview] = useState<{ identity: string; text?: string; images?: string[]; warnings?: string[]; error?: string; unavailable?: boolean } | null>(null);
  const selected = selection?.identity === identity ? selection.ref : null;
  const previewKey = JSON.stringify([identity, selected]);
  useEffect(() => {
    if (!selected || !user?.uid) return;
    const controller = new AbortController();
    setPreview(null);
    const ref = selected;
    const url = `${API_URL}/api/documents/${encodeURIComponent(ref.documentId)}/sources/${encodeURIComponent(ref.unitId)}?source_revision=${encodeURIComponent(ref.sourceRevision)}`;
    (async () => {
      try {
        const res = await apiFetch(url, { signal: controller.signal });
        if (controller.signal.aborted) return;
        if (!res.ok) {
          setPreview({ identity: previewKey, error: res.status === 404 || res.status === 409 ? "This source version is unavailable." : "Could not load source. Retry.", unavailable: res.status === 404 || res.status === 409 });
          return;
        }
        const data = await res.json();
        if (controller.signal.aborted) return;
        const unit = data.unit;
        if (!unit || unit.documentId !== ref.documentId || unit.sourceRevision !== ref.sourceRevision || unit.unitId !== ref.unitId) throw new Error("Unavailable source identity");
        setPreview({ identity: previewKey, text: [unit.text, unit.visualText].filter((value: unknown) => typeof value === "string" && value.trim()).join("\n\n"), warnings: Array.isArray(unit.warnings) ? unit.warnings.filter((value: unknown) => typeof value === "string") : [], images: Array.isArray(data.images) ? data.images.filter((image: unknown) => typeof image === "string" && /^data:image\/(png|jpeg|webp);base64,[A-Za-z0-9+/=\s]+$/.test(image)) : [] });
      } catch {
        if (!controller.signal.aborted) setPreview({ identity: previewKey, error: "Could not load source. Retry." });
      }
    })();
    return () => controller.abort();
  }, [identity, previewKey, selected, attempt, user?.uid]);
  if (!refs.length) return null;
  const current = preview?.identity === previewKey ? preview : null;
  return <div className="mt-3 text-xs text-ink-soft" onClick={event => event.stopPropagation()}>
    <div className="flex flex-wrap items-center gap-2"><span>{t("Sources")}:</span>{refs.map(ref => <button type="button" key={JSON.stringify([ref.documentId, ref.sourceRevision, ref.unitId])} className="underline hover:text-accent" onClick={() => { setPreview(null); setSelection({ identity, ref }); }}>{ref.label || ref.unitId}</button>)}</div>
    {selected && <div className="mt-2 p-3 border border-line rounded-xl bg-bg" role="region" aria-label={t("Source preview")}>
      <button type="button" className="float-end underline" onClick={() => setSelection(null)}>{t("Close source")}</button>
      {!current ? <p>{t("Loading source…")}</p> : current.error ? <div role="alert"><p>{t(current.error)}</p>{<button type="button" className="underline mt-2" onClick={() => setAttempt(n => n + 1)}>{t("Retry source")}</button>}</div> : <>
        {current.text ? <pre className="whitespace-pre-wrap font-sans leading-relaxed">{current.text}</pre> : !current.images?.length && <p>{t("This source unit is blank.")}</p>}
        {current.warnings?.map((warning, i) => <p key={`warning-${i}`} className="text-gold mt-2">{warning}</p>)}
        {current.images?.map((src, i) => <img key={i} src={src} alt={`${selected.label || selected.unitId} ${i + 1}`} className="max-w-full mt-3" />)}
      </>}
    </div>}
  </div>;
}
