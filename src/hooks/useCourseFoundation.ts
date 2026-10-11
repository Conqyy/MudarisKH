"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { apiJson } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import type { CourseFoundation } from "@/lib/course-foundation";

const API_URL = process.env.NEXT_PUBLIC_BACKEND_URL || "http://127.0.0.1:8000";
const STATES = ["missing", "processing", "failed", "confirmation_required", "ready"];

function checkedFoundation(data: CourseFoundation): CourseFoundation {
  if (!data || !STATES.includes(data.state) || typeof data.ready !== "boolean" || typeof data.revision !== "string") {
    throw new Error("Could not check your lecture documents. Please retry.");
  }
  return { ...data, ready: data.ready && data.state === "ready" };
}

export function useCourseFoundation(courseId: string) {
  const { user, loading: authLoading } = useAuth();
  const key = `${user?.uid || ""}:${courseId}`;
  const currentKey = useRef(key);
  currentKey.current = key;
  const request = useRef<AbortController | null>(null);
  const polls = useRef(0);
  const [status, setStatus] = useState<{ key: string; foundation: CourseFoundation | null; loading: boolean; error: string | null }>({ key, foundation: null, loading: true, error: null });
  const foundation = status.key === key ? status.foundation : null;
  const loading = authLoading || status.key !== key || status.loading;
  const error = status.key === key ? status.error : null;
  const latest = useRef(foundation);
  latest.current = foundation;

  const run = useCallback(async (revision?: string): Promise<CourseFoundation | null> => {
    if (!user?.uid || !courseId || authLoading) return null;
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    const active = () => !controller.signal.aborted && currentKey.current === key;
    // Background checks retain the last authoritative revision so active work
    // can compare it once the new response arrives. Loading still gates new
    // actions. Confirmation changes readiness and must clear the old status.
    setStatus({ key, foundation: revision === undefined ? latest.current : null, loading: true, error: null });
    const url = `${API_URL}/api/courses/${encodeURIComponent(courseId)}/foundation`;
    try {
      let data = checkedFoundation(await apiJson<CourseFoundation>(revision === undefined ? url : `${url}/confirm`, {
        signal: controller.signal,
        ...(revision === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ revision }) }),
      }));
      if (!active()) return null;
      if (revision !== undefined) {
        data = checkedFoundation(await apiJson<CourseFoundation>(url, { signal: controller.signal }));
        if (!active()) return null;
      }
      setStatus({ key, foundation: data, loading: false, error: null });
      return data;
    } catch (cause) {
      if (!active()) return null;
      const message = cause instanceof Error ? cause.message : "Could not check your lecture documents. Please retry.";
      // A confirmation may lose a race with an upload or a retry in another tab.
      // Read the new revision before offering another confirmation.
      let recovered: CourseFoundation | null = null;
      if (revision !== undefined) {
        try { recovered = checkedFoundation(await apiJson<CourseFoundation>(url, { signal: controller.signal })); }
        catch { /* Keep the recovery action visible if this check also fails. */ }
      }
      if (active()) setStatus({ key, foundation: recovered, loading: false, error: message });
      return null;
    }
  }, [authLoading, courseId, key, user?.uid]);

  const refresh = useCallback(() => { polls.current = 0; return run(); }, [run]);
  const confirm = useCallback(() => {
    const current = latest.current;
    return current?.state === "confirmation_required" && current.revision ? run(current.revision) : Promise.resolve(null);
  }, [run]);

  useEffect(() => {
    polls.current = 0;
    if (!authLoading && user?.uid && courseId) void refresh();
    else setStatus({ key, foundation: null, loading: authLoading, error: null });
    return () => { request.current?.abort(); };
  }, [authLoading, courseId, key, refresh, user?.uid]);

  useEffect(() => {
    const onFocus = () => { polls.current = 0; void refresh(); };
    window.addEventListener("focus", onFocus);
    return () => window.removeEventListener("focus", onFocus);
  }, [refresh]);

  useEffect(() => {
    if (foundation?.state !== "processing" || loading || polls.current >= 120) return;
    const timer = setTimeout(() => { polls.current += 1; void run(); }, 5000);
    return () => clearTimeout(timer);
  }, [foundation, loading, run]);

  return { foundation, loading, error, refresh, confirm };
}
