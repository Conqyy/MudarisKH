"use client";

import { useEffect, useRef, useState } from "react";
import { useAuth } from "@/lib/auth-context";
import { useLang } from "@/lib/i18n";
import { getSupportingOriginal, getSupportingSource, SupportingRef, SupportingSource, validatedSupportingRefs } from "@/lib/supporting-materials";

export default function SupportingCitation({ sourceRefs, courseId }: { sourceRefs: unknown; courseId: string }) {
  const { user } = useAuth();
  const { t } = useLang();
  const refs = validatedSupportingRefs(sourceRefs);
  const identity = JSON.stringify([user?.uid, courseId, refs]);
  const [selection, setSelection] = useState<{ identity: string; ref: SupportingRef } | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [preview, setPreview] = useState<{ key: string; source?: SupportingSource; error?: string; unavailable?: boolean } | null>(null);
  const [original, setOriginal] = useState<{ key: string; url: string } | null>(null);
  const originalRequest = useRef<AbortController | null>(null);
  const selected = selection?.identity === identity ? selection.ref : null;
  const key = JSON.stringify([identity, selected]);
  useEffect(() => {
    if (!selected || !user?.uid) return;
    const controller = new AbortController();
    setPreview(null);
    setOriginal(null);
    getSupportingSource(selected, controller.signal, courseId).then(source => {
      if (!controller.signal.aborted) setPreview({ key, source });
    }).catch(error => {
      if (!controller.signal.aborted) setPreview({ key, error: error?.status === 404 || error?.status === 409 ? "This source version is unavailable." : "Could not load source. Retry.", unavailable: error?.status === 404 || error?.status === 409 });
    });
    return () => controller.abort();
  }, [attempt, courseId, key, selected, user?.uid]);
  useEffect(() => () => { if (original?.url) URL.revokeObjectURL(original.url); }, [original]);
  useEffect(() => () => originalRequest.current?.abort(), [key]);
  if (!refs.length) return null;
  const current = preview?.key === key ? preview : null;
  const source = current?.source;
  const originalLink = original?.key === key ? original.url + (Number.isInteger(source?.originalPage) && (source?.originalPage || 0) > 0 ? `#page=${source?.originalPage}` : "") : null;
  return <div className="mt-3 text-xs text-ink-soft" onClick={event => event.stopPropagation()}>
    <div className="flex flex-wrap items-center gap-2"><span>{t("Original source")}:</span>{refs.map(ref => <button type="button" key={JSON.stringify(ref)} className="underline hover:text-accent" onClick={() => { setPreview(null); setSelection({ identity, ref }); }}>{ref.unitId}</button>)}</div>
    {selected && <div className="mt-2 p-3 border border-line rounded-xl bg-bg" role="region" aria-label={t("Source preview")}>
      <button type="button" className="float-end underline" onClick={() => setSelection(null)}>{t("Close source")}</button>
      {!current ? <p>{t("Loading source…")}</p> : current.error ? <div role="alert"><p>{t(current.error)}</p>{!current.unavailable && <button type="button" className="underline mt-2" onClick={() => setAttempt(value => value + 1)}>{t("Retry source")}</button>}</div> : source && <>
        {selected.kind === "notes" && <p className="mb-2">{t("This passage is from your typed notes.")}</p>}
        {source.unit.timing ? <p>{source.unit.timing.startSeconds.toFixed(1)}–{source.unit.timing.endSeconds.toFixed(1)} {t("seconds")}</p> : selected.kind === "audio" && <p>{t("No recording time available")}</p>}
        {[source.unit.text, source.unit.visualText].filter(value => typeof value === "string" && value.trim()).map((text, index) => <pre key={index} dir="auto" className="whitespace-pre-wrap font-sans leading-relaxed">{text}</pre>)}
        {!source.unit.text && !source.unit.visualText && !source.unit.visualAssets?.length && <p>{t("This source unit is blank.")}</p>}
        {source.unit.visualAssets?.length > 0 && <p>{t("The original page contains visual content.")}</p>}
        {originalLink ? <a className="underline" href={originalLink} target="_blank" rel="noopener noreferrer">{t("Open original")}</a> : <button type="button" className="underline" onClick={async () => {
          originalRequest.current?.abort();
          const request = new AbortController();
          originalRequest.current = request;
          try { const url = await getSupportingOriginal(selected, courseId, request.signal); if (!request.signal.aborted) setOriginal({ key, url }); else URL.revokeObjectURL(url); }
          catch { if (!request.signal.aborted) setPreview({ key, error: "Could not load source. Retry." }); }
        }}>{t("Open original")}</button>}
      </>}
    </div>}
  </div>;
}
