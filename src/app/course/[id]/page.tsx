"use client";

import { useEffect, useState, useRef } from "react";
import { useRouter, useParams, useSearchParams } from "next/navigation";
import Link from "next/link";
import AppShell from "@/components/AppShell";
import Icon from "@/components/Icon";
import CourseJourney from "@/components/CourseJourney";
import CourseMaterialPanel from "@/components/CourseMaterialPanel";
import { resolveCourseView } from "@/lib/course-navigation";
import EditCourseModal from "@/components/EditCourseModal";
import BookmarkButton from "@/components/BookmarkButton";
import { useAuth } from "@/lib/auth-context";
import { useTrackRecent } from "@/lib/activity";
import {
  getCourse,
  getUserCourses,
  deleteCourse,
  updateCourse,
  Course,
  CourseDocument,
  AudioRecording,
  HistoricalExam,
  Tutorial,
} from "@/lib/firestore-helpers";

const API_URL =
  process.env.NEXT_PUBLIC_BACKEND_URL || "http://127.0.0.1:8000";
import UploadDocumentModal from "@/components/UploadDocumentModal";
import UploadAudioModal from "@/components/UploadAudioModal";
import UploadHistoricalExamModal from "@/components/UploadHistoricalExamModal";
import UploadTutorialModal from "@/components/UploadTutorialModal";
import DocumentViewer from "@/components/DocumentViewer";
import AudioViewer from "@/components/AudioViewer";
import ReorderableList from "@/components/ReorderableList";
import { ordered } from "@/lib/ordering";
import { useLang } from "@/lib/i18n";

import { apiFetch, apiJson } from "@/lib/api";
import { useCourseFoundation } from "@/hooks/useCourseFoundation";
import { CourseFoundationGate } from "@/components/CourseFoundationGate";
import SupportingMaterialAction from "@/components/SupportingMaterialAction";
import { kindForRow } from "@/lib/supporting-materials";
import HistoricalExamTypeSelect from "@/components/HistoricalExamTypeSelect";
import { EXAM_GROUP_LABELS, EXAM_TYPE_LABELS, HISTORICAL_EXAM_TYPES, HistoricalExamType } from "@/lib/historical-exam-types";

// Reorder an array of items to match a list of ids.
function applyOrder<T extends { id: string }>(
  items: T[],
  orderedIds: string[]
): T[] {
  const map = new Map(items.map((it) => [it.id, it]));
  return orderedIds.map((id) => map.get(id)).filter(Boolean) as T[];
}

