"use client";

import { useEffect, useState, useRef } from "react";
import { useRouter, useParams } from "next/navigation";
import Link from "next/link";
import SourceCitation, { SourceRef } from "@/components/SourceCitation";
import SupportingCitation from "@/components/SupportingCitation";
import type { SupportingRef } from "@/lib/supporting-materials";
import AppShell from "@/components/AppShell";
import Icon from "@/components/Icon";
import { StudyHeader, StudyBusy, StudySourceStatus } from "@/components/StudyWorkspace";
import { CourseFoundationGate } from "@/components/CourseFoundationGate";
import { useCourseFoundation } from "@/hooks/useCourseFoundation";
import { useAuth } from "@/lib/auth-context";
import { useLang } from "@/lib/i18n";
import {
  getCourse,
  getUserCourses,
  Course,
} from "@/lib/firestore-helpers";
import { ordered } from "@/lib/ordering";

import { apiFetch, apiJson } from "@/lib/api";
import { firstSupportingBlocker, retainSelectedRows, supportingPresentation, SupportingRow } from "@/lib/supporting-materials";
import SupportingSelectionNotice from "@/components/SupportingSelectionNotice";
import HistoricalExamTypeSelect from "@/components/HistoricalExamTypeSelect";
import { useHistoricalExamSelection } from "@/hooks/useHistoricalExamSelection";
import { EXAM_TYPE_LABELS } from "@/lib/historical-exam-types";
const API_URL =
  process.env.NEXT_PUBLIC_BACKEND_URL || "http://127.0.0.1:8000";

interface DocItem {
  sourceRevision?: string;
  unitCount?: number;
  guide?: { sections: { label: string }[] };
  id: string;
  title: string;
  fileType: string;
  status: string;
  uploadedAt: number;
  analysis?: { topics?: string[]; keyConceptCount?: number };
}

interface SavedExam {
  id: string;
  examId: string;
  status: string;
  createdAt: number;
  questionCount: number;
  grade?: { totalScore: number; maxScore: number; percentage: number };
}

interface TutorialItem extends SupportingRow {
  id: string;
  title: string;
  status: string;
  analysis?: { problemCount?: number; problems?: unknown[] };
}

interface AudioItem extends SupportingRow {
  id: string;
  title: string;
  status: string;
  insights?: { examHints?: unknown[] };
}

type PageState = "configure" | "generating" | "done" | "error";

export default function ExamPage() {
  const { user } = useAuth();
  const params = useParams();
  return <ExamPageContent key={JSON.stringify([user?.uid, params.id])} />;
}

