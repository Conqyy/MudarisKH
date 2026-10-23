"use client";

import { useEffect, useState, useRef } from "react";
import { useRouter, useParams, useSearchParams } from "next/navigation";
import Link from "next/link";
import Navbar from "@/components/Navbar";
import Sidebar from "@/components/Sidebar";
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
import CourseReminders from "@/components/CourseReminders";
import { CourseReminder } from "@/lib/firestore-helpers";
import { ordered } from "@/lib/ordering";
import { useLang } from "@/lib/i18n";

import { apiFetch, apiJson } from "@/lib/api";
import { useCourseFoundation } from "@/hooks/useCourseFoundation";
import { CourseFoundationGate } from "@/components/CourseFoundationGate";
import SupportingMaterialAction from "@/components/SupportingMaterialAction";
import { kindForRow } from "@/lib/supporting-materials";
import HistoricalExamTypeSelect from "@/components/HistoricalExamTypeSelect";
import { EXAM_GROUP_LABELS, HISTORICAL_EXAM_TYPES, HistoricalExamType } from "@/lib/historical-exam-types";

function StudyAction({ ready, href, label, className, reason }: { ready: boolean; href: string; label: string; className: string; reason: string }) {
  return ready ? <Link href={href} className={className}>{label} →</Link> : (
    <div>
      <p className="mb-3 text-xs text-ink-soft">{reason}</p>
      <button disabled aria-describedby="foundation-lock-reason" className={`${className} w-full opacity-50 cursor-not-allowed`}><span aria-hidden="true">🔒</span> {label}</button>
    </div>
  );
}
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
  const foundationReady = foundation?.ready === true && !foundationLoading && !foundationError && !showDocUpload && !documentChanging;
  const stagesComplete = documents.length > 0 && documents.every(doc => doc.preparationStatus === "completed" && doc.guideStatus === "completed" && !foundation?.failedDocumentIds?.includes(doc.id));
  const lockReason = t("Complete and confirm all lecture documents to unlock.");

  useEffect(() => {
    if (!loading && !user) router.push("/signin");
  }, [user, loading, router]);

  useEffect(() => {
    if (user && courseId) loadDataRef.current?.();
  }, [user, courseId]);

  useEffect(() => {
    if (!pageLoading && searchParams?.get("section") === "documents") {
      document.getElementById("documents")?.scrollIntoView?.({ behavior: "smooth", block: "start" });
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

  // ---- Reminders (stored on the course doc) ----
  const handleRemindersChange = async (reminders: CourseReminder[]) => {
    try {
      const saved = await updateCourse(courseId, { reminders }, { reminders: course?.reminders || [] });
      setCourse((prev) => (prev ? { ...prev, reminders: saved.reminders } : prev));
    } catch (error) {
      alert("Could not save reminders. Please retry.");
      throw error;
    }
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

  if (loadError && !pageLoading) return <><Navbar /><div className="pt-28 px-6 text-center" role="alert"><p>{loadError}</p><button onClick={() => loadData()} className="mt-4 underline">Retry loading</button></div></>;

  if (loading || pageLoading) {
    return (
      <>
        <Navbar />
        <div className="pt-20 min-h-screen flex items-center justify-center">
          <div className="font-mono text-sm text-ink-mute">Loading…</div>
        </div>
      </>
    );
  }

  if (!user) return null;

  if (!course) {
    return (
      <>
        <Navbar />
        <div className="pt-20 min-h-screen flex items-center justify-center">
          <div className="text-center max-w-md px-6">
            <div className="text-6xl mb-6">🔍</div>
            <h1 className="font-serif text-3xl font-medium mb-3">
              Course not found
            </h1>
            <p className="text-ink-soft mb-8">
              This course may have been deleted or doesn&apos;t exist.
            </p>
            <Link
              href="/dashboard"
              className="inline-block bg-ink text-paper px-6 py-3 rounded-full text-sm font-medium hover:bg-accent transition"
            >
              ← Back to Dashboard
            </Link>
          </div>
        </div>
      </>
    );
  }

  const completedDocs = documents.filter((d) => d.status === "completed").length;
  const completedHist = historicalExams.filter((h) => h.status === "completed").length;
  const examReady = foundationReady && completedDocs > 0 && completedHist > 0;

  return (
    <>
      <Navbar />

      <div className="pt-20 flex">
        <Sidebar courses={allCourses} />

        <main className="flex-1 px-6 md:px-10 lg:px-12 pb-20 max-w-7xl mx-auto w-full">
          {/* Breadcrumb */}
          <div className="my-8">
            <Link
              href="/dashboard"
              className="text-xs font-mono text-ink-soft hover:text-accent transition"
            >
              ← Dashboard
            </Link>
          </div>

          {/* Course Header */}
          <div
            className="bg-paper border border-line rounded-3xl p-8 md:p-10 mb-10 relative overflow-hidden"
            style={{ borderTop: `6px solid ${course.color}` }}
          >
            <div className="absolute top-6 right-6 flex gap-2 items-center">
              <BookmarkButton
                item={{
                  kind: "course",
                  id: course.id,
                  title: `${course.code} — ${course.title}`,
                  href: `/course/${course.id}`,
                  courseCode: course.code,
                  courseColor: course.color,
                }}
                size="sm"
              />
              <button
                onClick={() => setShowEdit(true)}
                className="px-4 py-2 border border-line rounded-full text-xs font-medium hover:bg-bg-alt transition"
              >
                ✎ Edit
              </button>
              <button
                onClick={handleDelete}
                className="px-4 py-2 border border-line rounded-full text-xs font-medium text-ink-mute hover:bg-accent hover:text-paper hover:border-accent transition"
              >
                Delete
              </button>
            </div>

            <div className="font-mono text-xs text-ink-mute uppercase tracking-widest mb-3">
              {course.code}
            </div>
            <h1 className="font-serif text-3xl md:text-5xl font-medium tracking-tight leading-tight mb-3 pr-32">
              {course.title}
            </h1>
            <div className="flex flex-wrap gap-x-6 gap-y-2 text-ink-soft text-sm">
              <span className="flex items-center gap-2">
                <span className="opacity-60">👤</span>
                {course.instructor}
              </span>
            </div>
          </div>


          <CourseFoundationGate courseId={courseId} foundation={foundation} loading={foundationLoading} error={foundationError} onRetry={refreshFoundation} />
          {!foundationReady && <p id="foundation-lock-reason" className="mb-6 text-sm text-ink-soft">{lockReason}</p>}
          {foundation?.state === "confirmation_required" && !foundationLoading && !documentChanging && !showDocUpload && (
            <div className="mb-8 bg-paper border border-sage/30 rounded-2xl p-6">
              <p className="text-sm text-ink-soft mb-4">{t("Upload every lecture document you intend to study before confirming. Adding, deleting, or reanalyzing a document will require confirmation again.")}</p>
              <button disabled={!stagesComplete} onClick={() => { if (stagesComplete) void confirmFoundation(); }} className="disabled:opacity-50 disabled:cursor-not-allowed bg-sage text-paper px-5 py-3 rounded-full text-sm font-medium hover:bg-ink transition">{t("I've uploaded all lecture documents")}</button>
            </div>
          )}

          {/* Exam readiness bar */}
          {foundationReady && <div className="mb-12 bg-paper border border-line rounded-2xl px-6 py-4 flex items-center justify-between gap-4">
            <div className="flex items-center gap-3">
              <span
                className={`w-2.5 h-2.5 rounded-full ${
                  examReady ? "bg-sage" : "bg-gold"
                }`}
              />
              <span className="text-sm text-ink-soft">
                {examReady ? (
                  <>{t("This course is")} <span className="text-sage font-medium">{t("exam-ready")}</span> {t("— documents and past exams analyzed.")}</>
                ) : completedDocs === 0 ? (
                  t("Upload lecture documents to start building practice exams.")
                ) : completedHist === 0 ? (
                  t("Add a past exam so generated exams match its format.")
                ) : (
                  t("Ready to generate practice exams.")
                )}
              </span>
            </div>
          </div>}

          {/* Reminders */}
          <CourseReminders
            reminders={course.reminders || []}
            onChange={handleRemindersChange}
          />

          {/* Intelligence Summary */}
          {(documents.some(d => d.status === "completed") ||
            audioRecordings.some(a => a.status === "completed") ||
            historicalExams.some(h => h.status === "completed") ||
            tutorials.some(t => t.status === "completed")) && (
            <section className="mb-12">
              <div className="bg-paper border border-line rounded-3xl p-7">
                <h2 className="font-serif text-2xl font-medium tracking-tight mb-4">
                  {t("Intelligence Summary")}
                </h2>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                  <div className="bg-bg rounded-2xl p-4 text-center">
                    <div className="font-serif text-2xl font-medium text-sage">
                      {documents.filter(d => d.status === "completed").length}
                    </div>
                    <div className="text-xs text-ink-mute font-mono mt-1">{t("Documents")}</div>
                  </div>
                  <div className="bg-bg rounded-2xl p-4 text-center">
                    <div className="font-serif text-2xl font-medium text-accent">
                      {historicalExams.filter(h => h.status === "completed").length}
                    </div>
                    <div className="text-xs text-ink-mute font-mono mt-1">{t("Past Exams")}</div>
                  </div>
                  <div className="bg-bg rounded-2xl p-4 text-center">
                    <div className="font-serif text-2xl font-medium text-[#3f6f7d]">
                      {tutorials.filter(t => t.status === "completed").length}
                    </div>
                    <div className="text-xs text-ink-mute font-mono mt-1">{t("Tutorials")}</div>
                  </div>
                  <div className="bg-bg rounded-2xl p-4 text-center">
                    <div className="font-serif text-2xl font-medium text-gold">
                      {audioRecordings.filter(a => a.status === "completed").length}
                    </div>
                    <div className="text-xs text-ink-mute font-mono mt-1">{t("Audio")}</div>
                  </div>
                </div>

                {historicalExams.some(h => h.status === "completed" && h.analysis?.topicWeights?.length) && (
                  <div className="mt-4 pt-4 border-t border-line">
                    <div className="text-xs font-mono text-ink-mute uppercase tracking-widest mb-2">{t("Top Exam Topics")}</div>
                    <div className="flex flex-wrap gap-2">
                      {historicalExams
                        .filter(h => h.status === "completed" && h.analysis?.topicWeights)
                        .flatMap(h => h.analysis!.topicWeights.slice(0, 5))
                        .slice(0, 8)
                        .map((tw, i) => (
                          <span key={i} className="bg-accent/10 text-accent text-xs px-3 py-1 rounded-full">
                            {tw.topic} ({Math.round(tw.weight * 100)}%)
                          </span>
                        ))}
                    </div>
                  </div>
                )}

                {tutorials.some(t => t.status === "completed" && t.analysis?.problems?.length) && (
                  <div className="mt-4 pt-4 border-t border-line">
                    <div className="text-xs font-mono text-ink-mute uppercase tracking-widest mb-2">
                      {t("Practice Problems · likely to reappear with new numbers")}
                    </div>
                    <div className="flex flex-wrap gap-2">
                      {Array.from(
                        new Set(
                          tutorials
                            .filter(t => t.status === "completed" && t.analysis?.problems)
                            .flatMap(t =>
                              t.analysis!.problems.map(
                                p => p.concept || p.type || ""
                              )
                            )
                            .filter(Boolean)
                        )
                      )
                        .slice(0, 10)
                        .map((concept, i) => (
                          <span
                            key={i}
                            className="text-xs px-3 py-1 rounded-full"
                            style={{ backgroundColor: "#3f6f7d1a", color: "#3f6f7d" }}
                          >
                            {concept}
                          </span>
                        ))}
                    </div>
                  </div>
                )}

                {audioRecordings.some(a => a.status === "completed" && a.insights?.examHints?.length) && (
                  <div className="mt-4 pt-4 border-t border-line">
                    <div className="text-xs font-mono text-ink-mute uppercase tracking-widest mb-2">{t("Exam Hints")}</div>
                    <div className="space-y-1.5">
                      {audioRecordings
                        .filter(a => a.status === "completed" && a.insights?.examHints)
                        .flatMap(a => a.insights!.examHints.filter(h => h.confidence >= 0.7))
                        .slice(0, 5)
                        .map((hint, i) => (
                          <div key={i} className="text-sm text-ink-soft flex items-start gap-2">
                            <span className="text-gold flex-shrink-0">●</span>
                            <span>{hint.hint}</span>
                          </div>
                        ))}
                    </div>
                  </div>
                )}
              </div>
            </section>
          )}

          {/* Study tools */}
          <section className="mb-12 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-5">
            <div className="bg-paper border border-line rounded-3xl p-7 flex flex-col justify-between gap-5">
              <div>
                <div className="text-2xl mb-2">🎓</div>
                <h2 className="font-serif text-xl font-medium tracking-tight mb-1">
                  {t("AI Coach")}
                </h2>
                <p className="text-sm text-ink-soft">
                  {t("Chat with a coach grounded in your documents, recordings, and past exams.")}
                </p>
              </div>
              <StudyAction ready={foundationReady} reason={lockReason} label={t("Ask the Coach")}
                href={`/course/${courseId}/tutor`}
                className="bg-accent text-paper px-5 py-3 rounded-full text-sm font-medium hover:bg-ink transition-all hover:-translate-y-0.5 hover:shadow-lift flex items-center justify-center gap-2"
              />
            </div>

            <div className="bg-paper border border-line rounded-3xl p-7 flex flex-col justify-between gap-5">
              <div>
                <div className="text-2xl mb-2">📝</div>
                <h2 className="font-serif text-xl font-medium tracking-tight mb-1">
                  {t("Practice Exam")}
                </h2>
                <p className="text-sm text-ink-soft">
                  {t("An AI exam from your documents, matched to your past exams.")}
                </p>
              </div>
              <StudyAction ready={foundationReady} reason={lockReason} label={t("Generate Exam")}
                href={`/course/${courseId}/exam`}
                className="bg-[#3f6f7d] text-paper px-5 py-3 rounded-full text-sm font-medium hover:bg-ink transition-all hover:-translate-y-0.5 hover:shadow-lift flex items-center justify-center gap-2"
              />
            </div>

            <div className="bg-paper border border-line rounded-3xl p-7 flex flex-col justify-between gap-5">
              <div>
                <div className="text-2xl mb-2">🗂️</div>
                <h2 className="font-serif text-xl font-medium tracking-tight mb-1">
                  {t("Flashcards")}
                </h2>
                <p className="text-sm text-ink-soft">
                  {t("Study cards weighted by past exams and lecture emphasis.")}
                </p>
              </div>
              <StudyAction ready={foundationReady} reason={lockReason} label={t("Make Flashcards")}
                href={`/course/${courseId}/flashcards`}
                className="bg-sage text-paper px-5 py-3 rounded-full text-sm font-medium hover:bg-ink transition-all hover:-translate-y-0.5 hover:shadow-lift flex items-center justify-center gap-2"
              />
            </div>

            <div className="bg-paper border border-line rounded-3xl p-7 flex flex-col justify-between gap-5">
              <div>
                <div className="text-2xl mb-2">📝</div>
                <h2 className="font-serif text-xl font-medium tracking-tight mb-1">
                  {t("Summary")}
                </h2>
                <p className="text-sm text-ink-soft">
                  {t("A structured study summary, focused on what your exams test.")}
                </p>
              </div>
              <StudyAction ready={foundationReady} reason={lockReason} label={t("Make Summary")}
                href={`/course/${courseId}/summary`}
                className="bg-gold text-paper px-5 py-3 rounded-full text-sm font-medium hover:bg-ink transition-all hover:-translate-y-0.5 hover:shadow-lift flex items-center justify-center gap-2"
              />
            </div>
          </section>

          {/* Documents Section */}
          <section id="documents" className="mb-12 scroll-mt-24" aria-label={t("Documents")}>
            <div className="flex items-center justify-between mb-6">
              <h2 className="font-serif text-2xl font-medium tracking-tight">
                {t("Documents")}
              </h2>
              <button
                onClick={() => setShowDocUpload(true)}
                className="bg-sage text-paper px-5 py-2.5 rounded-full text-sm font-medium hover:bg-ink transition flex items-center gap-2"
              >
                <span>+</span> {t("Upload")}
              </button>
            </div>

            {documents.length === 0 ? (
              <div className="bg-paper border-2 border-dashed border-line rounded-3xl p-10 text-center">
                <div className="text-4xl mb-3 opacity-60">📄</div>
                <h3 className="font-serif text-xl font-medium mb-2">
                  {t("No documents yet")}
                </h3>
                <p className="text-ink-soft text-sm mb-5 max-w-md mx-auto">
                  {t("Upload lecture PDFs, slides, or Word docs. The AI will extract topics, definitions, and formulas.")}
                </p>
                <button
                  onClick={() => setShowDocUpload(true)}
                  className="bg-sage text-paper px-5 py-2.5 rounded-full text-sm font-medium hover:bg-ink transition"
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
                  <div className="w-10 h-10 rounded-xl bg-sage/10 flex items-center justify-center text-sage text-sm font-mono uppercase">
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
          </section>

          {/* Historical Exams Section */}
          <section className="mb-12">
            <div className="flex items-center justify-between mb-6">
              <h2 className="font-serif text-2xl font-medium tracking-tight">
                {t("Past Exams")}
              </h2>
              <button
                onClick={() => setShowHistExamUpload(true)}
                disabled={!foundationReady} aria-describedby="foundation-lock-reason"
                className="bg-accent text-paper px-5 py-2.5 rounded-full text-sm font-medium hover:bg-ink transition flex items-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                <span aria-hidden="true">{foundationReady ? "+" : "🔒"}</span> {t("Upload")}
              </button>
            </div>

            {!foundationReady && <p className="mb-4 text-sm text-ink-soft">{lockReason}</p>}

            {historicalExams.length === 0 && (
              <div className="bg-paper border-2 border-dashed border-line rounded-3xl p-10 text-center">
                <div className="text-4xl mb-3 opacity-60">📋</div>
                <h3 className="font-serif text-xl font-medium mb-2">
                  {t("No past exams yet")}
                </h3>
                <p className="text-ink-soft text-sm mb-5 max-w-md mx-auto">
                  {t("Upload old exam PDFs. The AI will analyze topic weights, question patterns, and difficulty distribution.")}
                </p>
                <button
                  onClick={() => setShowHistExamUpload(true)}
                  disabled={!foundationReady} aria-describedby="foundation-lock-reason"
                  className="bg-accent text-paper px-5 py-2.5 rounded-full text-sm font-medium hover:bg-ink transition disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  <span aria-hidden="true">{foundationReady ? "+" : "🔒"}</span> {t("Upload your first past exam")}
                </button>
              </div>
            )}
            {classificationError && <p role="alert" className="text-sm text-accent mb-4">{classificationError}</p>}
            {[...HISTORICAL_EXAM_TYPES, "uncategorized" as const].map(type => {
              const exams = historicalExams.filter(exam => type === "uncategorized" ? !exam.examType : exam.examType === type);
              if (type === "uncategorized" && !exams.length) return null;
              const label = type === "uncategorized" ? "Needs classification" : EXAM_GROUP_LABELS[type];
              return <section key={type} aria-label={t(label)} className="mb-6">
                <h3 className="font-serif text-xl font-medium mb-3">{t(label)} <span className="font-mono text-sm text-ink-mute">{exams.length}</span></h3>
                {type === "uncategorized" && <p className="text-sm text-ink-soft mb-3">{t("Assign a type before using these papers for exams or summaries.")}</p>}
              <ReorderableList<HistoricalExam>
                items={exams}
                onReorder={handleReorderExams}
                onRename={handleRenameExam}
                onDelete={(exam) =>
                  handleDeleteItem("historical-exams", exam.id, exam.title)
                }
                renderIcon={() => (
                  <div className="w-10 h-10 rounded-xl bg-accent/10 flex items-center justify-center text-accent">
                    📋
                  </div>
                )}
                renderMeta={(exam) => (
                  <>
                    {new Date(exam.uploadedAt).toLocaleDateString()}
                    {exam.analysis && (exam.analysis.paperCount
                      ? ` · ${exam.analysis.paperCount} ${t("papers")} · ~${exam.analysis.totalQuestions} ${t("questions per paper")}`
                      : ` · ${exam.analysis.totalQuestions} ${t("questions")}`)}
                  </>
                )}
                renderStatus={(exam) => <div>
                  {!exam.examType && <HistoricalExamTypeSelect value="" label={`${t("Classify")} ${exam.title}`} disabled={!!classifying} onChange={type => void handleClassifyExam(exam.id, type)} />}
                  <SupportingMaterialAction kind="historical_exam" materialId={exam.id} courseId={courseId} />
                </div>}
              />
              </section>;
            })}
          </section>

          {/* Tutorials Section */}
          <section className="mb-12">
            <div className="flex items-center justify-between mb-6">
              <div>
                <h2 className="font-serif text-2xl font-medium tracking-tight">
                  {t("Tutorials")}
                </h2>
                <p className="text-ink-soft text-sm mt-1">
                  {t("Practice problems. The exam generator reuses their ideas (with different numbers) — no marks or format weighting.")}
                </p>
              </div>
              <button
                onClick={() => setShowTutorialUpload(true)}
                disabled={!foundationReady} aria-describedby="foundation-lock-reason"
                className="bg-[#3f6f7d] text-paper px-5 py-2.5 rounded-full text-sm font-medium hover:bg-ink transition flex items-center gap-2 flex-shrink-0 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                <span aria-hidden="true">{foundationReady ? "+" : "🔒"}</span> {t("Upload")}
              </button>
            </div>

            {!foundationReady && <p className="mb-4 text-sm text-ink-soft">{lockReason}</p>}

            {tutorials.length === 0 ? (
              <div className="bg-paper border-2 border-dashed border-line rounded-3xl p-10 text-center">
                <div className="text-4xl mb-3 opacity-60">✏️</div>
                <h3 className="font-serif text-xl font-medium mb-2">
                  {t("No tutorials yet")}
                </h3>
                <p className="text-ink-soft text-sm mb-5 max-w-md mx-auto">
                  {t("Upload tutorial / exercise sheets. The AI learns how topics are applied so generated exams mirror those problem ideas.")}
                </p>
                <button
                  onClick={() => setShowTutorialUpload(true)}
                  disabled={!foundationReady} aria-describedby="foundation-lock-reason"
                  className="bg-[#3f6f7d] text-paper px-5 py-2.5 rounded-full text-sm font-medium hover:bg-ink transition disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  <span aria-hidden="true">{foundationReady ? "+" : "🔒"}</span> {t("Upload your first tutorial")}
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
                  <div className="w-10 h-10 rounded-xl bg-[#3f6f7d]/10 flex items-center justify-center text-[#3f6f7d]">
                    ✏️
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
          </section>

          {/* Audio Recordings Section */}
          <section className="mb-12">
            <div className="flex items-center justify-between mb-6">
              <h2 className="font-serif text-2xl font-medium tracking-tight">
                {t("Audio Recordings")}
              </h2>
              <button
                onClick={() => setShowAudioUpload(true)}
                disabled={!foundationReady} aria-describedby="foundation-lock-reason"
                className="bg-gold text-paper px-5 py-2.5 rounded-full text-sm font-medium hover:bg-ink transition flex items-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                <span aria-hidden="true">{foundationReady ? "+" : "🔒"}</span> {t("Upload")}
              </button>
            </div>

            {!foundationReady && <p className="mb-4 text-sm text-ink-soft">{lockReason}</p>}

            {audioRecordings.length === 0 ? (
              <div className="bg-paper border-2 border-dashed border-line rounded-3xl p-10 text-center">
                <div className="text-4xl mb-3 opacity-60">🎙️</div>
                <h3 className="font-serif text-xl font-medium mb-2">
                  {t("No recordings yet")}
                </h3>
                <p className="text-ink-soft text-sm mb-5 max-w-md mx-auto">
                  {t("Upload professor lecture recordings. The AI will transcribe them and extract exam hints.")}
                </p>
                <button
                  onClick={() => setShowAudioUpload(true)}
                  disabled={!foundationReady} aria-describedby="foundation-lock-reason"
                  className="bg-gold text-paper px-5 py-2.5 rounded-full text-sm font-medium hover:bg-ink transition disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  <span aria-hidden="true">{foundationReady ? "+" : "🔒"}</span> {t("Upload your first recording")}
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
                    🎙️
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
          </section>

        </main>
      </div>

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

      {showAudioUpload && foundationReady && (
        <UploadAudioModal
          courseId={course.id}
          onClose={() => setShowAudioUpload(false)}
          onSuccess={loadData}
        />
      )}

      {showHistExamUpload && foundationReady && (
        <UploadHistoricalExamModal
          courseId={course.id}
          onClose={() => setShowHistExamUpload(false)}
          onSuccess={loadData}
        />
      )}

      {showTutorialUpload && foundationReady && (
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
