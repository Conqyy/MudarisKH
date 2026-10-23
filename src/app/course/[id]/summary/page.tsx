"use client";

import { useEffect, useState, useRef } from "react";
import { useRouter, useParams, useSearchParams } from "next/navigation";
import Link from "next/link";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import SourceCitation, { SourceRef } from "@/components/SourceCitation";
import SupportingCitation from "@/components/SupportingCitation";
import type { SupportingRef } from "@/lib/supporting-materials";
import AppShell from "@/components/AppShell";
import Icon from "@/components/Icon";
import { StudyHeader, StudyBusy, StudySourceStatus } from "@/components/StudyWorkspace";
import { CourseFoundationGate } from "@/components/CourseFoundationGate";
import { useCourseFoundation } from "@/hooks/useCourseFoundation";
import BookmarkButton from "@/components/BookmarkButton";
import { useTrackRecent } from "@/lib/activity";
import { useAuth } from "@/lib/auth-context";
import { useLang } from "@/lib/i18n";
import { getCourse, getUserCourses, Course } from "@/lib/firestore-helpers";
import { ordered } from "@/lib/ordering";

import { apiFetch, apiJson } from "@/lib/api";
import { citationsForPath, CanonicalProvenance, firstSupportingBlocker, retainSelectedRows, supportingPresentation, SupportingRow } from "@/lib/supporting-materials";
import SupportingSelectionNotice from "@/components/SupportingSelectionNotice";
import HistoricalExamTypeSelect from "@/components/HistoricalExamTypeSelect";
import { useHistoricalExamSelection } from "@/hooks/useHistoricalExamSelection";
// Inline-markdown renderer: the AI writes **bold** / *italic* / `code` inside
// summary text — render it instead of showing raw asterisks. Paragraphs unwrap
// to fragments so it also works inside list items and styled containers.
const Md = ({ children }: { children: string }) => (
  <ReactMarkdown
    remarkPlugins={[remarkGfm]}
    components={{
      p: ({ children }) => <>{children}</>,
      strong: ({ children }) => (
        <strong className="font-semibold text-ink">{children}</strong>
      ),
      code: ({ children }) => (
        <code className="font-mono text-[0.9em] bg-bg-alt px-1.5 py-0.5 rounded">
          {children}
        </code>
      ),
    }}
  >
    {children}
  </ReactMarkdown>
);

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
  analysis?: { topics?: string[] };
}

interface TutorialItem extends SupportingRow {
  id: string;
  title: string;
  status: string;
  analysis?: { problems?: unknown[]; problemCount?: number };
}

interface AudioItem extends SupportingRow {
  id: string;
  title: string;
  status: string;
  insights?: { examHints?: unknown[] };
}

interface SummarySection {
  sourceRefs?: SourceRef[];
  supportingSourceRefs?: SupportingRef[];
  heading: string;
  content: string;
  keyPoints?: string[];
  examLikelihood?: "high" | "medium" | "low";
  examWeight?: number;
}

interface SummaryData {
  sourceRefs?: SourceRef[];
  supportingSourceRefs?: SupportingRef[];
  provenance?: CanonicalProvenance[];
  title: string;
  overview: string;
  sections: SummarySection[];
  keyTerms?: { term: string; definition: string; sourceRefs?: SourceRef[]; supportingSourceRefs?: SupportingRef[] }[];
  examFocus?: string[];
}

interface SavedSummary {
  id: string;
  summaryId: string;
  title: string;
  sectionCount: number;
  createdAt: number;
}

type PageState = "configure" | "generating" | "opening" | "view" | "error";

export default function SummaryPage() {
  const { user } = useAuth();
  const params = useParams();
  return <SummaryPageContent key={JSON.stringify([user?.uid, params.id])} />;
}