function ExamPageContent() {
  const { user, loading } = useAuth();
  const router = useRouter();
  const params = useParams();
  const courseId = params.id as string;
  const { t } = useLang();
  const { foundation, loading: foundationLoading, error: foundationError, refresh: refreshFoundation } = useCourseFoundation(courseId);
  const foundationReady = !foundationLoading && !foundationError && foundation?.ready === true;
  const foundationReadyRef = useRef(foundationReady);
  foundationReadyRef.current = foundationReady;
  const foundationUnknownRef = useRef(foundationLoading || !!foundationError);
  foundationUnknownRef.current = foundationLoading || !!foundationError;

  const [course, setCourse] = useState<Course | null>(null);
  const [allCourses, setAllCourses] = useState<Course[]>([]);
  const [documents, setDocuments] = useState<DocItem[]>([]);
  const historical = useHistoricalExamSelection(courseId, user?.uid, course);
  const { rows: histExams, category: historicalExamType, selected: selectedHist, setSelected: setSelectedHist } = historical;
  const [tutorials, setTutorials] = useState<TutorialItem[]>([]);
  const [audioRecs, setAudioRecs] = useState<AudioItem[]>([]);
  const [savedExams, setSavedExams] = useState<SavedExam[]>([]);
  const [pageLoading, setPageLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const loadRequest = useRef<AbortController | null>(null);
  const loadDataRef = useRef<(() => Promise<void>) | null>(null);
  useEffect(() => () => { loadRequest.current?.abort(); }, [courseId, user?.uid]);

  const [selectedDocs, setSelectedDocs] = useState<Set<string>>(new Set());
  const [selectedTut, setSelectedTut] = useState<Set<string>>(new Set());
  const [selectedAudio, setSelectedAudio] = useState<Set<string>>(new Set());
  const initialSupportingSelection = useRef("");
  const selectionRef = useRef({ hist: selectedHist, tut: selectedTut, audio: selectedAudio });
  selectionRef.current = { hist: selectedHist, tut: selectedTut, audio: selectedAudio };
  const supportingBlocker = firstSupportingBlocker([{ selected: selectedHist, rows: histExams }, { selected: selectedTut, rows: tutorials }, { selected: selectedAudio, rows: audioRecs }]);
  const deselectBlocking = (id: string) => {
    setSelectedHist(previous => new Set([...previous].filter(value => value !== id)));
    setSelectedTut(previous => new Set([...previous].filter(value => value !== id)));
    setSelectedAudio(previous => new Set([...previous].filter(value => value !== id)));
  };
  const [topics, setTopics] = useState("");
  const [preference, setPreference] = useState("");
  const [totalMarks, setTotalMarks] = useState(40);

  const [pageState, setPageState] = useState<PageState>("configure");
  const [texContent, setTexContent] = useState("");
  const [examId, setExamId] = useState("");
  const [examDocId, setExamDocId] = useState("");
  const [questionStructure, setQuestionStructure] = useState<
    { id: string; type: string; sourceRefs?: SourceRef[]; supportingSourceRefs?: SupportingRef[] }[]
  >([]);
  const [sharedSupportingSourceRefs, setSharedSupportingSourceRefs] = useState<SupportingRef[]>([]);
  const [errorMsg, setErrorMsg] = useState("");

  const [intelligence, setIntelligence] = useState<{
    documents: number;
    audio: number;
    historical_exams: number;
    tutorials: number;
  } | null>(null);

  const studyRequest = useRef<AbortController | null>(null);
  const generationRequest = useRef<AbortController | null>(null);
  useEffect(() => () => { studyRequest.current?.abort(); }, [courseId, user?.uid]);

  useEffect(() => {
    if (foundationLoading || foundationError || foundationReady || !generationRequest.current) return;
    generationRequest.current.abort();
    generationRequest.current = null;

    setPageState("configure");
  }, [foundationReady, foundationLoading, foundationError]);

  // PDF preview state for the "done" view
  const [pdfAttempt, setPdfAttempt] = useState(0);
  const [pdfUrl, setPdfUrl] = useState<string | null>(null);
  const [pdfStatus, setPdfStatus] = useState<"loading" | "ready" | "failed">(
    "loading"
  );

  useEffect(() => {
    return () => {

      studyRequest.current?.abort();
    };
  }, []);

  // When an exam is ready, fetch its PDF as a blob so a failed compile shows a
  // clean message instead of dumping the backend's raw JSON error in an iframe.
  useEffect(() => {
    if (pageState !== "done" || !examDocId) return;
    let revoked = false;
    let created = "";
    const controller = new AbortController();
    setPdfStatus("loading");
    setPdfUrl((old) => {
      if (old) URL.revokeObjectURL(old);
      return null;
    });
    (async () => {
      try {
        const res = await apiFetch(`${API_URL}/api/exams/${examDocId}/pdf`, { signal: controller.signal });
        const ct = res.headers.get("content-type") || "";
        if (res.ok && ct.includes("pdf")) {
          const blob = await res.blob();
          if (!revoked) {
            created = URL.createObjectURL(blob);
            setPdfUrl(created);
            setPdfStatus("ready");
          }
        } else if (!revoked) {
          setPdfStatus("failed");
        }
      } catch {
        if (!revoked) setPdfStatus("failed");
      }
    })();
    return () => {
      revoked = true;
      controller.abort();
      if (created) URL.revokeObjectURL(created);
    };
  }, [pageState, examDocId, pdfAttempt]);

  useEffect(() => {
    if (!loading && !user) router.push("/signin");
  }, [user, loading, router]);

  useEffect(() => {
    if (user && courseId) loadDataRef.current?.();
  }, [user, courseId]);

  const loadData = async () => {
    if (!user) return;
    loadRequest.current?.abort();
    const controller = new AbortController();
    loadRequest.current = controller;
    setLoadError("");
    if (course) void historical.refresh();
    setPageLoading(true);
    try {
      const [courseData, allCoursesData] = await Promise.all([
        getCourse(courseId),
        getUserCourses(user.uid),
      ]);
      if (courseData && courseData.userId !== user.uid) {
        router.push("/dashboard");
        return;
      }
      if (controller.signal.aborted) return;
      setCourse(courseData);
      setAllCourses(allCoursesData);

      const [docsRes, examsRes, intRes, tutRes, audioRes] = await Promise.all([
        apiJson(`${API_URL}/api/documents/${courseId}`, { signal: controller.signal }),
        apiJson(`${API_URL}/api/exams/list/${courseId}`, { signal: controller.signal }),
        apiJson(`${API_URL}/api/intelligence/${courseId}`, { signal: controller.signal }),
        apiJson(`${API_URL}/api/tutorials/${courseId}`, { signal: controller.signal }),
        apiJson(`${API_URL}/api/audio/${courseId}`, { signal: controller.signal }),
      ]);
      if (controller.signal.aborted) return;

      const completedDocs = ordered<DocItem>(
        (docsRes.documents || []).filter(
          (d: DocItem) => d.status === "completed"
        ),
        courseData?.documentOrder,
        courseData?.titleOverrides
      );
      setDocuments(completedDocs);
      setSelectedDocs(new Set(completedDocs.map((d: DocItem) => d.id)));

      const completedTut = ordered<TutorialItem>(
        tutRes.tutorials || [],
        courseData?.tutorialOrder,
        courseData?.titleOverrides
      );
      setTutorials(previous => retainSelectedRows(completedTut, previous, selectionRef.current.tut));

      const completedAudio = ordered<AudioItem>(
        audioRes.audio_recordings || [],
        courseData?.audioOrder,
        courseData?.titleOverrides
      );
      setAudioRecs(previous => retainSelectedRows(completedAudio, previous, selectionRef.current.audio));
      if (initialSupportingSelection.current !== `${user.uid}:${courseId}`) {
        initialSupportingSelection.current = `${user.uid}:${courseId}`;
        setSelectedTut(new Set(completedTut.filter(row => supportingPresentation(row) === "usable").map(row => row.id)));
        setSelectedAudio(new Set(completedAudio.filter(row => supportingPresentation(row) === "usable").map(row => row.id)));
      }

      setSavedExams(examsRes.exams || []);
      setIntelligence(intRes.counts || null);
    } catch (error: any) {
      if (!controller.signal.aborted) setLoadError(error.message || "Could not load course data.");
    } finally {
      if (!controller.signal.aborted) setPageLoading(false);
    }
  };

  loadDataRef.current = loadData;
  const toggleHist = (id: string) => {
    setSelectedHist((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const toggleDoc = (id: string) => {
    setSelectedDocs((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const toggleTut = (id: string) => {
    setSelectedTut((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const toggleAudio = (id: string) => {
    setSelectedAudio((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const handleDeleteExam = async (
    e: React.MouseEvent,
    id: string,
    examId: string
  ) => {
    e.preventDefault();
    e.stopPropagation();
    if (!confirm(`Delete exam "${examId}"? This cannot be undone.`)) return;
    try {
      const res = await apiFetch(`${API_URL}/api/exams/${id}`, {
        method: "DELETE",
      });
      if (!res.ok) throw new Error(`Delete failed (${res.status})`);
      setSavedExams((prev) => prev.filter((x) => x.id !== id));
    } catch (err) {
      console.error(err);
      alert("Failed to delete exam.");
    }
  };

  const handleGenerate = async () => {
    if (historical.loading || historical.error) return;
    if (!user || !course || !foundationReadyRef.current || !documents.some((doc) => selectedDocs.has(doc.id))) return;
    if (supportingBlocker) { setErrorMsg(t("Selected material is unavailable. Retry or deselect it.")); return; }
    studyRequest.current?.abort();
    const controller = new AbortController();
    studyRequest.current = controller;
    generationRequest.current = controller;
    setPageState("generating");
    setErrorMsg("");

    const topicsList = topics.split(",").map((topic) => topic.trim()).filter(Boolean);

    try {
      const res = await apiFetch(`${API_URL}/api/exams/generate-enhanced`, {
        method: "POST",
        signal: controller.signal,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          user_id: user.uid,
          course_id: courseId,
          topics: topicsList.length > 0 ? topicsList : [course.title],
          preference: preference.trim() || "Generate based on historical exam format.",
          document_ids: Array.from(selectedDocs),
          historical_exam_ids: histExams.filter(row => selectedHist.has(row.id)).map(row => row.id),
          historical_exam_type: historicalExamType,
          tutorial_ids: Array.from(selectedTut),
          audio_ids: Array.from(selectedAudio),
          total_marks: totalMarks,
          exam_type: EXAM_TYPE_LABELS[historicalExamType],
        }),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => null);
        if (res.status === 409) {
          if (controller.signal.aborted) return;
          const currentFoundation = await refreshFoundation();
          if (currentFoundation?.ready) {

            setErrorMsg(err?.detail || `Backend returned ${res.status}`);
            setPageState("error");
          }
          return;
        }
        throw new Error(err?.detail || `Backend returned ${res.status}`);
      }

      const data = await res.json();
      if (controller.signal.aborted || (!foundationReadyRef.current && !foundationUnknownRef.current)) return;

      // Take the student straight to the exam page (exam on the left, upload
      // your answers on the right). Model answers are built on demand there.
      if (data.doc_id) {
        router.push(`/course/${courseId}/exam/${data.doc_id}`);
        return;
      }

      // Fallback (no doc id): show the inline result.
      setExamId(data.exam_id);
      setExamDocId(data.doc_id || "");
      setTexContent(data.tex_content || "");
      setQuestionStructure(data.question_structure || []);
      setSharedSupportingSourceRefs(data.sharedSupportingSourceRefs || []);
      setPdfStatus("failed");
      setPageState("done");
    } catch (e: any) {
      if (controller.signal.aborted) return;
      console.error("Exam generation failed:", e);

      setErrorMsg(
        e.message ||
          "Could not connect to the backend. Make sure the server is running."
      );
      setPageState("error");
    } finally {
      if (generationRequest.current === controller) generationRequest.current = null;
    }
  };

  if (loadError && !pageLoading) return <AppShell courses={allCourses} course={course} courseId={courseId} activeTab="exam"><main className="workspace-main study-workspace"><div className="ui-panel study-busy" role="alert"><Icon name="alert" size={28} /><p>{loadError}</p><button onClick={() => loadData()} className="ui-button secondary">{t("Retry loading")}</button></div></main></AppShell>;

  if (loading || pageLoading || (course && historical.initialLoading)) {
    return (
      <AppShell courses={allCourses} course={course} courseId={courseId} activeTab="exam"><main className="workspace-main study-workspace"><StudyBusy loading title="Loading…" /></main></AppShell>
    );
  }
  if (!user) return null;
  if (!course) {
    return (
      <AppShell courses={allCourses} course={course} courseId={courseId} activeTab="exam"><main className="workspace-main study-workspace"><div className="ui-panel study-busy">
          <div className="text-center">
            <h1 className="font-sans text-3xl font-medium mb-3">{t("Course not found")}</h1>
            <Link
              href="/dashboard"
              className="inline-block bg-ink text-paper px-6 py-3 rounded-full text-sm font-medium hover:bg-accent transition"
            >
              {t("Back to Dashboard")}
            </Link>
          </div>
        </div></main></AppShell>
    );
  }

  if (!foundationReady && pageState !== "done") {
    return (
      <AppShell courses={allCourses} course={course} courseId={courseId} activeTab="exam"><main className="workspace-main study-workspace">
            <Link href={`/course/${courseId}`} className="inline-block mb-6 text-sm text-ink-soft hover:text-accent transition">
              ← {t("Back to course")}
            </Link>
            <CourseFoundationGate courseId={courseId} foundation={foundation} loading={foundationLoading} error={foundationError} onRetry={refreshFoundation} />
          </main></AppShell>
    );
  }

  const renderConfigure = () => (
    <div className="study-layout">
      <aside className="ui-panel source-panel study-sources space-y-6">
        <div className="study-source-title"><h2 className="section-heading">{t("Sources")}</h2><p className="page-subtitle">{t("Choose the material for this study session.")}</p></div>
      {/* Document selection */}
      <div>
        <h3 className="font-sans text-xl font-medium mb-1 tracking-tight">
          {t("Select lecture documents")}
        </h3>
        <p className="text-sm text-ink-soft mb-4">
          Questions cover <span className="text-ink font-medium">only</span> the
          topics in the documents you select. All selected past papers inform the
          predicted question mix and topic emphasis within that scope.
        </p>

        {documents.length === 0 ? (
          <div className="bg-bg-alt border border-line rounded-2xl p-6 text-center">
            <p className="text-ink-mute text-sm mb-3">
              No analyzed documents yet. Upload lecture PDFs on the course page first.
            </p>
            <Link
              href={`/course/${courseId}`}
              className="text-accent text-sm hover:underline"
            >
              {t("Go to course page to upload")}
            </Link>
          </div>
        ) : (
          <div className="bg-paper border border-line rounded-2xl overflow-hidden">
            {documents.map((doc, idx) => (
              <label
                key={doc.id}
                className={`flex items-center gap-4 px-5 py-4 cursor-pointer hover:bg-bg-alt transition ${
                  idx !== 0 ? "border-t border-line" : ""
                }`}
              >
                <input
                  type="checkbox"
                  checked={selectedDocs.has(doc.id)}
                  onChange={() => toggleDoc(doc.id)}
                  className="w-4 h-4 accent-accent rounded"
                />
                <div className="w-10 h-10 rounded-xl bg-sage/10 flex items-center justify-center text-sage text-xs tabular-nums  flex-shrink-0">
                  {doc.fileType}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="font-medium truncate">{doc.title}</div>
                  <div className="text-xs text-ink-mute tabular-nums">
                    {doc.sourceRevision ? `${doc.unitCount ?? "—"} ${t("source units")} · ${doc.guide?.sections.length ?? "—"} ${t("guide sections")}` : `${doc.analysis?.topics?.length || 0} ${t("topics")}`}
                    {!doc.sourceRevision && doc.analysis?.keyConceptCount
                      ? ` · ${doc.analysis.keyConceptCount} concepts`
                      : ""}
                  </div>
                </div>
              </label>
            ))}
            <div className="px-5 py-3 bg-bg-alt border-t border-line flex items-center justify-between">
              <span className="text-xs text-ink-mute tabular-nums">
                {selectedDocs.size} {t("of")} {documents.length} {t("selected")}
              </span>
              <button
                type="button"
                onClick={() => {
                  if (selectedDocs.size === documents.length) {
                    setSelectedDocs(new Set());
                  } else {
                    setSelectedDocs(new Set(documents.map((d) => d.id)));
                  }
                }}
                className="text-xs text-accent hover:underline"
              >
                {selectedDocs.size === documents.length
                  ? t("Deselect all")
                  : t("Select all")}
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Past exam selection */}
      <div>
        <HistoricalExamTypeSelect value={historicalExamType} onChange={historical.setCategory} />
        {historical.loading && <p role="status" className="text-sm text-ink-soft">{t("Loading past exams…")}</p>}
        {historical.error && <div role="alert" className="text-sm text-accent">{historical.error}<button type="button" onClick={() => void historical.refresh()} className="ml-3 underline">{t("Retry")}</button></div>}
        {!historical.loading && !historical.error && histExams.length === 0 && <p className="text-sm text-ink-soft">{t("No past exams in this category. Classify existing papers on the course page or upload this type.")}</p>}
      </div>
      {histExams.length > 0 && (
        <div>
          <h3 className="font-sans text-xl font-medium mb-1 tracking-tight">
            {t("Base it on past exams")}
          </h3>
          <p className="text-sm text-ink-soft mb-4">
            Predict one exam from recurring patterns across all selected papers.
            Merged PDFs are analyzed as collections of individual exams.
          </p>
          <div className="bg-paper border border-line rounded-2xl overflow-hidden">
            {histExams.map((h, idx) => (
              <label
                key={h.id}
                className={`flex items-center gap-4 px-5 py-4 cursor-pointer hover:bg-bg-alt transition ${
                  idx !== 0 ? "border-t border-line" : ""
                }`}
              >
                <input
                  type="checkbox"
                  checked={selectedHist.has(h.id)}
                  onChange={() => toggleHist(h.id)}
                  className="w-4 h-4 accent-accent rounded"
                />
                <div className="w-10 h-10 rounded-xl bg-accent/10 flex items-center justify-center text-accent flex-shrink-0">
                  <Icon name="exam" size={18} />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="font-medium truncate">{h.title}</div><StudySourceStatus row={h} />
                  <div className="text-xs text-ink-mute tabular-nums">
                    {h.analysis?.paperCount
                      ? `${h.analysis.paperCount} papers · ~${h.analysis.totalQuestions} questions per paper`
                      : h.analysis?.totalQuestions
                      ? `${h.analysis.totalQuestions} questions`
                      : ""}
                  </div>
                </div>
              </label>
            ))}
            <div className="px-5 py-3 bg-bg-alt border-t border-line flex items-center justify-between">
              <span className="text-xs text-ink-mute tabular-nums">
                {selectedHist.size} {t("of")} {histExams.length} {t("selected")}
              </span>
              <button
                type="button"
                onClick={() => {
                  if (selectedHist.size === histExams.length) {
                    setSelectedHist(new Set());
                  } else {
                    setSelectedHist(new Set(histExams.map((h) => h.id)));
                  }
                }}
                className="text-xs text-accent hover:underline"
              >
                {selectedHist.size === histExams.length ? t("Deselect all") : t("Select all")}
              </button>
            </div>
          </div>
        </div>
      )}

      {tutorials.length > 0 && (
        <div>
          <h3 className="font-sans text-xl font-medium mb-1 tracking-tight">
            {t("Include tutorial problems")}
          </h3>
          <p className="text-sm text-ink-soft mb-4">
            The generated exam re-creates the problem ideas from the tutorials you
            select (with different numbers). Tutorials don&apos;t affect marks or
            format — only the kinds of problems.
          </p>
          <div className="bg-paper border border-line rounded-2xl overflow-hidden">
            {tutorials.map((t, idx) => (
              <label
                key={t.id}
                className={`flex items-center gap-4 px-5 py-4 cursor-pointer hover:bg-bg-alt transition ${
                  idx !== 0 ? "border-t border-line" : ""
                }`}
              >
                <input
                  type="checkbox"
                  checked={selectedTut.has(t.id)}
                  onChange={() => toggleTut(t.id)}
                  className="w-4 h-4 rounded"
                  style={{ accentColor: "var(--accent)" }}
                />
                <div
                  className="w-10 h-10 rounded-xl flex items-center justify-center flex-shrink-0"
                  style={{ backgroundColor: "var(--bg-alt)", color: "var(--ink-soft)" }}
                >
                  <Icon name="edit" size={18} />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="font-medium truncate">{t.title}</div><StudySourceStatus row={t} />
                  <div className="text-xs text-ink-mute tabular-nums">
                    {t.analysis?.problems?.length
                      ? `${t.analysis.problems.length} problems`
                      : t.analysis?.problemCount
                      ? `${t.analysis.problemCount} problems`
                      : ""}
                  </div>
                </div>
              </label>
            ))}
            <div className="px-5 py-3 bg-bg-alt border-t border-line flex items-center justify-between">
              <span className="text-xs text-ink-mute tabular-nums">
                {selectedTut.size} {t("of")} {tutorials.length} {t("selected")}
              </span>
              <button
                type="button"
                onClick={() => {
                  if (selectedTut.size === tutorials.length) {
                    setSelectedTut(new Set());
                  } else {
                    setSelectedTut(new Set(tutorials.map((t) => t.id)));
                  }
                }}
                className="text-xs hover:underline"
                style={{ color: "var(--accent)" }}
              >
                {selectedTut.size === tutorials.length ? t("Deselect all") : t("Select all")}
              </button>
            </div>
          </div>
        </div>
      )}

      {audioRecs.length > 0 && (
        <div>
          <h3 className="font-sans text-xl font-medium mb-1 tracking-tight">
            {t("Include lecture recordings")}
          </h3>
          <p className="text-sm text-ink-soft mb-4">
            The professor&apos;s exam hints and key emphasis from the recordings
            you select are used to weight what the exam focuses on.
          </p>
          <div className="bg-paper border border-line rounded-2xl overflow-hidden">
            {audioRecs.map((a, idx) => (
              <label
                key={a.id}
                className={`flex items-center gap-4 px-5 py-4 cursor-pointer hover:bg-bg-alt transition ${
                  idx !== 0 ? "border-t border-line" : ""
                }`}
              >
                <input
                  type="checkbox"
                  checked={selectedAudio.has(a.id)}
                  onChange={() => toggleAudio(a.id)}
                  className="w-4 h-4 rounded"
                  style={{ accentColor: "var(--accent)" }}
                />
                <div
                  className="w-10 h-10 rounded-xl flex items-center justify-center flex-shrink-0"
                  style={{ backgroundColor: "var(--bg-alt)", color: "var(--ink-soft)" }}
                >
                  <Icon name="layers" size={18} />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="font-medium truncate">{a.title}</div><StudySourceStatus row={a} />
                  <div className="text-xs text-ink-mute tabular-nums">
                    {a.insights?.examHints?.length
                      ? `${a.insights.examHints.length} exam hints`
                      : ""}
                  </div>
                </div>
              </label>
            ))}
            <div className="px-5 py-3 bg-bg-alt border-t border-line flex items-center justify-between">
              <span className="text-xs text-ink-mute tabular-nums">
                {selectedAudio.size} {t("of")} {audioRecs.length} {t("selected")}
              </span>
              <button
                type="button"
                onClick={() => {
                  if (selectedAudio.size === audioRecs.length) {
                    setSelectedAudio(new Set());
                  } else {
                    setSelectedAudio(new Set(audioRecs.map((a) => a.id)));
                  }
                }}
                className="text-xs hover:underline"
                style={{ color: "var(--accent)" }}
              >
                {selectedAudio.size === audioRecs.length ? t("Deselect all") : t("Select all")}
              </button>
            </div>
          </div>
        </div>
      )}

      </aside>
      <div className="study-content space-y-6">
      <section className="ui-panel study-options space-y-6">
        <div><h2 className="section-heading">{t("Exam options")}</h2><p className="page-subtitle">{t("Make it fit the way you study.")}</p></div>
      {/* Intelligence summary */}
      {intelligence &&
        (histExams.length > 0 ||
          intelligence.audio > 0 ||
          intelligence.tutorials > 0) && (
          <div className="bg-paper border border-line rounded-2xl p-5">
            <h3 className="font-sans text-lg font-medium tracking-tight mb-2">
              {t("Intelligence Data")}
            </h3>
            <p className="text-xs text-ink-soft mb-3">
              Topics are weighted by how often they appeared (and the marks they earned) in your past exams; rarely-tested topics get less coverage. Tutorials add practice-problem ideas (reused with different numbers) — never marks or format.
            </p>
            <div className="flex flex-wrap gap-3 text-xs tabular-nums">
              {histExams.length > 0 && (
                <span className="bg-accent/10 text-accent px-2.5 py-1 rounded-full">
                  {histExams.length} past exam
                  {histExams.length > 1 ? "s" : ""} (topic weighting)
                </span>
              )}
              {intelligence.audio > 0 && (
                <span className="bg-gold/10 text-gold px-2.5 py-1 rounded-full">
                  {intelligence.audio} audio
                </span>
              )}
              {intelligence.tutorials > 0 && (
                <span
                  className="px-2.5 py-1 rounded-full"
                  style={{ backgroundColor: "var(--bg-alt)", color: "var(--ink-soft)" }}
                >
                  {intelligence.tutorials} tutorial
                  {intelligence.tutorials > 1 ? "s" : ""} (problem ideas)
                </span>
              )}
            </div>
          </div>
        )}

      {/* Total marks / exam type */}
      <div>
        <div className="flex items-center justify-between mb-3">
          <label htmlFor="exam-marks" className="block text-sm font-medium text-ink-soft">
            {t("Exam total marks")}
          </label>
          <div className="flex items-center gap-2">
            {EXAM_TYPE_LABELS[historicalExamType] && (
              <span
                className={`text-xs tabular-nums  px-3 py-1 rounded-full ${
                  EXAM_TYPE_LABELS[historicalExamType] === "Final"
                    ? "bg-accent/10 text-accent"
                    : EXAM_TYPE_LABELS[historicalExamType] === "Midterm"
                    ? "bg-gold/10 text-gold"
                    : "bg-sage/10 text-sage"
                }`}
              >
                {t(EXAM_TYPE_LABELS[historicalExamType])}
              </span>
            )}
            <span className="tabular-nums text-sm bg-bg-alt px-3 py-1.5 rounded-lg min-w-[3.5rem] text-center">
              {totalMarks} pts
            </span>
          </div>
        </div>

        <input
          id="exam-marks"
          type="range"
          min={5}
          max={40}
          step={5}
          value={totalMarks}
          onChange={(e) => setTotalMarks(Number(e.target.value))}
          className="w-full accent-accent"
        />

      </div>

      {/* Topics */}
      <div>
        <label htmlFor="exam-topics" className="block text-sm font-medium text-ink-soft mb-2">
          {t("Topics")}{" "}
          <span className="text-ink-mute font-normal">{t("(optional, comma-separated)")}</span>
        </label>
        <input
          id="exam-topics"
          type="text"
          value={topics}
          onChange={(e) => setTopics(e.target.value)}
          placeholder={`e.g. ${course.title}, Key concepts`}
          className="w-full px-4 py-3 border border-line rounded-xl bg-bg focus:outline-none focus:border-accent transition"
        />
      </div>

      {/* Custom instructions */}
      <div>
        <label htmlFor="exam-instructions" className="block text-sm font-medium text-ink-soft mb-2">
          {t("Custom instructions")}{" "}
          <span className="text-ink-mute font-normal">{t("(optional)")}</span>
        </label>
        <textarea
          id="exam-instructions"
          value={preference}
          onChange={(e) => setPreference(e.target.value)}
          placeholder="e.g. Focus on practical applications, include diagrams..."
          rows={2}
          className="w-full px-4 py-3 border border-line rounded-xl bg-bg focus:outline-none focus:border-accent transition resize-none"
        />
      </div>

      {/* Generate button */}
      <SupportingSelectionNotice blocker={supportingBlocker} onDeselect={deselectBlocking} onRefresh={() => { void loadDataRef.current?.(); }} />
      <button
        onClick={handleGenerate}
        disabled={!foundationReady || historical.loading || !!historical.error || !!supportingBlocker || !documents.some((doc) => selectedDocs.has(doc.id))}
        className="ui-button primary"
      >
        {t("Generate Exam")} <Icon name="arrow-right" size={18} />
      </button>

      <p className="text-xs text-ink-mute text-center tabular-nums">
        Question count and format are predicted from all selected papers and your
        requested marks. Older uploads may need a one-time rescan. Keep this tab open.
      </p>

      </section>

      {/* Previous exams */}
      {savedExams.length > 0 && (
        <div className="study-library" id="study-library">
          <h3 className="font-sans text-xl font-medium mb-4 tracking-tight">
            {t("Saved library")}
          </h3>
          <div className="bg-paper border border-line rounded-2xl overflow-hidden">
            {savedExams.map((exam, idx) => (
              <div
                key={exam.id}
                className={`study-library-row ${
                  idx !== 0 ? "border-t border-line" : ""
                }`}
              >
                <Link className="study-library-open" href={`/course/${courseId}/exam/${exam.id}`}>
                  <div
                    className={`w-10 h-10 rounded-xl flex items-center justify-center text-sm ${
                      exam.status === "graded"
                        ? "bg-sage/10 text-sage"
                        : "bg-accent/10 text-accent"
                    }`}
                  >
                    <Icon name="exam" size={20} />
                  </div>
                  <div>
                    <div className="font-medium tabular-nums text-sm">
                      {exam.examId}
                    </div>
                    <div className="text-xs text-ink-mute tabular-nums mt-0.5">
                      {new Date(exam.createdAt).toLocaleDateString()} ·{" "}
                      {exam.questionCount} questions
                    </div>
                  </div>
                </Link>
                <div className="flex items-center gap-3">
                  {exam.grade ? (
                    <span className="tabular-nums text-sm text-sage font-medium">
                      {exam.grade.percentage}%
                    </span>
                  ) : (
                    <span className="tabular-nums text-xs text-ink-mute">
                      {t("Ready to practice")}
                    </span>
                  )}
                  <button
                    onClick={(e) => handleDeleteExam(e, exam.id, exam.examId)}
                    title="Delete exam"
                    aria-label={t("Delete exam")}
                    className="icon-button danger"
                  >
                    <Icon name="trash" size={16} />
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
      </div>
    </div>
  );

  const renderGenerating = () => <StudyBusy title="Generating your exam…" />;

  const downloadPdf = () => {
    if (!pdfUrl) return;
    const a = document.createElement("a");
    a.href = pdfUrl;
    a.download = `${examId || "exam"}.pdf`;
    a.click();
  };

  const renderDone = () => (
    <div className="space-y-6">
      <SupportingCitation courseId={courseId} sourceRefs={sharedSupportingSourceRefs} />
      {questionStructure.map((question, index) => <div key={question.id || index}><span className="text-sm">{question.id || index + 1}</span><SourceCitation courseId={courseId} sourceRefs={question.sourceRefs} /><SupportingCitation courseId={courseId} sourceRefs={question.supportingSourceRefs} /></div>)}
      <div className="flex flex-wrap items-center gap-3">
        <span className="tabular-nums text-xs text-sage bg-sage/10 px-3 py-1.5 rounded-full">
          {examId} · {questionStructure.length} questions
        </span>

        {pdfStatus === "ready" && pdfUrl && (
          <button
            onClick={downloadPdf}
            className="border border-ink text-ink px-4 py-2 rounded-full text-xs font-medium hover:bg-ink hover:text-paper transition flex items-center gap-1.5"
          >
            ↓ Download PDF
          </button>
        )}

        {examDocId && (
          <Link
            href={`/course/${courseId}/exam/${examDocId}`}
            className="bg-accent text-paper px-4 py-2 rounded-full text-xs font-medium hover:bg-ink transition flex items-center gap-1.5"
          >
            Open exam & model answers →
          </Link>
        )}

        <button
          onClick={() => {
            setPageState("configure");
            setTexContent("");
            setExamId("");
            setExamDocId("");
            setQuestionStructure([]);
            setPdfUrl((old) => {
              if (old) URL.revokeObjectURL(old);
              return null;
            });
            loadData();
          }}
          className="border border-line text-ink-soft px-4 py-2 rounded-full text-xs font-medium hover:bg-bg-alt transition"
        >
          Generate another
        </button>
      </div>

      <div className="bg-paper border border-line rounded-3xl overflow-hidden shadow-soft">
        <div className="bg-bg-alt border-b border-line px-5 py-3 flex items-center gap-3">
          <div
            className={`w-2.5 h-2.5 rounded-full ${
              pdfStatus === "ready"
                ? "bg-sage"
                : pdfStatus === "failed"
                ? "bg-gold"
                : "bg-ink-mute animate-pulse"
            }`}
          />
          <span className="tabular-nums text-xs text-ink-mute">{examId}.pdf</span>
        </div>

        {pdfStatus === "loading" && (
          <div className="flex items-center justify-center py-24 text-ink-mute text-sm tabular-nums">
            Preparing preview…
          </div>
        )}

        {pdfStatus === "ready" && pdfUrl && (
          <iframe
            src={pdfUrl}
            className="w-full border-0"
            style={{ height: "75vh" }}
            title="Generated Exam PDF"
          />
        )}

        {pdfStatus === "failed" && (
          <div className="p-8">
            <div className="bg-gold/10 border border-gold/40 rounded-2xl p-5 mb-6 text-sm text-ink-soft">
              <div className="font-medium text-ink mb-1">
                Your exam is ready, but the PDF preview couldn&apos;t be built.
              </div>
              The generated source is shown below. Retry generation to create a saved exam with a PDF preview.
              {examDocId && <button onClick={() => setPdfAttempt(n => n + 1)} className="mt-3 underline">Retry PDF preview</button>}
            </div>
            <pre className="bg-ink text-paper p-5 rounded-2xl overflow-auto text-xs font-mono leading-relaxed max-h-[55vh]">
              {texContent || "No source available."}
            </pre>
          </div>
        )}
      </div>
    </div>
  );

  const renderError = () => (
    <div className="flex items-center justify-center py-20">
      <div className="ui-panel study-busy max-w-md" role="alert">
        <h2 className="font-sans text-2xl font-medium mb-3 tracking-tight">
          {t("Could not open study material")}
        </h2>
        <p className="text-ink-soft text-sm mb-8">{errorMsg}</p>
        <button
          onClick={() => setPageState("configure")}
          className="bg-ink text-paper px-6 py-3 rounded-full text-sm font-medium hover:bg-accent transition"
        >
          {t("Try again")}
        </button>
      </div>
    </div>
  );

  return (
    <AppShell courses={allCourses} course={course} courseId={courseId} activeTab="exam"><main className="workspace-main study-workspace">
          <StudyHeader title="Practice exams" description="Build a practice exam from your lectures and selected past papers." icon="exam" libraryCount={pageState === "configure" ? savedExams.length : 0} />

          {pageState === "configure" && renderConfigure()}
          {pageState === "generating" && renderGenerating()}
          {pageState === "done" && renderDone()}
          {pageState === "error" && renderError()}
        </main></AppShell>
  );
}
