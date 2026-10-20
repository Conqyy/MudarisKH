"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useAuth } from "@/lib/auth-context";
import { getSupportingReport, getSupportingStatus, MaterialKind, prepareSupportingMaterial, SupportingReportPage, SupportingStatus } from "@/lib/supporting-materials";

const ACTIVE = new Set(["queued", "processing", "preparing", "extracting", "aligning"]);
const POLL_MS = 2500;
const MAX_POLLS = 300;
export function useSupportingAnalysis({ kind, materialId, courseId }: { kind: MaterialKind; materialId: string; courseId: string }) {
  const { user } = useAuth();
  const identity = JSON.stringify([user?.uid, courseId, kind, materialId]);
  const generation = useRef(0);
  const controller = useRef<AbortController | null>(null);
  const [statusState, setStatusState] = useState<{ identity: string; value: SupportingStatus } | null>(null);
  const [reportState, setReportState] = useState<{ identity: string; key: string; value: SupportingReportPage } | null>(null);
  const [errorState, setErrorState] = useState<{ identity: string; value: string } | null>(null);
  const [busy, setBusy] = useState(true);
  const [refresh, setRefresh] = useState(0);
  const status = statusState?.identity === identity ? statusState.value : null;
  const reportKey = JSON.stringify([identity, status?.jobId, status?.sourceRevision, status?.reportRevision]);
  const report = reportState?.identity === identity && reportState.key === reportKey ? reportState.value : null;
  const error = errorState?.identity === identity ? errorState.value : null;

  useEffect(() => {
    const current = ++generation.current;
    controller.current?.abort();
    const request = new AbortController();
    controller.current = request;
    setBusy(true);
    setStatusState(null);
    setReportState(null);
    setErrorState(null);
    if (!user?.uid || !materialId || !courseId) { setBusy(false); return () => request.abort(); }
    let timer: ReturnType<typeof setTimeout> | null = null;
    let polls = 0;
    let loadedKey: string | null = null;
    let lastStatusKey: string | null = null;
    const live = () => !request.signal.aborted && generation.current === current;
    const poll = async () => {
      try {
        const next = await getSupportingStatus(kind, materialId, request.signal, courseId);
        if (!live()) return;
        const nextKey = JSON.stringify([identity, next.jobId, next.sourceRevision, next.reportRevision]);
        if (lastStatusKey !== nextKey) { setReportState(null); loadedKey = null; lastStatusKey = nextKey; }
        setStatusState({ identity, value: next });
        setErrorState(null);
        setBusy(false);
        if (next.reportRevision) {
          const key = JSON.stringify([identity, next.jobId, next.sourceRevision, next.reportRevision]);
          if (loadedKey !== key) {
            try {
              const first = await getSupportingReport(kind, materialId, next.reportRevision, 0, 50, request.signal, courseId);
              if (live()) { loadedKey = key; setReportState({ identity, key, value: first }); }
            } catch (cause) {
              if (live()) setErrorState({ identity, value: (cause as Error).message });
            }
          }
        }
        if (ACTIVE.has(next.status) && ++polls < MAX_POLLS) timer = setTimeout(poll, POLL_MS);
      } catch (cause) {
        if (!live()) return;
        setBusy(false);
        setErrorState({ identity, value: (cause as Error).message });
      }
    };
    void poll();
    return () => { request.abort(); if (timer) clearTimeout(timer); };
  // Report pagination changes do not restart status polling.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [identity, kind, materialId, courseId, user?.uid, refresh]);

  const retry = useCallback(async () => {
    controller.current?.abort();
    const request = new AbortController();
    controller.current = request;
    const current = ++generation.current;
    setBusy(true);
    setErrorState(null);
    try {
      const queued = await prepareSupportingMaterial(kind, materialId, courseId, true, request.signal);
      if (request.signal.aborted || current !== generation.current) return;
      setReportState(null);
      setStatusState({ identity, value: queued });
      setBusy(false);
      setRefresh(value => value + 1);
    } catch (cause) {
      if (!request.signal.aborted && current === generation.current) setErrorState({ identity, value: (cause as Error).message });
    } finally { if (!request.signal.aborted && current === generation.current) setBusy(false); }
  }, [courseId, identity, kind, materialId]);

  const loadMore = useCallback(async () => {
    const current = report;
    const revision = status?.reportRevision;
    if (!current || !revision || current.nextOffset === null || !controller.current || controller.current.signal.aborted) return;
    const request = controller.current;
    const expected = generation.current;
    try {
      const next = await getSupportingReport(kind, materialId, revision, current.nextOffset, 50, request.signal, courseId);
      if (request.signal.aborted || expected !== generation.current) return;
      setReportState(previous => previous?.key === reportKey && previous.value.nextOffset === next.offset ? { identity, key: reportKey, value: { ...previous.value, items: [...previous.value.items, ...next.items], alignments: [...previous.value.alignments, ...next.alignments], sharedContexts: [...previous.value.sharedContexts, ...next.sharedContexts], papers: [...previous.value.papers, ...next.papers], topics: [...previous.value.topics, ...next.topics], nextOffset: next.nextOffset } } : previous);
    } catch (cause) { if (!request.signal.aborted) setErrorState({ identity, value: (cause as Error).message }); }
  }, [courseId, identity, kind, materialId, report, reportKey, status?.reportRevision]);
  return { status, report, loading: busy, error, retry, loadMore };
}