function SummaryPageContent() {
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
  const searchParams = useSearchParams();
  const requestedId = searchParams.get("summary");
  const openedRequest = useRef("");
  const openSavedRef = useRef<((id: string) => Promise<void>) | null>(null);

  const [course, setCourse] = useState<Course | null>(null);
  const [allCourses, setAllCourses] = useState<Course[]>([]);
  const [documents, setDocuments] = useState<DocItem[]>([]);
  const historical = useHistoricalExamSelection(courseId, user?.uid, course);
  const { rows: histExams, category: historicalExamType, selected: selectedHist, setSelected: setSelectedHist } = historical;
  const [tutorials, setTutorials] = useState<TutorialItem[]>([]);
  const [audioRecs, setAudioRecs] = useState<AudioItem[]>([]);
  const [savedSummaries, setSavedSummaries] = useState<SavedSummary[]>([]);
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
  const [instructions, setInstructions] = useState("");

  const [pageState, setPageState] = useState<PageState>("configure");
  const [summary, setSummary] = useState<SummaryData | null>(null);
  const [viewingId, setViewingId] = useState("");
  const [errorMsg, setErrorMsg] = useState("");
  const [pdfNote, setPdfNote] = useState("");
  const [downloadingPdf, setDownloadingPdf] = useState(false);

  const studyRequest = useRef<AbortController | null>(null);
  const generationRequest = useRef<AbortController | null>(null);
  useEffect(() => () => { studyRequest.current?.abort(); }, [courseId, user?.uid]);

  useEffect(() => {
    if (foundationLoading || foundationError || foundationReady || !generationRequest.current) return;
    generationRequest.current.abort();
    generationRequest.current = null;

    setPageState("configure");
  }, [foundationReady, foundationLoading, foundationError]);

  const activityItem = course && viewingId && summary && pageState === "view" ? { kind: "summary" as const, id: viewingId, title: summary.title, href: "/course/" + courseId + "/summary?summary=" + encodeURIComponent(viewingId), courseCode: course.code, courseColor: course.color } : null;
  useTrackRecent(activityItem);
  useEffect(() => {
    if (user?.uid && !pageLoading && !loadError && requestedId && openedRequest.current !== requestedId) {
      openedRequest.current = requestedId;
      openSavedRef.current?.(requestedId);
    }
  }, [user?.uid, pageLoading, loadError, requestedId]);

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

      const [docsRes, sumRes, tutRes, audioRes] = await Promise.all([
        apiJson(`${API_URL}/api/documents/${courseId}`, { signal: controller.signal }),
        apiJson(`${API_URL}/api/summaries/list/${courseId}`, { signal: controller.signal }),
        apiJson(`${API_URL}/api/tutorials/${courseId}`, { signal: controller.signal }),
        apiJson(`${API_URL}/api/audio/${courseId}`, { signal: controller.signal }),
      ]);
      if (controller.signal.aborted) return;

      const completedDocs = ordered<DocItem>(
        (docsRes.documents || []).filter((d: DocItem) => d.status === "completed"),
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

      setSavedSummaries(sumRes.summaries || []);
    } catch (error: any) {
      if (!controller.signal.aborted) setLoadError(error.message || "Could not load course data.");
    } finally {
      if (!controller.signal.aborted) setPageLoading(false);
    }
  };

  loadDataRef.current = loadData;
  const toggle = (set: Set<string>, setter: (s: Set<string>) => void, id: string) => {
    const next = new Set(set);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setter(next);
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

    try {
      const res = await apiFetch(`${API_URL}/api/summaries/generate`, {
        method: "POST",
        signal: controller.signal,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          user_id: user.uid,
          course_id: courseId,
          document_ids: Array.from(selectedDocs),
          historical_exam_ids: histExams.filter(row => selectedHist.has(row.id)).map(row => row.id),
          historical_exam_type: historicalExamType,
          tutorial_ids: Array.from(selectedTut),
          audio_ids: Array.from(selectedAudio),
          instructions: instructions.trim(),
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

      setViewingId(data.doc_id || "");
      setSummary({
        sourceRefs: data.sourceRefs,
        supportingSourceRefs: data.supportingSourceRefs,
        provenance: data.provenance,
        title: data.title,
        overview: data.overview,
        sections: data.sections || [],
        keyTerms: data.keyTerms || [],
        examFocus: data.examFocus || [],
      });
      setPageState("view");
      loadData();
    } catch (e: any) {
      if (controller.signal.aborted) return;

      setErrorMsg(e.message || "Could not generate summary.");
      setPageState("error");
    } finally {
      if (generationRequest.current === controller) generationRequest.current = null;
    }
  };

  const openSummary = async (id: string) => {
    studyRequest.current?.abort();

    const controller = new AbortController();
    studyRequest.current = controller;
    setPageState("opening");
    try {
      const res = await apiFetch(`${API_URL}/api/summaries/detail/${id}`, { signal: controller.signal });
      if (!res.ok) throw new Error("Summary not found");
      const data = await res.json();
      if (controller.signal.aborted) return;
      const s = data.summary;
      setViewingId(id);
      setSummary({
        sourceRefs: s.sourceRefs,
        supportingSourceRefs: s.supportingSourceRefs,
        provenance: s.provenance,
        title: s.title,
        overview: s.overview,
        sections: s.sections || [],
        keyTerms: s.keyTerms || [],
        examFocus: s.examFocus || [],
      });
      setPageState("view");
    } catch (e: any) {
      if (controller.signal.aborted) return;
      setErrorMsg(e.message || "Could not open summary.");
      setPageState("error");
    }
  };

  openSavedRef.current = openSummary;
  const deleteSummary = async (e: React.MouseEvent, id: string, title: string) => {
    e.stopPropagation();
    if (!confirm(`Delete summary "${title}"?`)) return;
    try {
      const res = await apiFetch(`${API_URL}/api/summaries/${id}`, { method: "DELETE" });
      if (!res.ok) throw new Error();
      setSavedSummaries((prev) => prev.filter((s) => s.id !== id));
    } catch {
      alert("Failed to delete summary.");
    }
  };

  // ---- PDF download ----
  // Build a clean, printable HTML document from the summary data.
  // Used as a reliable fallback when the backend PDF compile fails.
  const buildPrintHtml = (s: SummaryData) => {
    const esc = (str: string) =>
      (str || "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;");

    // Escape HTML, then render the AI's inline markdown (**bold**, *italic*,
    // `code`) so the print view doesn't show raw asterisks.
    const md = (str: string) =>
      esc(str)
        .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
        .replace(/(^|[^*])\*([^*\n]+)\*(?!\*)/g, "$1<em>$2</em>")
        .replace(/`([^`\n]+)`/g, "<code>$1</code>");

    const sections = s.sections
      .map(
        (sec, i) => `
      <section class="sec">
        <h2>${i + 1}. ${md(sec.heading)}${
          sec.examLikelihood
            ? ` <span class="badge ${sec.examLikelihood}">${esc(
                sec.examLikelihood
              )} exam${sec.examWeight ? ` · ~${sec.examWeight}%` : ""}</span>`
            : ""
        }</h2>
        ${sec.content ? `<p>${md(sec.content)}</p>` : ""}
        ${
          (sec.keyPoints?.length ?? 0) > 0
            ? `<ul>${sec
                .keyPoints!.map((p) => `<li>${md(p)}</li>`)
                .join("")}</ul>`
            : ""
        }
      </section>`
      )
      .join("");

    const examFocus =
      (s.examFocus?.length ?? 0) > 0
        ? `<div class="focus"><h3>Focus for the exam</h3><ul>${s
            .examFocus!.map((f) => `<li>${md(f)}</li>`)
            .join("")}</ul></div>`
        : "";

    const keyTerms =
      (s.keyTerms?.length ?? 0) > 0
        ? `<div class="terms"><h3>Key Terms</h3>${s
            .keyTerms!.map(
              (t) =>
                `<p><strong>${md(t.term)}</strong> — ${md(t.definition)}</p>`
            )
            .join("")}</div>`
        : "";

    return `<!doctype html><html><head><meta charset="utf-8"><title>${esc(
      s.title
    )}</title>
    <style>
      * { box-sizing: border-box; }
      body { font-family: Manrope, Alexandria, Arial, sans-serif; color: #161923; max-width: 760px; margin: 40px auto; padding: 0 24px; line-height: 1.65; }
      h1 { font-size: 28px; margin: 0 0 12px; }
      h2 { font-size: 18px; margin: 0 0 8px; }
      h3 { font-size: 15px; margin: 0 0 8px; }
      p { margin: 0 0 10px; }
      .overview { background: #f1f3f8; padding: 16px; border-radius: 8px; }
      .focus { border: 1px solid #dce1ec; background: #e3e9fc; padding: 16px; border-radius: 8px; margin: 20px 0; }
      .sec { border: 1px solid #dce1ec; padding: 16px; border-radius: 8px; margin-bottom: 16px; }
      .terms p { padding: 8px 0; border-bottom: 1px solid #eee; }
      .badge { font-size: 11px; padding: 2px 8px; border-radius: 10px; background: #eee; font-variant-numeric: tabular-nums; }
      .badge.high { background: #eaf0ff; color: #354da8; }
      .badge.medium { background: #fff2d8; color: #825000; }
      .badge.low { background: #eee; color: #777; }
      ul { padding-inline-start: 20px; margin: 0; }
      li { margin: 3px 0; }
      @media print { body { margin: 0; } .sec, .focus, .terms { break-inside: avoid; } }
    </style></head>
    <body dir="auto">
      <h1>${esc(s.title)}</h1>
      ${s.overview ? `<p class="overview">${esc(s.overview)}</p>` : ""}
      ${examFocus}
      ${sections}
      ${keyTerms}
    </body></html>`;
  };

  const printSummary = () => {
    if (!summary) return;
    const w = window.open("", "_blank");
    if (!w) {
      setPdfNote("Please allow pop-ups for this site, then try again.");
      return;
    }
    w.document.write(buildPrintHtml(summary));
    w.document.close();
    w.focus();
    // Let the new window render before opening the print dialog
    setTimeout(() => w.print(), 350);
  };

  const handleDownloadPdf = async () => {
    setPdfNote("");
    setDownloadingPdf(true);
    try {
      // Try the backend-generated PDF first
      if (viewingId) {
        const res = await apiFetch(`${API_URL}/api/summaries/${viewingId}/pdf`);
        const contentType = res.headers.get("content-type") || "";
        if (res.ok && contentType.includes("pdf")) {
          const blob = await res.blob();
          const url = URL.createObjectURL(blob);
          const a = document.createElement("a");
          a.href = url;
          a.download = `${summary?.title || "summary"}.pdf`;
          a.click();
          URL.revokeObjectURL(url);
          return;
        }
      }
      // Backend PDF unavailable → use the browser's print-to-PDF
      setPdfNote(
        "The server PDF wasn't available, so we opened your browser's print view — choose “Save as PDF.”"
      );
      printSummary();
    } catch {
      setPdfNote(
        "Couldn't reach the server, so we opened your browser's print view — choose “Save as PDF.”"
      );
      printSummary();
    } finally {
      setDownloadingPdf(false);
    }
  };

  if (loadError && !pageLoading) return <AppShell courses={allCourses} course={course} courseId={courseId} activeTab="summary"><main className="workspace-main study-workspace"><div className="ui-panel study-busy" role="alert"><Icon name="alert" size={28} /><p>{loadError}</p><button onClick={() => loadData()} className="ui-button secondary">{t("Retry loading")}</button></div></main></AppShell>;

  if (loading || pageLoading || (course && historical.initialLoading)) {
    return (
      <AppShell courses={allCourses} course={course} courseId={courseId} activeTab="summary"><main className="workspace-main study-workspace"><StudyBusy loading title="Loading…" /></main></AppShell>
    );
  }
  if (!user) return null;
  if (!course) {
    return (
      <AppShell courses={allCourses} course={course} courseId={courseId} activeTab="summary"><main className="workspace-main study-workspace"><div className="ui-panel study-busy">
          <div className="text-center">
            <h1 className="font-sans text-3xl font-medium mb-3">{t("Course not found")}</h1>
            <Link href="/dashboard" className="inline-block bg-ink text-paper px-6 py-3 rounded-full text-sm font-medium hover:bg-accent transition">
              {t("Back to Dashboard")}
            </Link>
          </div>
        </div></main></AppShell>
    );
  }

  if (!foundationReady && pageState !== "view") {
    return (
      <AppShell courses={allCourses} course={course} courseId={courseId} activeTab="summary"><main className="workspace-main study-workspace">
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
      <div>
        <h3 className="font-sans text-xl font-medium mb-1 tracking-tight">
          {t("Select lecture documents")}
        </h3>
        <p className="text-sm text-ink-soft mb-4">
          The summary covers <span className="text-ink font-medium">only</span> the
          topics in the documents you tick — pick one chapter and you get that chapter.
          Past exams are used to prioritize within that scope, never to add other chapters.
        </p>

        {documents.length === 0 ? (
          <div className="bg-bg-alt border border-line rounded-2xl p-6 text-center">
            <p className="text-ink-mute text-sm mb-3">
              No analyzed documents yet. Upload lecture PDFs on the course page first.
            </p>
            <Link href={`/course/${courseId}`} className="text-accent text-sm hover:underline">
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
                  onChange={() => toggle(selectedDocs, setSelectedDocs, doc.id)}
                  className="w-4 h-4 accent-accent rounded"
                />
                <div className="w-10 h-10 rounded-xl bg-sage/10 flex items-center justify-center text-sage text-xs tabular-nums  flex-shrink-0">
                  {doc.fileType}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="font-medium truncate">{doc.title}</div>
                  <div className="text-xs text-ink-mute tabular-nums">
                    {doc.sourceRevision ? `${doc.unitCount ?? "—"} ${t("source units")} · ${doc.guide?.sections.length ?? "—"} ${t("guide sections")}` : `${doc.analysis?.topics?.length || 0} ${t("topics")}`}
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
                {selectedDocs.size === documents.length ? t("Deselect all") : t("Select all")}
              </button>
            </div>
          </div>
        )}
      </div>

      <div>
        <HistoricalExamTypeSelect value={historicalExamType} onChange={historical.setCategory} />
        {historical.loading && <p role="status" className="text-sm text-ink-soft">{t("Loading past exams…")}</p>}
        {historical.error && <div role="alert" className="text-sm text-accent">{historical.error}<button type="button" onClick={() => void historical.refresh()} className="ml-3 underline">{t("Retry")}</button></div>}
        {!historical.loading && !historical.error && histExams.length === 0 && <p className="text-sm text-ink-soft">{t("No past exams in this category. Classify existing papers on the course page or upload this type.")}</p>}
      </div>
      {histExams.length > 0 && (
        <div>
          <h3 className="font-sans text-xl font-medium mb-1 tracking-tight">
            {t("Weight by past exams")}
          </h3>
          <p className="text-sm text-ink-soft mb-4">
            Selected past exams tell the summary which topics to emphasize.
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
                  onChange={() => toggle(selectedHist, setSelectedHist, h.id)}
                  className="w-4 h-4 accent-accent rounded"
                />
                <div className="w-10 h-10 rounded-xl bg-accent/10 flex items-center justify-center text-accent flex-shrink-0">
                  <Icon name="exam" size={18} />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="font-medium truncate">{h.title}</div><StudySourceStatus row={h} />
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
            {t("Include tutorials")}
          </h3>
          <p className="text-sm text-ink-soft mb-4">
            The summary will explain how to solve the practice-problem types from
            the tutorials you select.
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
                  onChange={() => toggle(selectedTut, setSelectedTut, t.id)}
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
                className="text-xs text-accent hover:underline"
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
            The summary draws on what the professor said and emphasized in the
            recordings you select.
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
                  onChange={() => toggle(selectedAudio, setSelectedAudio, a.id)}
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
                className="text-xs text-accent hover:underline"
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
        <div><h2 className="section-heading">{t("Summary options")}</h2><p className="page-subtitle">{t("Make it fit the way you study.")}</p></div>
      <div>
        <h3 className="font-sans text-xl font-medium mb-1 tracking-tight">
          {t("Custom instructions")}{" "}
          <span className="text-ink-mute text-sm font-normal">{t("(optional)")}</span>
        </h3>
        <p className="text-sm text-ink-soft mb-3">
          Tell the AI how you want the summary — e.g. focus areas, depth, format,
          or language.
        </p>
        <textarea
          aria-label={t("Custom instructions")}
          value={instructions}
          onChange={(e) => setInstructions(e.target.value)}
          rows={3}
          placeholder="e.g. Focus on chapters 3–5, keep it concise with bullet points, and explain the formulas with examples."
          className="w-full px-4 py-3 border border-line rounded-2xl bg-paper focus:outline-none focus:border-accent transition resize-y text-sm"
        />
      </div>

      <SupportingSelectionNotice blocker={supportingBlocker} onDeselect={deselectBlocking} onRefresh={() => { void loadDataRef.current?.(); }} />
      <button
        onClick={handleGenerate}
        disabled={!foundationReady || historical.loading || !!historical.error || !!supportingBlocker || !documents.some((doc) => selectedDocs.has(doc.id))}
        className="ui-button primary"
      >
        {t("Generate Summary")} <Icon name="arrow-right" size={18} />
      </button>

      </section>

      {savedSummaries.length > 0 && (
        <div className="study-library" id="study-library">
          <h3 className="font-sans text-xl font-medium mb-4 tracking-tight">
            {t("Saved library")}
          </h3>
          <div className="bg-paper border border-line rounded-2xl overflow-hidden">
            {savedSummaries.map((s, idx) => (
              <div
                key={s.id}
                className={`study-library-row ${
                  idx !== 0 ? "border-t border-line" : ""
                }`}
              >
                <button type="button" className="study-library-open" onClick={() => openSummary(s.id)} onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); openSummary(s.id); } }}>
                  <div className="w-10 h-10 rounded-xl bg-sage/10 flex items-center justify-center text-sage">
                    <Icon name="summary" size={20} />
                  </div>
                  <div>
                    <div className="font-medium text-sm">{s.title}</div>
                    <div className="text-xs text-ink-mute tabular-nums mt-0.5">
                      {new Date(s.createdAt).toLocaleDateString()} · {s.sectionCount} sections
                    </div>
                  </div>
                </button>
                <div className="flex items-center gap-3">
                  <button
                    onClick={(e) => deleteSummary(e, s.id, s.title)}
                    title="Delete summary"
                    aria-label={t("Delete summary")}
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

  const renderGenerating = () => <StudyBusy opening={pageState === "opening"} title="Generating your summary…" />;

  const renderView = () => {
    if (!summary) return null;
    return (
      <div className="summary-workspace">
        <div className="study-reader-toolbar">
          <h2 className="font-sans text-3xl font-medium tracking-tight">{summary.title}</h2>
          <div className="flex items-center gap-3 flex-shrink-0">
            {activityItem && <BookmarkButton item={activityItem} size="sm" />}
            <button
              onClick={handleDownloadPdf}
              disabled={downloadingPdf}
              className="border border-ink text-ink px-4 py-2 rounded-full text-xs font-medium hover:bg-ink hover:text-paper transition disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {downloadingPdf ? "Preparing…" : "↓ Download PDF"}
            </button>
            <button
              onClick={() => { setPageState("configure"); setPdfNote(""); loadData(); }}
              className="tabular-nums text-xs text-ink-soft hover:text-accent transition"
            >
              ← Back
            </button>
          </div>
        </div>

        <div className="summary-reading-layout">
          <details className="summary-contents" open>
            <summary>{t("Contents")}</summary>
            <nav aria-label={t("Summary contents")}>
              {summary.overview && <a href="#summary-overview">{t("Overview")}</a>}
              {(summary.examFocus?.length ?? 0) > 0 && <a href="#summary-focus">{t("Focus for the exam")}</a>}
              {summary.sections.map((section, index) => <a key={index} href={`#summary-section-${index}`}>{section.heading}</a>)}
              {(summary.keyTerms?.length ?? 0) > 0 && <a href="#summary-terms">{t("Key Terms")}</a>}
            </nav>
          </details>
          <article className="study-summary" dir="auto">
        {pdfNote && (
          <div className="bg-gold/10 border border-gold/40 text-ink-soft text-xs rounded-xl p-3 mb-6">
            {pdfNote}
          </div>
        )}

        {summary.overview && (
          <div id="summary-overview" className="text-ink-soft text-base leading-relaxed mb-7">
            <Md>{summary.overview}</Md>
            <SourceCitation courseId={courseId} sourceRefs={citationsForPath(summary.provenance, "/overview", summary).sourceRefs} />
            <SupportingCitation courseId={courseId} sourceRefs={citationsForPath(summary.provenance, "/overview", summary).supportingSourceRefs} />
          </div>
        )}

        {(summary.examFocus?.length ?? 0) > 0 && (
          <div id="summary-focus" className="bg-bg-alt rounded-2xl p-6 mb-9">
            <div className="tabular-nums text-xs text-accent  mb-4">
              {t("Focus for the exam")}
            </div>
            <ul className="space-y-2.5">
              {summary.examFocus!.map((f, i) => (
                <li key={i} className="text-base text-ink flex items-start gap-3 leading-relaxed">
                  <span className="text-accent flex-shrink-0">●</span>
                  <span><Md>{f}</Md><SourceCitation courseId={courseId} sourceRefs={citationsForPath(summary.provenance, `/examFocus/${i}`).sourceRefs} /><SupportingCitation courseId={courseId} sourceRefs={citationsForPath(summary.provenance, `/examFocus/${i}`).supportingSourceRefs} /></span>
                </li>
              ))}
            </ul>
          </div>
        )}

        <div className="space-y-7">
          {summary.sections.map((sec, i) => (
            <section key={i} id={`summary-section-${i}`} className="summary-section">
              <div className="flex items-start justify-between gap-3 mb-4">
                <h3 className="font-sans text-2xl font-medium tracking-tight flex items-center gap-3">
                  <span className="w-9 h-9 rounded-full bg-sage/10 text-sage text-sm flex items-center justify-center tabular-nums flex-shrink-0">
                    {i + 1}
                  </span>
                  {sec.heading}
                </h3>
                {sec.examLikelihood && (
                  <span
                    className={`text-[11px] tabular-nums  px-3 py-1.5 rounded-full flex-shrink-0 ${
                      sec.examLikelihood === "high"
                        ? "bg-accent/10 text-accent"
                        : sec.examLikelihood === "medium"
                        ? "bg-gold/10 text-gold"
                        : "bg-bg-alt text-ink-mute"
                    }`}
                    title="Likelihood of appearing on the exam"
                  >

                    {sec.examLikelihood} exam
                    {sec.examWeight ? ` · ~${sec.examWeight}%` : ""}
                  </span>
                )}
              </div>
              <SourceCitation courseId={courseId} sourceRefs={sec.sourceRefs} />
              <SupportingCitation courseId={courseId} sourceRefs={sec.supportingSourceRefs} />
              {sec.content && (
                <div className="text-base text-ink-soft leading-relaxed mb-4">
                  <Md>{sec.content}</Md>
                </div>
              )}
              {(sec.keyPoints?.length ?? 0) > 0 && (
                <ul className="space-y-2.5 bg-bg rounded-xl border border-line p-5">
                  {sec.keyPoints!.map((p, j) => (
                    <li key={j} className="text-base text-ink-soft flex items-start gap-3 leading-relaxed">
                      <span className="text-sage flex-shrink-0">–</span>
                      <span><Md>{p}</Md></span>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          ))}
        </div>

        {(summary.keyTerms?.length ?? 0) > 0 && (
          <section id="summary-terms" className="mt-10">
            <h3 className="font-sans text-2xl font-medium tracking-tight mb-5">{t("Key Terms")}</h3>
            <div className="bg-paper border border-line rounded-2xl overflow-hidden">
              {summary.keyTerms!.map((t, i) => (
                <div key={i} className={`px-6 py-5 ${i !== 0 ? "border-t border-line" : ""}`}>
                  <div className="font-medium text-base text-accent"><Md>{t.term}</Md></div>
                  <div className="text-base text-ink-soft mt-1.5 leading-relaxed">
                    <Md>{t.definition}</Md>
                  </div>
                  <SourceCitation courseId={courseId} sourceRefs={t.sourceRefs} />
                  <SupportingCitation courseId={courseId} sourceRefs={t.supportingSourceRefs} />
                </div>
              ))}
            </div>
          </section>
        )}
          </article>
        </div>
      </div>
    );
  };

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
    <AppShell courses={allCourses} course={course} courseId={courseId} activeTab="summary"><main className="workspace-main study-workspace">
          <StudyHeader title="Summaries" description="Turn your course materials into a focused study reference." icon="summary" libraryCount={pageState === "configure" ? savedSummaries.length : 0} />

          {pageState === "configure" && renderConfigure()}
          {(pageState === "generating" || pageState === "opening") && renderGenerating()}
          {pageState === "view" && renderView()}
          {pageState === "error" && renderError()}
        </main></AppShell>
  );
}
