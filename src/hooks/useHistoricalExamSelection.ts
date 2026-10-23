"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { apiJson } from "@/lib/api";
import { HistoricalExamType } from "@/lib/historical-exam-types";
import { ordered } from "@/lib/ordering";
import { retainSelectedRows, supportingPresentation, SupportingRow } from "@/lib/supporting-materials";

interface HistoricalRow extends SupportingRow { title: string; examType?: HistoricalExamType; analysis?: { totalQuestions?: number; paperCount?: number } }
const API_URL = process.env.NEXT_PUBLIC_BACKEND_URL || "http://127.0.0.1:8000";

/** Category changes invalidate both the visible rows and their selection immediately. */
export function useHistoricalExamSelection(courseId: string, userId?: string, course?: { examOrder?: string[]; titleOverrides?: Record<string, string> } | null) {
  const [category, setCategoryState] = useState<HistoricalExamType>("final");
  const [rows, setRows] = useState<HistoricalRow[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(true);
  const [initialLoading, setInitialLoading] = useState(true);
  const [error, setError] = useState("");
  const request = useRef<AbortController | null>(null);
  const currentCategory = useRef(category);
  const initialized = useRef("");
  const data = useRef({ rows, selected, course });
  data.current = { rows, selected, course };
  const setCategory = (next: HistoricalExamType) => {
    if (next === currentCategory.current) return;
    request.current?.abort();
    currentCategory.current = next;
    initialized.current = "";
    setRows([]);
    setSelected(new Set());
    setLoading(true);
    setError("");
    setCategoryState(next);
  };
  const refresh = useCallback(async () => {
    if (!userId || !data.current.course) return;
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    const startedCategory = currentCategory.current;
    const identity = `${userId}:${courseId}:${startedCategory}`;
    setLoading(true);
    setError("");
    try {
      const result = await apiJson(`${API_URL}/api/historical-exams/${courseId}?exam_type=${startedCategory}`, { signal: controller.signal });
      if (controller.signal.aborted || startedCategory !== currentCategory.current) return;
      const next = ordered<HistoricalRow>((result.historical_exams || []).filter((row: HistoricalRow) => row.examType === startedCategory), data.current.course?.examOrder, data.current.course?.titleOverrides);
      const first = initialized.current !== identity;
      setRows(first ? next : retainSelectedRows(next, data.current.rows, data.current.selected));
      if (first) {
        initialized.current = identity;
        setSelected(new Set(next.filter(row => supportingPresentation(row) === "usable").map(row => row.id)));
      }
    } catch (failure) {
      if (!controller.signal.aborted) setError(failure instanceof Error ? failure.message : "Could not load past exams.");
    } finally {
      if (!controller.signal.aborted && startedCategory === currentCategory.current) {
        setLoading(false);
        setInitialLoading(false);
      }
    }
  }, [courseId, userId]);
  const available = !!course;
  useEffect(() => { void refresh(); return () => request.current?.abort(); }, [refresh, category, available]);
  return { category, setCategory, rows, selected, setSelected, loading, initialLoading, error, refresh };
}