export default function CoursePage() {
  const { user, loading } = useAuth();
  const router = useRouter();
  const params = useParams();
  const searchParams = useSearchParams();
  const courseId = params.id as string;
  const view = resolveCourseView(searchParams || new URLSearchParams());
  const { t } = useLang();
  const { foundation, loading: foundationLoading, error: foundationError, refresh: refreshFoundation, confirm: confirmFoundation } = useCourseFoundation(courseId);

  const [course, setCourse] = useState<Course | null>(null);
  const [allCourses, setAllCourses] = useState<Course[]>([]);
  const [pageLoading, setPageLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const loadRequest = useRef<AbortController | null>(null);
  const loadDataRef = useRef<(() => Promise<void>) | null>(null);
  useEffect(() => () => { loadRequest.current?.abort(); }, [courseId, user?.uid]);
  const [documents, setDocuments] = useState<CourseDocument[]>([]);
  const [audioRecordings, setAudioRecordings] = useState<AudioRecording[]>([]);
  const [historicalExams, setHistoricalExams] = useState<HistoricalExam[]>([]);
  const [classifying, setClassifying] = useState<string | null>(null);
  const [classificationError, setClassificationError] = useState("");
  const classificationRequest = useRef<AbortController | null>(null);
  useEffect(() => {
    setClassifying(null);
    setClassificationError("");
    return () => classificationRequest.current?.abort();
  }, [courseId, user?.uid]);
  const [tutorials, setTutorials] = useState<Tutorial[]>([]);
  const [examCount, setExamCount] = useState(0);
  const [showEdit, setShowEdit] = useState(false);
  const [showDocUpload, setShowDocUpload] = useState(false);
  const [showAudioUpload, setShowAudioUpload] = useState(false);
  const [showHistExamUpload, setShowHistExamUpload] = useState(false);
  const [historicalExamUploadType, setHistoricalExamUploadType] = useState<HistoricalExamType | undefined>();
  const [showTutorialUpload, setShowTutorialUpload] = useState(false);
  const [viewingDoc, setViewingDoc] = useState<CourseDocument | null>(null);
  const [viewingAudio, setViewingAudio] = useState<AudioRecording | null>(null);
  const [documentChanging, setDocumentChanging] = useState(false);
  const documentPolls = useRef(0);
  const documentMutation = useRef<AbortController | null>(null);
  useEffect(() => {
    setDocumentChanging(false);
    return () => documentMutation.current?.abort();
  }, [courseId, user?.uid]);
  // Returning from a native file chooser rechecks the foundation on focus.
  // Retain confirmation and active upload state until that check actually
  // revokes readiness; only starting new actions waits for the response.
  const foundationConfirmed = foundation?.ready === true && !foundationError && !showDocUpload && !documentChanging;
  const foundationReady = foundationConfirmed && !foundationLoading;
  const stagesComplete = documents.length > 0 && documents.every(doc => doc.preparationStatus === "completed" && doc.guideStatus === "completed" && !foundation?.failedDocumentIds?.includes(doc.id));
  const lockReason = t(foundationLoading ? "Checking your lecture document foundation…" : "Complete and confirm all lecture documents to unlock.");

  useEffect(() => {
    if (!loading && !user) router.push("/signin");
  }, [user, loading, router]);

  useEffect(() => {
    if (user && courseId) loadDataRef.current?.();
  }, [user, courseId]);

  useEffect(() => {
    if (!pageLoading && searchParams?.get("section") === "documents") {
      document.getElementById("documents")?.scrollIntoView?.({ behavior: "auto", block: "start" });
    }
  }, [pageLoading, searchParams]);

  // A document upload may be processing when this page is opened elsewhere.
  // Stop after ten minutes; the foundation panel retains an explicit retry.
  useEffect(() => {
    if (!user?.uid || !documents.some(d => d.status !== "failed" && d.preparationStatus !== "failed" && d.guideStatus !== "failed" && (d.status === "pending" || d.status === "processing" || d.preparationStatus === "pending" || d.preparationStatus === "processing" || d.guideStatus === "pending" || d.guideStatus === "processing"))) { documentPolls.current = 0; return; }
    if (documentPolls.current >= 120) return;
    const controller = new AbortController();
    let inFlight = false;
    const timer = setInterval(async () => {
      if (documentPolls.current >= 120) { clearInterval(timer); return; }
      if (inFlight) return;
      inFlight = true;
      documentPolls.current += 1;
      try {
        const data = await apiJson(`${API_URL}/api/documents/${courseId}`, { signal: controller.signal });
        if (controller.signal.aborted) return;
        setDocuments(ordered(data.documents || [], course?.documentOrder, course?.titleOverrides));
        void refreshFoundation();
      } catch { /* Keep retrying within the polling limit. */ }
      finally { inFlight = false; }
    }, 5000);
    return () => { clearInterval(timer); controller.abort(); };
  }, [courseId, course?.documentOrder, course?.titleOverrides, documents, refreshFoundation, user?.uid]);

  // Poll while any audio recording is still being processed (download →
  // transcribe → analyze can take a while for long videos), so the status
  // badge updates live without a manual refresh.
  useEffect(() => {
    const TERMINAL = ["completed", "failed"];
    const anyProcessing = audioRecordings.some(
      (a) => !TERMINAL.includes(a.status as string)
    );
    if (!anyProcessing) return;
    const t = setInterval(() => {
      apiFetch(`${API_URL}/api/audio/${courseId}`)
        .then((r) => r.json())
        .then((d) => d.audio_recordings || [])
        .then((data) =>
          setAudioRecordings((prev) =>
            ordered(data, course?.audioOrder, course?.titleOverrides)
          )
        )
        .catch(() => {});
    }, 5000);
    return () => clearInterval(t);
  }, [audioRecordings, courseId, course?.audioOrder, course?.titleOverrides]);

  // Record the course as recently opened (for the Recent / Bookmarked pages).
  useTrackRecent(
    course
      ? {
          kind: "course",
          id: course.id,
          title: `${course.code} — ${course.title}`,
          href: `/course/${course.id}`,
          courseCode: course.code,
          courseColor: course.color,
        }
      : null
  );

  // Deep-link support: /course/[id]?doc=ID opens the document viewer directly,
  // /course/[id]?audio=ID opens the audio viewer. Used by Recent / Bookmarked.
  useEffect(() => {
    const docId = searchParams?.get("doc");
    if (docId && documents.length > 0) {
      const d = documents.find((x) => x.id === docId);
      if (d) setViewingDoc(d);
    }
  }, [searchParams, documents]);

  useEffect(() => {
    const audioId = searchParams?.get("audio");
    if (audioId && audioRecordings.length > 0) {
      const a = audioRecordings.find((x) => x.id === audioId);
      if (a) setViewingAudio(a);
    }
  }, [searchParams, audioRecordings]);

  const loadData = async () => {
    if (!user) return;
    loadRequest.current?.abort();
    const controller = new AbortController();
    loadRequest.current = controller;
    setLoadError("");
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
      void refreshFoundation();

      // Fetch from backend API (bypasses Firestore security rules)
      await Promise.all([
        apiJson(`${API_URL}/api/documents/${courseId}`, { signal: controller.signal }).then(d => d.documents || []),
        apiJson(`${API_URL}/api/audio/${courseId}`, { signal: controller.signal }).then(d => d.audio_recordings || []),
        apiJson(`${API_URL}/api/historical-exams/${courseId}`, { signal: controller.signal }).then(d => d.historical_exams || []),
        apiJson(`${API_URL}/api/exams/list/${courseId}`, { signal: controller.signal }).then(d => d.exams || []),
        apiJson(`${API_URL}/api/tutorials/${courseId}`, { signal: controller.signal }).then(d => d.tutorials || []),
      ]).then(([docsData, audioData, histData, examData, tutData]) => {
        if (controller.signal.aborted) return;
        setDocuments(
          ordered(docsData, courseData?.documentOrder, courseData?.titleOverrides)
        );
        setAudioRecordings(
          ordered(audioData, courseData?.audioOrder, courseData?.titleOverrides)
        );
        setHistoricalExams(
          ordered(histData, courseData?.examOrder, courseData?.titleOverrides)
        );
        setExamCount(examData.length);
        setTutorials(
          ordered(tutData, courseData?.tutorialOrder, courseData?.titleOverrides)
        );
      });
    } catch (error: any) {
      if (!controller.signal.aborted) setLoadError(error.message || "Could not load course data.");
    } finally {
      if (!controller.signal.aborted) setPageLoading(false);
    }
  };

  loadDataRef.current = loadData;
  const handleDelete = async () => {
    if (
      !confirm(
        "Delete this course and all its uploaded materials and generated study items? This cannot be undone."
      )
    )
      return;
    try {
      await deleteCourse(courseId);
      router.push("/dashboard");
    } catch (error) {
      console.error(error);
      alert("Failed to delete.");
    }
  };

  const handleDeleteItem = async (
    kind: "documents" | "audio" | "historical-exams" | "tutorials",
    id: string,
    title: string
  ) => {
    if (!confirm(`Delete "${title}"? This cannot be undone.`)) return;
    try {
      const res = await apiFetch(`${API_URL}/api/${kind}/${id}`, {
        method: "DELETE",
      });
      if (!res.ok) throw new Error(`Delete failed (${res.status})`);
      if (kind === "documents") {
        setDocuments((prev) => prev.filter((d) => d.id !== id));
        await refreshFoundation();
      } else if (kind === "audio")
        setAudioRecordings((prev) => prev.filter((a) => a.id !== id));
      else if (kind === "tutorials")
        setTutorials((prev) => prev.filter((t) => t.id !== id));
      else setHistoricalExams((prev) => prev.filter((h) => h.id !== id));
    } catch (error) {
      console.error(error);
      alert("Failed to delete. Make sure the backend is running.");
    }
  };

  // ---- Reorder (drag & drop) ----
  // Order + renames are persisted on the COURSE doc (client-writable), since the
  // materials collections themselves are backend-only.
  const handleReorderDocuments = async (orderedIds: string[]) => {
    try {
      await updateCourse(courseId, { documentOrder: orderedIds }, { documentOrder: course?.documentOrder || [] });
      setDocuments((prev) => applyOrder(prev, orderedIds));
      setCourse((prev) => (prev ? { ...prev, documentOrder: orderedIds } : prev));
    } catch (error) {
      alert(error instanceof Error ? error.message : "Could not save the new order. Please retry.");
    }
  };
  const handleReorderAudio = async (orderedIds: string[]) => {
    try {
      await updateCourse(courseId, { audioOrder: orderedIds }, { audioOrder: course?.audioOrder || [] });
      setAudioRecordings((prev) => applyOrder(prev, orderedIds));
      setCourse((prev) => (prev ? { ...prev, audioOrder: orderedIds } : prev));
    } catch (error) {
      alert(error instanceof Error ? error.message : "Could not save the new order. Please retry.");
    }
  };
  const handleReorderExams = async (orderedIds: string[]) => {
    // A list emits only its category. Replace those slots in the full order.
    const fullOrder = [...new Set([...(course?.examOrder || []), ...historicalExams.map(exam => exam.id)])];
    const groupIds = new Set(orderedIds);
    let index = 0;
    const mergedOrder = fullOrder.map(id => groupIds.has(id) ? orderedIds[index++] : id);
    try {
      await updateCourse(courseId, { examOrder: mergedOrder }, { examOrder: course?.examOrder || [] });
      setHistoricalExams((prev) => applyOrder(prev, mergedOrder));
      setCourse((prev) => (prev ? { ...prev, examOrder: mergedOrder } : prev));
    } catch (error) {
      alert(error instanceof Error ? error.message : "Could not save the new order. Please retry.");
    }
  };
  const handleClassifyExam = async (id: string, examType: HistoricalExamType) => {
    classificationRequest.current?.abort();
    const controller = new AbortController();
    classificationRequest.current = controller;
    setClassifying(id);
    setClassificationError("");
    try {
      await apiJson(`${API_URL}/api/historical-exams/${id}/classify`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ exam_type: examType }), signal: controller.signal });
      if (controller.signal.aborted) return;
      // Reload the authoritative category after assignment, including conflicts.
      await loadDataRef.current?.();
    } catch (error) {
      if (!controller.signal.aborted) setClassificationError(error instanceof Error ? error.message : t("Could not classify past exam."));
    } finally {
      if (!controller.signal.aborted) setClassifying(null);
    }
  };
  const handleReorderTutorials = async (orderedIds: string[]) => {
    try {
      await updateCourse(courseId, { tutorialOrder: orderedIds }, { tutorialOrder: course?.tutorialOrder || [] });
      setTutorials((prev) => applyOrder(prev, orderedIds));
      setCourse((prev) => (prev ? { ...prev, tutorialOrder: orderedIds } : prev));
    } catch (error) {
      alert(error instanceof Error ? error.message : "Could not save the new order. Please retry.");
    }
  };
  // ---- Rename ----
  const renameItem = async (id: string, title: string) => {
    const saved = await updateCourse(courseId, { titleOverrides: { [id]: title } }, {
      titleOverrides: { [id]: course?.titleOverrides?.[id] } as Record<string, string>,
    });
    setCourse((prev) => (prev ? { ...prev, titleOverrides: saved.titleOverrides } : prev));
  };

  const handleRenameDocument = async (id: string, title: string) => {
    await renameItem(id, title);
    setDocuments((prev) =>
      prev.map((d) => (d.id === id ? { ...d, title } : d))
    );
  };

  const handleRenameAudio = async (id: string, title: string) => {
    await renameItem(id, title);
    setAudioRecordings((prev) =>
      prev.map((a) => (a.id === id ? { ...a, title } : a))
    );
  };

  const handleRenameExam = async (id: string, title: string) => {
    await renameItem(id, title);
    setHistoricalExams((prev) =>
      prev.map((h) => (h.id === id ? { ...h, title } : h))
    );
  };

  const handleRenameTutorial = async (id: string, title: string) => {
    await renameItem(id, title);
    setTutorials((prev) =>
      prev.map((t) => (t.id === id ? { ...t, title } : t))
    );
  };

  // Explicit stage retries are accepted jobs; detail/list polling owns completion.
  const handleReanalyzeDocument = async (doc: CourseDocument) => {
    if (documentChanging) return;
    const prepare = !doc.sourceRevision || doc.preparationStatus !== "completed" || (foundation?.failedStages?.[doc.id]?.stage === "upgrade_required" || foundation?.failedStages?.[doc.id]?.stage === "preparation");
    if (!confirm(t(prepare ? "Prepare this document from its original? Both stages must finish before confirmation." : "Retry lightweight analysis? You will need to confirm your documents again."))) return;
    documentMutation.current?.abort();
    const controller = new AbortController();
    documentMutation.current = controller;
    setDocumentChanging(true);
    setDocuments(prev => prev.map(d => d.id === doc.id ? { ...d, status: "processing", preparationStatus: prepare ? "pending" : d.preparationStatus, guideStatus: "pending", preparationError: "", guideError: "", errorMessage: "" } : d));
    try {
      const res = await apiFetch(`${API_URL}/api/documents/${encodeURIComponent(doc.id)}/${prepare ? "prepare" : "reanalyze"}`, { method: "POST", signal: controller.signal });
      const data = await res.json().catch(() => null);
      if (controller.signal.aborted) return;
      if (!res.ok) throw new Error(data?.detail || t("Document retry failed."));
      if (data?.document_id !== doc.id) throw new Error(t("Document is unavailable."));
      const detail = await apiJson(`${API_URL}/api/documents/detail/${encodeURIComponent(doc.id)}`, { signal: controller.signal });
      if (controller.signal.aborted) return;
      if (detail.document?.id !== doc.id || (detail.document.courseId && detail.document.courseId !== courseId)) throw new Error(t("Document is unavailable."));
      setDocuments(prev => prev.map(d => d.id === doc.id ? { ...detail.document, title: d.title } : d));
    } catch (error: any) {
      if (controller.signal.aborted) return;
      // Reload authoritative stage state: a transport failure may follow acceptance.
      void loadDataRef.current?.();
      alert(error.message || t("Document retry failed."));
    } finally {
      if (!controller.signal.aborted) {
        await refreshFoundation();
        if (!controller.signal.aborted) setDocumentChanging(false);
      }
    }
  };

  // ---- Re-analyze a recording / typed note (retry after a failed AI call) ----
  const handleReanalyzeRecording = async (rec: AudioRecording) => {
    if (!foundationReady) return;
    if (
      !confirm(
        `Re-analyze "${rec.title}"? This runs the AI again on the saved text.`
      )
    )
      return;

    setAudioRecordings((prev) =>
      prev.map((r) =>
        r.id === rec.id ? { ...r, status: "analyzing", errorMessage: "" } : r
      )
    );

    try {
      const res = await apiFetch(`${API_URL}/api/audio/${rec.id}/reanalyze`, {
        method: "POST",
      });
      const data = await res.json().catch(() => null);
      if (!res.ok) {
        throw new Error(data?.detail || `Re-analysis failed (${res.status}).`);
      }
      setAudioRecordings((prev) =>
        prev.map((r) =>
          r.id === rec.id
            ? { ...r, status: "completed", insights: data.insights, errorMessage: "" }
            : r
        )
      );
    } catch (e: any) {
      setAudioRecordings((prev) =>
        prev.map((r) =>
          r.id === rec.id
            ? { ...r, status: "failed", errorMessage: e.message || "" }
            : r
        )
      );
      alert(e.message || "Re-analysis failed. Try again in a moment.");
    }
  };

  // True if a completed document has an essentially empty analysis.
  const isEmptyAnalysis = (doc: CourseDocument) => {
    if (doc.status !== "completed") return false;
    if (doc.guide || doc.sourceRevision) return false;
    if (!doc.analysis) return true;
    const a = doc.analysis;
    return (
      (a.topics?.length || 0) === 0 &&
      (a.definitions?.length || 0) === 0 &&
      (a.formulas?.length || 0) === 0 &&
      (a.chapterMapping?.length || 0) === 0
    );
  };

  const openHistoricalExamUpload = (type?: HistoricalExamType) => {
    setHistoricalExamUploadType(type);
    setShowHistExamUpload(true);
  };
  const examUploadAction = (type?: HistoricalExamType, first = false) => <button
    onClick={() => openHistoricalExamUpload(type)} disabled={!foundationReady} aria-describedby="foundation-lock-reason" className="ui-button primary">
    <Icon name={foundationReady ? "plus" : "lock"} size={16} />{t(first ? "Upload your first past exam" : "Upload")}
  </button>;
  const examRows = (exams: HistoricalExam[]) => <ReorderableList<HistoricalExam>
    items={exams} onReorder={handleReorderExams} onRename={handleRenameExam}
    onDelete={exam => handleDeleteItem("historical-exams", exam.id, exam.title)}
    renderIcon={() => <div className="w-10 h-10 rounded-xl bg-accent/10 flex items-center justify-center text-accent"><Icon name="exam" size={22} /></div>}
    renderMeta={exam => <>{new Date(exam.uploadedAt).toLocaleDateString()}{exam.analysis && (exam.analysis.paperCount
      ? ` · ${exam.analysis.paperCount} ${t("papers")} · ~${exam.analysis.totalQuestions} ${t("questions per paper")}`
      : ` · ${exam.analysis.totalQuestions} ${t("questions")}`)}</>}
    renderStatus={exam => <div>
      {!exam.examType && <HistoricalExamTypeSelect value="" label={`${t("Classify")} ${exam.title}`} disabled={!!classifying} onChange={type => void handleClassifyExam(exam.id, type)} />}
      <SupportingMaterialAction kind="historical_exam" materialId={exam.id} courseId={courseId} />
    </div>}
  />;
  const examDetails = (type?: HistoricalExamType) => {
    const exams = type ? historicalExams.filter(exam => exam.examType === type) : historicalExams;
    return <div className="course-material-panel-body">
      {!foundationReady && <p className="mb-4 text-sm text-ink-soft">{lockReason}</p>}
      {exams.length === 0 && <div className="bg-paper border-2 border-dashed border-line rounded-3xl p-10 text-center">
        <div className="text-4xl mb-3 opacity-60"><Icon name="exam" size={22} /></div>
        <h3 className="font-sans text-xl font-medium mb-2">{t("No past exams yet")}</h3>
        <p className="text-ink-soft text-sm mb-5 max-w-md mx-auto">{t("Upload old exam PDFs. The AI will analyze topic weights, question patterns, and difficulty distribution.")}</p>
        {examUploadAction(type, true)}
      </div>}
      {!type && classificationError && <p role="alert" className="text-sm text-accent mb-4">{classificationError}</p>}
      {type ? examRows(exams) : [...HISTORICAL_EXAM_TYPES, "uncategorized" as const].map(group => {
        const rows = historicalExams.filter(exam => group === "uncategorized" ? !exam.examType : exam.examType === group);
        if (group === "uncategorized" && !rows.length) return null;
        const label = group === "uncategorized" ? "Needs classification" : EXAM_GROUP_LABELS[group];
        return <section key={group} aria-label={t(label)} className="mb-6">
          <h3 className="font-sans text-xl font-medium mb-3">{t(label)} <span className="font-sans text-sm text-ink-mute">{rows.length}</span></h3>
          {group === "uncategorized" && <p className="text-sm text-ink-soft mb-3">{t("Assign a type before using these papers for exams or summaries.")}</p>}
          {examRows(rows)}
        </section>;
      })}
    </div>;
  };

  if (loadError && !pageLoading) return <AppShell courses={allCourses}><main className="workspace-main"><div role="alert" className="ui-notice danger mt-8"><Icon name="alert" /><div><p>{loadError}</p><button onClick={() => void loadData()} className="ui-button secondary mt-3">{t("Retry loading")}</button></div></div></main></AppShell>;
  if (loading || pageLoading) return <AppShell courses={allCourses}><main className="workspace-main"><div className="course-loading"><Icon name="loader" className="animate-spin" /><p>{t("Loading…")}</p></div></main></AppShell>;
  if (!user) return null;
  if (!course) return <AppShell courses={allCourses}><main className="workspace-main"><div className="dashboard-empty ui-panel mt-8"><Icon name="search" size={30} /><h1>{t("Course not found")}</h1><p>{t("This course may have been deleted or doesn't exist.")}</p><Link href="/dashboard" className="ui-button primary">{t("Back to Dashboard")}</Link></div></main></AppShell>;

  return (<>
    <AppShell courses={allCourses} course={course} courseId={courseId} activeTab={view}>
      <main className="workspace-main course-page">
        <header className="page-header">
          <div><div className="course-page-code"><span className="course-color-dot" style={{ background: course.color }} />{course.code}</div><h1 className="page-heading">{course.title}</h1>{course.instructor && <p className="page-subtitle flex items-center gap-2"><Icon name="user" size={15} />{course.instructor}</p>}</div>
          <div className="flex flex-wrap items-center gap-2">
            <BookmarkButton item={{ kind: "course", id: course.id, title: course.code + " — " + course.title, href: "/course/" + course.id, courseCode: course.code, courseColor: course.color }} />
            <button className="ui-button secondary" onClick={() => setShowEdit(true)}><Icon name="edit" size={15} />{t("Edit")}</button>
            <button className="icon-button danger" aria-label={t("Delete")} title={t("Delete course")} onClick={handleDelete}><Icon name="trash" size={17} /></button>
          </div>
        </header>
        {view === "overview" && <CourseJourney courseId={courseId} foundation={foundation} loading={foundationLoading} error={foundationError} ready={foundationReady} confirmed={foundationConfirmed}
          onRetry={refreshFoundation} onUpload={() => setShowDocUpload(true)} onConfirm={confirmFoundation} canConfirm={stagesComplete}
          showConfirmation={foundation?.state === "confirmation_required" && !foundationLoading && !documentChanging && !showDocUpload}
          supportCount={historicalExams.length + tutorials.length + audioRecordings.length} />}
        {!foundationReady && <p id="foundation-lock-reason" className="text-sm text-ink-soft mb-4">{lockReason}</p>}
        <div className={view === "overview" ? "course-materials course-materials-overview" : "course-materials"}>
          {view === "materials" && <>
            <div className="section-heading"><div><h2>{t("Course materials")}</h2><p className="page-subtitle">{t("Your lecture foundation and supporting sources, in one place.")}</p></div><Link href={"/course/" + courseId} className="ui-button ghost">{t("Back to overview")}<Icon name="arrow-right" size={15} /></Link></div>
            <CourseFoundationGate courseId={courseId} foundation={foundation} loading={foundationLoading} error={foundationError} onRetry={refreshFoundation} />
            <nav className="materials-groups" aria-label={t("Material groups")}><a href="#documents"><Icon name="file" size={17} />{t("Documents")}<span>{documents.length}</span></a><a href="#past-exams"><Icon name="exam" size={17} />{t("Past Exams")}<span>{historicalExams.length}</span></a><a href="#tutorials"><Icon name="book" size={17} />{t("Tutorials")}<span>{tutorials.length}</span></a><a href="#recordings"><Icon name="audio" size={17} />{t("Audio Recordings")}<span>{audioRecordings.length}</span></a></nav>
          </>}
          {/* Documents Section */}
          <CourseMaterialPanel id="documents" title={t("Documents")} icon="file" count={documents.length}
            summary={t("Lecture documents and source guides")} overview={view === "overview"} holdOpen={showDocUpload || !!viewingDoc}
            actions={<button
                onClick={() => setShowDocUpload(true)}
                className="ui-button primary"
              >
                <span>+</span> {t("Upload")}
              </button>}>

            <div className="course-material-panel-body">
            {documents.length === 0 ? (
              <div className="bg-paper border-2 border-dashed border-line rounded-3xl p-10 text-center">
                <div className="text-4xl mb-3 opacity-60">{<Icon name="file" size={22} />}</div>
                <h3 className="font-sans text-xl font-medium mb-2">
                  {t("No documents yet")}
                </h3>
                <p className="text-ink-soft text-sm mb-5 max-w-md mx-auto">
                  {t("Upload lecture PDFs, slides, or Word docs. The AI will extract topics, definitions, and formulas.")}
                </p>
                <button
                  onClick={() => setShowDocUpload(true)}
                  className="ui-button primary"
                >
                  + {t("Upload your first document")}
                </button>
              </div>
            ) : (
              <ReorderableList<CourseDocument>
                items={documents}
                onReorder={handleReorderDocuments}
                onRename={handleRenameDocument}
                onItemClick={(doc) => setViewingDoc(doc)}
                canClick={() => true}
                onDelete={(doc) =>
                  handleDeleteItem("documents", doc.id, doc.title)
                }
                renderIcon={(doc) => (
                  <div className="w-10 h-10 rounded-xl bg-sage/10 flex items-center justify-center text-sage text-sm font-sans uppercase">
                    {doc.fileType}
                  </div>
                )}
                renderMeta={(doc) => (
                  <>
                    {new Date(doc.uploadedAt).toLocaleDateString()}
                    {doc.sourceRevision ? ` · ${doc.unitCount ?? "—"} ${t("source units")} · ${doc.guide?.sections.length ?? "—"} ${t("guide sections")}` : doc.analysis && ` · ${doc.analysis.topics?.length || 0} ${t("topics")}` }
                  </>
                )}
                renderStatus={(doc) => {
                  const empty = isEmptyAnalysis(doc);
                  const rejected = foundation?.failedDocumentIds?.includes(doc.id) === true;
                  const failure = foundation?.failedStages?.[doc.id];
                  const legacy = !doc.sourceRevision && doc.status === "completed";
                  const stageFailure = doc.preparationStatus === "failed" || doc.guideStatus === "failed";
                  const pending = !stageFailure && doc.status !== "failed" && (doc.preparationStatus === "pending" || doc.preparationStatus === "processing" || doc.guideStatus === "pending" || doc.guideStatus === "processing" || doc.status === "processing" || doc.status === "pending");
                  const needsRetry = doc.status === "failed" || stageFailure || empty || rejected || legacy;
                  const label = pending ? doc.preparationStatus === "completed" ? "Creating lightweight analysis" : "Preparing document" : legacy || failure?.stage === "upgrade_required" ? "Preparation required" : needsRetry ? "Failed" : "Analyzed";
                  const retryLabel = legacy || failure?.stage === "upgrade_required" ? "Prepare document" : doc.preparationStatus === "failed" || failure?.stage === "preparation" ? "Retry preparation" : doc.guideStatus === "failed" || failure?.stage === "guide" ? "Retry lightweight analysis" : "retry";
                  return <span className="inline-flex flex-wrap items-center gap-2">
                    <span className={needsRetry ? "text-accent" : pending ? "text-gold" : "text-sage"}>● {t(label)}</span>
                    {(failure?.error || doc.preparationError || doc.guideError || doc.errorMessage) && <span className="text-xs text-accent">{failure?.error || doc.preparationError || doc.guideError || doc.errorMessage}</span>}
                    {needsRetry && !pending && <button disabled={documentChanging} onClick={e => { e.stopPropagation(); void handleReanalyzeDocument(doc); }} className="text-[10px] underline text-accent hover:text-ink disabled:opacity-50">{t(retryLabel)}</button>}
                  </span>;
                }}
              />
            )}
            </div>
          </CourseMaterialPanel>

          {/* Historical Exams Section */}
          {view === "overview" ? <section id="past-exams" className="course-exam-panels" aria-label={t("Past Exams")}>
            <h2 className="sr-only">{t("Past Exams")}</h2>
            {(["final", "midterm", "quiz"] as const).map(type => <CourseMaterialPanel key={type} mini
              id={`past-exams-${type}`} title={t(EXAM_TYPE_LABELS[type])} icon="exam"
              count={historicalExams.filter(exam => exam.examType === type).length} summary={t("Past Exams")} overview
              holdOpen={showHistExamUpload && historicalExamUploadType === type} actions={examUploadAction(type)}>
              {examDetails(type)}
            </CourseMaterialPanel>)}
            {historicalExams.some(exam => !exam.examType) && <Link className="course-exam-mini-notice" href={`/course/${courseId}?view=materials#past-exams`}>
              <Icon name="alert" size={15} />{t("Needs classification")} ({historicalExams.filter(exam => !exam.examType).length})<Icon name="arrow-right" size={15} />
            </Link>}
          </section> : <CourseMaterialPanel id="past-exams" title={t("Past Exams")} icon="exam" count={historicalExams.length}
            summary={t("Previous quizzes, midterms and finals")} overview={false} actions={examUploadAction()}>
            {examDetails()}
          </CourseMaterialPanel>}

          {/* Tutorials Section */}
          <CourseMaterialPanel id="tutorials" title={t("Tutorials")} icon="book" count={tutorials.length}
            summary={t("Practice sheets and worked problems")} overview={view === "overview"} holdOpen={showTutorialUpload}
            description={t("Practice problems. The exam generator reuses their ideas (with different numbers) — no marks or format weighting.")}
            actions={<button
                onClick={() => setShowTutorialUpload(true)}
                disabled={!foundationReady} aria-describedby="foundation-lock-reason"
                className="ui-button primary"
              >
                <span aria-hidden="true">{<Icon name={foundationReady ? "plus" : "lock"} size={16} />}</span> {t("Upload")}
              </button>}>

            <div className="course-material-panel-body">
            {!foundationReady && <p className="mb-4 text-sm text-ink-soft">{lockReason}</p>}

            {tutorials.length === 0 ? (
              <div className="bg-paper border-2 border-dashed border-line rounded-3xl p-10 text-center">
                <div className="text-4xl mb-3 opacity-60">{<Icon name="book" size={22} />}</div>
                <h3 className="font-sans text-xl font-medium mb-2">
                  {t("No tutorials yet")}
                </h3>
                <p className="text-ink-soft text-sm mb-5 max-w-md mx-auto">
                  {t("Upload tutorial / exercise sheets. The AI learns how topics are applied so generated exams mirror those problem ideas.")}
                </p>
                <button
                  onClick={() => setShowTutorialUpload(true)}
                  disabled={!foundationReady} aria-describedby="foundation-lock-reason"
                  className="ui-button primary"
                >
                  <span aria-hidden="true">{<Icon name={foundationReady ? "plus" : "lock"} size={16} />}</span> {t("Upload your first tutorial")}
                </button>
              </div>
            ) : (
              <ReorderableList<Tutorial>
                items={tutorials}
                onReorder={handleReorderTutorials}
                onRename={handleRenameTutorial}
                onDelete={(tut) =>
                  handleDeleteItem("tutorials", tut.id, tut.title)
                }
                renderIcon={() => (
                  <div className="w-10 h-10 rounded-xl bg-accent/10 flex items-center justify-center text-accent">
                    {<Icon name="book" size={22} />}
                  </div>
                )}
                renderMeta={(tut) => (
                  <>
                    {new Date(tut.uploadedAt).toLocaleDateString()}
                    {tut.analysis?.problems?.length
                      ? ` · ${tut.analysis.problems.length} ${t("problems")}`
                      : ""}
                  </>
                )}
                renderStatus={(tut) => <SupportingMaterialAction kind="tutorial" materialId={tut.id} courseId={courseId} />}
              />
            )}
            </div>
          </CourseMaterialPanel>

          {/* Audio Recordings Section */}
          <CourseMaterialPanel id="recordings" title={t("Audio Recordings")} icon="audio" count={audioRecordings.length}
            summary={t("Lecture recordings and typed notes")} overview={view === "overview"} holdOpen={showAudioUpload || !!viewingAudio}
            actions={<button
                onClick={() => setShowAudioUpload(true)}
                disabled={!foundationReady} aria-describedby="foundation-lock-reason"
                className="ui-button primary"
              >
                <span aria-hidden="true">{<Icon name={foundationReady ? "plus" : "lock"} size={16} />}</span> {t("Upload")}
              </button>}>

            <div className="course-material-panel-body">
            {!foundationReady && <p className="mb-4 text-sm text-ink-soft">{lockReason}</p>}

            {audioRecordings.length === 0 ? (
              <div className="bg-paper border-2 border-dashed border-line rounded-3xl p-10 text-center">
                <div className="text-4xl mb-3 opacity-60">{<Icon name="audio" size={22} />}</div>
                <h3 className="font-sans text-xl font-medium mb-2">
                  {t("No recordings yet")}
                </h3>
                <p className="text-ink-soft text-sm mb-5 max-w-md mx-auto">
                  {t("Upload professor lecture recordings. The AI will transcribe them and extract exam hints.")}
                </p>
                <button
                  onClick={() => setShowAudioUpload(true)}
                  disabled={!foundationReady} aria-describedby="foundation-lock-reason"
                  className="ui-button primary"
                >
                  <span aria-hidden="true">{<Icon name={foundationReady ? "plus" : "lock"} size={16} />}</span> {t("Upload your first recording")}
                </button>
              </div>
            ) : (
              <ReorderableList<AudioRecording>
                items={audioRecordings}
                onReorder={handleReorderAudio}
                onRename={handleRenameAudio}
                onItemClick={(rec) => setViewingAudio(rec)}
                canClick={(rec) => rec.status === "completed" || rec.legacy === true}
                onDelete={(rec) => handleDeleteItem("audio", rec.id, rec.title)}
                renderIcon={() => (
                  <div className="w-10 h-10 rounded-xl bg-gold/10 flex items-center justify-center text-gold">
                    {<Icon name="audio" size={22} />}
                  </div>
                )}
                renderMeta={(rec) => (
                  <>
                    {new Date(rec.uploadedAt).toLocaleDateString()}
                    {rec.insights?.examHints &&
                      ` · ${rec.insights.examHints.length} ${t("exam hints")}`}
                  </>
                )}
                renderStatus={(rec) => <SupportingMaterialAction kind={kindForRow(rec, "audio")} materialId={rec.id} courseId={courseId} />}
              />
            )}
            </div>
          </CourseMaterialPanel>


        </div>
      </main>
    </AppShell>

      {showEdit && (
        <EditCourseModal
          course={course}
          onClose={() => setShowEdit(false)}
          onSuccess={loadData}
        />
      )}

      {showDocUpload && (
        <UploadDocumentModal
          courseId={course.id}
          onClose={() => { setShowDocUpload(false); void loadData(); }}
          onSuccess={refreshFoundation}
        />
      )}

      {showAudioUpload && foundationConfirmed && (
        <UploadAudioModal
          courseId={course.id}
          onClose={() => setShowAudioUpload(false)}
          onSuccess={loadData}
        />
      )}

      {showHistExamUpload && foundationConfirmed && (
        <UploadHistoricalExamModal
          courseId={course.id}
          initialExamType={historicalExamUploadType}
          onClose={() => setShowHistExamUpload(false)}
          onSuccess={loadData}
        />
      )}

      {showTutorialUpload && foundationConfirmed && (
        <UploadTutorialModal
          courseId={course.id}
          onClose={() => setShowTutorialUpload(false)}
          onSuccess={loadData}
        />
      )}

      {viewingDoc && (
        <DocumentViewer
          document={viewingDoc}
          onClose={() => setViewingDoc(null)}
          courseCode={course.code}
          courseColor={course.color}
        />
      )}

      {viewingAudio && (
        <AudioViewer
          recording={viewingAudio}
          onClose={() => setViewingAudio(null)}
          courseCode={course.code}
          courseColor={course.color}
        />
      )}
    </>
  );
}
