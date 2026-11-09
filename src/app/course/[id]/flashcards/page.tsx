"use client";

import { useEffect, useState, useRef, useId } from "react";
import { useRouter, useParams, useSearchParams } from "next/navigation";
import Link from "next/link";
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

interface Flashcard {
  sourceRefs?: SourceRef[];
  supportingSourceRefs?: SupportingRef[];
  provenance?: CanonicalProvenance[];
  front: string;
  back: string;
  topic?: string;
  examLikelihood?: "high" | "medium" | "low";
}

interface HistExamItem extends SupportingRow {
  id: string;
  title: string;
  status: string;
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

interface SavedSet {
  id: string;
  setId: string;
  title: string;
  cardCount: number;
  createdAt: number;
}

type PageState = "configure" | "generating" | "opening" | "study" | "error";

export default function FlashcardsPage() {
  const { user } = useAuth();
  const params = useParams();
  return <FlashcardsPageContent key={JSON.stringify([user?.uid, params.id])} />;
}

function FlashcardsPageContent() {
  const cardAccessibilityId = useId();
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
  const requestedId = searchParams.get("flashcards");
  const openedRequest = useRef("");
  const openSavedRef = useRef<((id: string) => Promise<void>) | null>(null);

  const [course, setCourse] = useState<Course | null>(null);
  const [allCourses, setAllCourses] = useState<Course[]>([]);
  const [documents, setDocuments] = useState<DocItem[]>([]);
  const [histExams, setHistExams] = useState<HistExamItem[]>([]);
  const [tutorials, setTutorials] = useState<TutorialItem[]>([]);
  const [audioRecs, setAudioRecs] = useState<AudioItem[]>([]);
  const [savedSets, setSavedSets] = useState<SavedSet[]>([]);
  const [pageLoading, setPageLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const loadRequest = useRef<AbortController | null>(null);
  const loadDataRef = useRef<(() => Promise<void>) | null>(null);
  useEffect(() => () => { loadRequest.current?.abort(); }, [courseId, user?.uid]);

  const [selectedDocs, setSelectedDocs] = useState<Set<string>>(new Set());
  const [selectedHist, setSelectedHist] = useState<Set<string>>(new Set());
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
  const [count, setCount] = useState(15);

  const [pageState, setPageState] = useState<PageState>("configure");
  const [cards, setCards] = useState<Flashcard[]>([]);
  const [current, setCurrent] = useState(0);
  const [flipped, setFlipped] = useState(false);
  const [viewingId, setViewingId] = useState("");
  const [viewingTitle, setViewingTitle] = useState("");
  const [errorMsg, setErrorMsg] = useState("");

  const studyRequest = useRef<AbortController | null>(null);
  const generationRequest = useRef<AbortController | null>(null);
  useEffect(() => () => { studyRequest.current?.abort(); }, [courseId, user?.uid]);

  useEffect(() => {
    if (foundationLoading || foundationError || foundationReady || !generationRequest.current) return;
    generationRequest.current.abort();
    generationRequest.current = null;

    setPageState("configure");
  }, [foundationReady, foundationLoading, foundationError]);

  const activityItem = course && viewingId && pageState === "study" ? { kind: "flashcards" as const, id: viewingId, title: viewingTitle, href: "/course/" + courseId + "/flashcards?flashcards=" + encodeURIComponent(viewingId), courseCode: course.code, courseColor: course.color } : null;
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

      const [docsRes, histRes, setsRes, tutRes, audioRes] = await Promise.all([
        apiJson(`${API_URL}/api/documents/${courseId}`, { signal: controller.signal }),
        apiJson(`${API_URL}/api/historical-exams/${courseId}`, { signal: controller.signal }),
        apiJson(`${API_URL}/api/flashcards/list/${courseId}`, { signal: controller.signal }),
        apiJson(`${API_URL}/api/tutorials/${courseId}`, { signal: controller.signal }),
        apiJson(`${API_URL}/api/audio/${courseId}`, { signal: controller.signal }),
      ]);
      if (controller.signal.aborted) return;
      const completed = ordered<DocItem>(
        (docsRes.documents || []).filter((d: DocItem) => d.status === "completed"),
        courseData?.documentOrder,
        courseData?.titleOverrides
      );
      setDocuments(completed);
      setSelectedDocs(new Set(completed.map((d: DocItem) => d.id)));

      const completedHist = ordered<HistExamItem>(
        histRes.historical_exams || [],
        courseData?.examOrder,
        courseData?.titleOverrides
      );
      setHistExams(previous => retainSelectedRows(completedHist, previous, selectionRef.current.hist));

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
        setSelectedHist(new Set(completedHist.filter(row => supportingPresentation(row) === "usable").map(row => row.id)));
        setSelectedTut(new Set(completedTut.filter(row => supportingPresentation(row) === "usable").map(row => row.id)));
        setSelectedAudio(new Set(completedAudio.filter(row => supportingPresentation(row) === "usable").map(row => row.id)));
      }

      setSavedSets(setsRes.sets || []);
    } catch (error: any) {
      if (!controller.signal.aborted) setLoadError(error.message || "Could not load course data.");
    } finally {
      if (!controller.signal.aborted) setPageLoading(false);
    }
  };

  loadDataRef.current = loadData;
  const toggleDoc = (id: string) => {
    setSelectedDocs((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const toggleHist = (id: string) => {
    setSelectedHist((prev) => {
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

  const startStudy = (deck: Flashcard[]) => {
    if (deck.length === 0) {
      setErrorMsg(t("This set has no cards. Choose another set or generate a new one."));
      setPageState("error");
      return;
    }
    setCards(deck);
    setCurrent(0);
    setFlipped(false);
    setPageState("study");
  };

  const handleGenerate = async () => {
    if (!user || !course || !foundationReadyRef.current || !documents.some((doc) => selectedDocs.has(doc.id))) return;
    if (supportingBlocker) { setErrorMsg(t("Selected material is unavailable. Retry or deselect it.")); return; }
    studyRequest.current?.abort();
    const controller = new AbortController();
    studyRequest.current = controller;
    generationRequest.current = controller;
    setPageState("generating");
    setErrorMsg("");

    try {
      const res = await apiFetch(`${API_URL}/api/flashcards/generate`, {
        method: "POST",
        signal: controller.signal,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          user_id: user.uid,
          course_id: courseId,
          document_ids: Array.from(selectedDocs),
          historical_exam_ids: Array.from(selectedHist),
          tutorial_ids: Array.from(selectedTut),
          audio_ids: Array.from(selectedAudio),
          count,
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
      setViewingTitle(data.title || "Flashcards");
      startStudy(data.cards || []);
      loadData();
    } catch (e: any) {
      if (controller.signal.aborted) return;

      setErrorMsg(e.message || "Could not generate flashcards.");
      setPageState("error");
    } finally {
      if (generationRequest.current === controller) generationRequest.current = null;
    }
  };

  const openSet = async (id: string) => {
    studyRequest.current?.abort();

    const controller = new AbortController();
    studyRequest.current = controller;
    setPageState("opening");
    try {
      const res = await apiFetch(`${API_URL}/api/flashcards/detail/${id}`, { signal: controller.signal });
      if (!res.ok) throw new Error("Set not found");
      const data = await res.json();
      if (controller.signal.aborted) return;
      setViewingId(id);
      setViewingTitle(data.set?.title || "Flashcards");
      startStudy(data.set?.cards || []);
    } catch (e: any) {
      if (controller.signal.aborted) return;
      setErrorMsg(e.message || "Could not open set.");
      setPageState("error");
    }
  };

  openSavedRef.current = openSet;
  const deleteSet = async (e: React.MouseEvent, id: string, title: string) => {
    e.stopPropagation();
    if (!confirm(`Delete flashcard set "${title}"?`)) return;
    try {
      const res = await apiFetch(`${API_URL}/api/flashcards/${id}`, { method: "DELETE" });
      if (!res.ok) throw new Error();
      setSavedSets((prev) => prev.filter((s) => s.id !== id));
    } catch {
      alert("Failed to delete set.");
    }
  };

  const next = () => {
    setFlipped(false);
    setCurrent((c) => Math.min(c + 1, cards.length - 1));
  };
  const prev = () => {
    setFlipped(false);
    setCurrent((c) => Math.max(c - 1, 0));
  };

  if (loadError && !pageLoading) return <AppShell courses={allCourses} course={course} courseId={courseId} activeTab="flashcards"><main className="workspace-main study-workspace"><div className="ui-panel study-busy" role="alert"><Icon name="alert" size={28} /><p>{loadError}</p><button onClick={() => loadData()} className="ui-button secondary">{t("Retry loading")}</button></div></main></AppShell>;

  if (loading || pageLoading) {
    return (
      <AppShell courses={allCourses} course={course} courseId={courseId} activeTab="flashcards"><main className="workspace-main study-workspace"><StudyBusy loading title="Loading…" /></main></AppShell>
    );
  }
  if (!user) return null;
  if (!course) {
    return (
      <AppShell courses={allCourses} course={course} courseId={courseId} activeTab="flashcards"><main className="workspace-main study-workspace"><div className="ui-panel study-busy">
          <div className="text-center">
            <h1 className="font-sans text-3xl font-medium mb-3">{t("Course not found")}</h1>
            <Link href="/dashboard" className="inline-block bg-ink text-paper px-6 py-3 rounded-full text-sm font-medium hover:bg-accent transition">
              {t("Back to Dashboard")}
            </Link>
          </div>
        </div></main></AppShell>
    );
  }

  if (!foundationReady && pageState !== "study") {
    return (
      <AppShell courses={allCourses} course={course} courseId={courseId} activeTab="flashcards"><main className="workspace-main study-workspace">
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
          Cards cover <span className="text-ink font-medium">only</span> the topics in
          the documents you tick, weighted within that scope by your past exams and
          professor emphasis.
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
                  </div>
                </div>
              </label>
            ))}
          </div>
        )}
      </div>

      {histExams.length > 0 && (
        <div>
          <h3 className="font-sans text-xl font-medium mb-1 tracking-tight">
            {t("Weight by past exams")}
          </h3>
          <p className="text-sm text-ink-soft mb-4">
            Cards are driven by these past exams and your lecture recordings — the
            most exam-likely topics come first.
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
                </div>
              </label>
            ))}
          </div>
        </div>
      )}

      {tutorials.length > 0 && (
        <div>
          <h3 className="font-sans text-xl font-medium mb-1 tracking-tight">
            {t("Include tutorials")}
          </h3>
          <p className="text-sm text-ink-soft mb-4">
            Adds cards on how to solve the practice-problem types from the
            tutorials you select.
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
                      : ""}
                  </div>
                </div>
              </label>
            ))}
          </div>
        </div>
      )}

      {audioRecs.length > 0 && (
        <div>
          <h3 className="font-sans text-xl font-medium mb-1 tracking-tight">
            {t("Include lecture recordings")}
          </h3>
          <p className="text-sm text-ink-soft mb-4">
            Adds cards from what the professor said and flagged in the recordings
            you select.
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
          </div>
        </div>
      )}

      </aside>
      <div className="study-content space-y-6">
      <section className="ui-panel study-options space-y-6">
        <div><h2 className="section-heading">{t("Card options")}</h2><p className="page-subtitle">{t("Make it fit the way you study.")}</p></div>
      <div>
        <label htmlFor="flashcard-count" className="block text-sm font-medium text-ink-soft mb-2">
          {t("Number of cards")} <span className="text-ink-mute font-normal">{t("(max 20)")}</span>
        </label>
        <div className="flex items-center gap-4">
          <input
            id="flashcard-count"
            type="range"
            min={5}
            max={20}
            step={5}
            value={count}
            onChange={(e) => setCount(Number(e.target.value))}
            className="flex-1 accent-accent"
          />
          <span className="tabular-nums text-sm bg-bg-alt px-3 py-1.5 rounded-lg min-w-[3rem] text-center">
            {count}
          </span>
        </div>
      </div>

      <SupportingSelectionNotice blocker={supportingBlocker} onDeselect={deselectBlocking} onRefresh={() => void loadDataRef.current?.()} />
      <button
        onClick={handleGenerate}
        disabled={!foundationReady || !!supportingBlocker || !documents.some((doc) => selectedDocs.has(doc.id))}
        className="ui-button primary"
      >
        {t("Generate Flashcards")} <Icon name="arrow-right" size={18} />
      </button>

      </section>

      {savedSets.length > 0 && (
        <div className="study-library" id="study-library">
          <h3 className="font-sans text-xl font-medium mb-4 tracking-tight">
            {t("Saved library")}
          </h3>
          <div className="bg-paper border border-line rounded-2xl overflow-hidden">
            {savedSets.map((set, idx) => (
              <div
                key={set.id}
                className={`study-library-row ${
                  idx !== 0 ? "border-t border-line" : ""
                }`}
              >
                <button type="button" className="study-library-open" onClick={() => openSet(set.id)} onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); openSet(set.id); } }}>
                  <div className="w-10 h-10 rounded-xl bg-accent/10 flex items-center justify-center text-accent">
                    <Icon name="cards" size={18} />
                  </div>
                  <div>
                    <div className="font-medium text-sm">{set.title}</div>
                    <div className="text-xs text-ink-mute tabular-nums mt-0.5">
                      {new Date(set.createdAt).toLocaleDateString()} · {set.cardCount} cards
                    </div>
                  </div>
                </button>
                <div className="flex items-center gap-3">
                  <button
                    onClick={(e) => deleteSet(e, set.id, set.title)}
                    title="Delete set"
                    aria-label={t("Delete set")}
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

  const renderGenerating = () => <StudyBusy opening={pageState === "opening"} title="Generating your flashcards…" />;

  const renderStudy = () => {
    const card = cards[current];
    if (!card) return null;
    return (
      <div className="study-flashcards">
        {activityItem && <div className="flex justify-end mb-3"><BookmarkButton item={activityItem} size="sm" /></div>}
        {/* Progress */}
        <div className="flex items-center justify-between mb-4">
          <span className="tabular-nums text-xs text-ink-mute" role="status" aria-live="polite" aria-atomic="true">
            {t("Card")} {current + 1} {t("of")} {cards.length} · {t(flipped ? "Answer" : "Question")}
          </span>
          <div className="flex items-center gap-2">
            {card.examLikelihood && (
              <span
                className={`text-[10px] tabular-nums  px-2.5 py-1 rounded-full ${
                  card.examLikelihood === "high"
                    ? "bg-accent/10 text-accent"
                    : card.examLikelihood === "medium"
                    ? "bg-gold/10 text-gold"
                    : "bg-bg-alt text-ink-mute"
                }`}
                title="Likelihood of appearing on the exam"
              >
                {card.examLikelihood === "high" ? t("Likely exam topic") : `${card.examLikelihood} ${t("exam")}`}
              </span>
            )}
            {card.topic && (
              <div><span className="text-xs tabular-nums bg-sage/10 text-sage px-3 py-1 rounded-full">{card.topic}</span><SourceCitation courseId={courseId} sourceRefs={citationsForPath(card.provenance, "/topic").sourceRefs} /><SupportingCitation courseId={courseId} sourceRefs={citationsForPath(card.provenance, "/topic").supportingSourceRefs} /></div>
            )}
          </div>
          <button
            onClick={() => {
              setPageState("configure");
              loadData();
            }}
            className="ui-button ghost"
          >
            <Icon name="close" size={16} /> {t("Exit")}
          </button>
        </div>

        <div className="w-full bg-bg-alt rounded-full h-1.5 mb-6 overflow-hidden">
          <div
            className="bg-accent h-full transition-colors"
            style={{ width: `${((current + 1) / cards.length) * 100}%` }}
          />
        </div>

        <SourceCitation key={`${current}-${flipped}`} courseId={courseId} sourceRefs={citationsForPath(card.provenance, flipped ? "/back" : "/front", card).sourceRefs} />
        <SupportingCitation key={`supporting-${current}-${flipped}`} courseId={courseId} sourceRefs={citationsForPath(card.provenance, flipped ? "/back" : "/front", card).supportingSourceRefs} />
        {/* Card */}
        <button
          type="button"
          className="study-flashcard flashcard-scene"
          data-side={flipped ? "answer" : "question"}
          aria-labelledby={`${cardAccessibilityId}-side ${cardAccessibilityId}-content`}
          aria-describedby={`${cardAccessibilityId}-instruction`}
          onClick={() => setFlipped((f) => !f)}
          onKeyDown={(event) => {
            if (event.key === "Enter" || event.key === " ") { event.preventDefault(); setFlipped((value) => !value); }
          }}
        >
          <span id={`${cardAccessibilityId}-side`}>{t(flipped ? "Answer" : "Question")}</span>
          <p id={`${cardAccessibilityId}-content`} dir="auto">{flipped ? card.back : card.front}</p>
          <span id={`${cardAccessibilityId}-instruction`}>{t(flipped ? "Select to see the question" : "Select to reveal the answer")}</span>
        </button>

        {/* Controls */}
        <div className="study-flashcard-controls">
          <button
            onClick={prev}
            disabled={current === 0}
            className="ui-button secondary"
          >
            <Icon name="arrow-left" size={16} /> {t("Previous")}
          </button>
          <button
            onClick={() => setFlipped((f) => !f)}
            className="ui-button secondary"
          >
            {t("Flip")}
          </button>
          {current === cards.length - 1 ? (
            <button
              onClick={() => {
                setPageState("configure");
                loadData();
              }}
              className="ui-button primary"
            >
              {t("Done")} <Icon name="check" size={16} />
            </button>
          ) : (
            <button
              onClick={next}
              className="ui-button primary"
            >
              {t("Next")} <Icon name="arrow-right" size={16} />
            </button>
          )}
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
    <AppShell courses={allCourses} course={course} courseId={courseId} activeTab="flashcards"><main className="workspace-main study-workspace">
          <StudyHeader title="Flashcards" description="Review the concepts in your course, one card at a time." icon="cards" libraryCount={pageState === "configure" ? savedSets.length : 0} />

          {pageState === "configure" && renderConfigure()}
          {(pageState === "generating" || pageState === "opening") && renderGenerating()}
          {pageState === "study" && renderStudy()}
          {pageState === "error" && renderError()}
        </main></AppShell>
  );
}
