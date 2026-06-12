"use client";

import { useEffect, useState, useRef } from "react";
import { useRouter, useParams } from "next/navigation";
import Link from "next/link";
import Navbar from "@/components/Navbar";
import Sidebar from "@/components/Sidebar";
import { useAuth } from "@/lib/auth-context";
import {
  getCourse,
  getUserCourses,
  Course,
} from "@/lib/firestore-helpers";
import { ordered } from "@/lib/ordering";

const API_URL =
  process.env.NEXT_PUBLIC_BACKEND_URL || "http://127.0.0.1:8000";

interface DocItem {
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

interface HistExamItem {
  id: string;
  title: string;
  status: string;
  analysis?: { totalQuestions?: number };
}

interface TutorialItem {
  id: string;
  title: string;
  status: string;
  analysis?: { problemCount?: number; problems?: unknown[] };
}

interface AudioItem {
  id: string;
  title: string;
  status: string;
  insights?: { examHints?: unknown[] };
}

type PageState = "configure" | "generating" | "done" | "error";

// Pipeline steps shown while the exam is generated. The last step is held
// "in progress" until the real backend request resolves.
const GEN_STEPS = [
  { label: "Analyzing lecture documents", duration: 3000 },
  { label: "Matching past exam format", duration: 3000 },
  { label: "Generating exam questions", duration: 6000 },
  { label: "Building LaTeX document", duration: 3000 },
  { label: "Compiling PDF", duration: 4000 },
];

export default function ExamPage() {
  const { user, loading } = useAuth();
  const router = useRouter();
  const params = useParams();
  const courseId = params.id as string;

  const [course, setCourse] = useState<Course | null>(null);
  const [allCourses, setAllCourses] = useState<Course[]>([]);
  const [documents, setDocuments] = useState<DocItem[]>([]);
  const [histExams, setHistExams] = useState<HistExamItem[]>([]);
  const [tutorials, setTutorials] = useState<TutorialItem[]>([]);
  const [audioRecs, setAudioRecs] = useState<AudioItem[]>([]);
  const [savedExams, setSavedExams] = useState<SavedExam[]>([]);
  const [pageLoading, setPageLoading] = useState(true);

  const [selectedDocs, setSelectedDocs] = useState<Set<string>>(new Set());
  const [selectedHist, setSelectedHist] = useState<Set<string>>(new Set());
  const [selectedTut, setSelectedTut] = useState<Set<string>>(new Set());
  const [selectedAudio, setSelectedAudio] = useState<Set<string>>(new Set());
  const [topics, setTopics] = useState("");
  const [preference, setPreference] = useState("");
  const [totalMarks, setTotalMarks] = useState(40);

  // Labels only at the defined bands; the 10-20 and 30-40 gaps are unlabeled.
  const examType = (marks: number) => {
    if (marks <= 10) return "Quiz";
    if (marks >= 20 && marks <= 30) return "Midterm";
    if (marks >= 40) return "Final";
    return "";
  };

  const [pageState, setPageState] = useState<PageState>("configure");
  const [texContent, setTexContent] = useState("");
  const [examId, setExamId] = useState("");
  const [examDocId, setExamDocId] = useState("");
  const [questionStructure, setQuestionStructure] = useState<
    { id: string; type: string }[]
  >([]);
  const [errorMsg, setErrorMsg] = useState("");

  const [intelligence, setIntelligence] = useState<{
    documents: number;
    audio: number;
    historical_exams: number;
    tutorials: number;
  } | null>(null);

  // Generation pipeline animation state
  const [genStep, setGenStep] = useState(0);
  const [genCompleted, setGenCompleted] = useState<Set<number>>(new Set());
  const [genTimings, setGenTimings] = useState<Record<number, number>>({});
  const genCancelled = useRef(false);
  const genFinished = useRef(false);

  // PDF preview state for the "done" view
  const [pdfUrl, setPdfUrl] = useState<string | null>(null);
  const [pdfStatus, setPdfStatus] = useState<"loading" | "ready" | "failed">(
    "loading"
  );

  useEffect(() => {
    return () => {
      genCancelled.current = true;
    };
  }, []);

  // When an exam is ready, fetch its PDF as a blob so a failed compile shows a
  // clean message instead of dumping the backend's raw JSON error in an iframe.
  useEffect(() => {
    if (pageState !== "done" || !examDocId) return;
    let revoked = false;
    setPdfStatus("loading");
    setPdfUrl((old) => {
      if (old) URL.revokeObjectURL(old);
      return null;
    });
    (async () => {
      try {
        const res = await fetch(`${API_URL}/api/exams/${examDocId}/pdf`);
        const ct = res.headers.get("content-type") || "";
        if (res.ok && ct.includes("pdf")) {
          const blob = await res.blob();
          if (!revoked) {
            setPdfUrl(URL.createObjectURL(blob));
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
    };
  }, [pageState, examDocId]);

  useEffect(() => {
    if (!loading && !user) router.push("/signin");
  }, [user, loading, router]);

  useEffect(() => {
    if (user && courseId) loadData();
  }, [user, courseId]);

  const loadData = async () => {
    if (!user) return;
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
      setCourse(courseData);
      setAllCourses(allCoursesData);

      const [docsRes, histRes, examsRes, intRes, tutRes, audioRes] = await Promise.all([
        fetch(`${API_URL}/api/documents/${courseId}`).then((r) => r.json()).catch(() => ({ documents: [] })),
        fetch(`${API_URL}/api/historical-exams/${courseId}`).then((r) => r.json()).catch(() => ({ historical_exams: [] })),
        fetch(`${API_URL}/api/exams/list/${courseId}`).then((r) => r.json()).catch(() => ({ exams: [] })),
        fetch(`${API_URL}/api/intelligence/${courseId}`).then((r) => r.json()).catch(() => ({})),
        fetch(`${API_URL}/api/tutorials/${courseId}`).then((r) => r.json()).catch(() => ({ tutorials: [] })),
        fetch(`${API_URL}/api/audio/${courseId}`).then((r) => r.json()).catch(() => ({ audio_recordings: [] })),
      ]);

      const completedDocs = ordered<DocItem>(
        (docsRes.documents || []).filter(
          (d: DocItem) => d.status === "completed"
        ),
        courseData?.documentOrder,
        courseData?.titleOverrides
      );
      setDocuments(completedDocs);
      setSelectedDocs(new Set(completedDocs.map((d: DocItem) => d.id)));

      const completedHist = ordered<HistExamItem>(
        (histRes.historical_exams || []).filter(
          (h: HistExamItem) => h.status === "completed"
        ),
        courseData?.examOrder,
        courseData?.titleOverrides
      );
      setHistExams(completedHist);
      setSelectedHist(new Set(completedHist.map((h: HistExamItem) => h.id)));

      const completedTut = ordered<TutorialItem>(
        (tutRes.tutorials || []).filter(
          (t: TutorialItem) => t.status === "completed"
        ),
        courseData?.tutorialOrder,
        courseData?.titleOverrides
      );
      setTutorials(completedTut);
      setSelectedTut(new Set(completedTut.map((t: TutorialItem) => t.id)));

      const completedAudio = ordered<AudioItem>(
        (audioRes.audio_recordings || []).filter(
          (a: AudioItem) => a.status === "completed"
        ),
        courseData?.audioOrder,
        courseData?.titleOverrides
      );
      setAudioRecs(completedAudio);
      setSelectedAudio(new Set(completedAudio.map((a: AudioItem) => a.id)));

      setSavedExams(examsRes.exams || []);
      setIntelligence(intRes.counts || null);
    } catch (error) {
      console.error(error);
    } finally {
      setPageLoading(false);
    }
  };

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
      const res = await fetch(`${API_URL}/api/exams/${id}`, {
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
    if (!user || !course) return;
    setPageState("generating");
    setErrorMsg("");

    // Reset + start the pipeline animation
    setGenStep(0);
    setGenCompleted(new Set());
    setGenTimings({});
    genCancelled.current = false;
    genFinished.current = false;
    const startTime = Date.now();

    (async () => {
      for (let i = 0; i < GEN_STEPS.length; i++) {
        if (genCancelled.current || genFinished.current) return;
        setGenStep(i);
        if (i === GEN_STEPS.length - 1) return; // hold last step until result
        await new Promise((r) => setTimeout(r, GEN_STEPS[i].duration));
        if (genCancelled.current || genFinished.current) return;
        setGenCompleted((prev) => new Set(prev).add(i));
        setGenTimings((prev) => ({ ...prev, [i]: Date.now() - startTime }));
      }
    })();

    const topicsList = topics
      .split(",")
      .map((t) => t.trim())
      .filter(Boolean);

    try {
      const res = await fetch(`${API_URL}/api/exams/generate-enhanced`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          user_id: user.uid,
          course_id: courseId,
          topics: topicsList.length > 0 ? topicsList : [course.title],
          preference: preference.trim() || "Generate based on historical exam format.",
          document_ids: Array.from(selectedDocs),
          historical_exam_ids: Array.from(selectedHist),
          tutorial_ids: Array.from(selectedTut),
          audio_ids: Array.from(selectedAudio),
          total_marks: totalMarks,
          exam_type: examType(totalMarks) || "Exam",
        }),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => null);
        throw new Error(err?.detail || `Backend returned ${res.status}`);
      }

      const data = await res.json();
      genFinished.current = true;

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
      setPageState("done");
    } catch (e: any) {
      console.error("Exam generation failed:", e);
      genFinished.current = true;
      setErrorMsg(
        e.message ||
          "Could not connect to the backend. Make sure the server is running."
      );
      setPageState("error");
    }
  };

  const formatGenTime = (ms: number) => {
    const sec = Math.floor(ms / 1000);
    const mins = Math.floor(sec / 60);
    const secs = sec % 60;
    return `${mins}:${String(secs).padStart(2, "0")}`;
  };

  if (loading || pageLoading) {
    return (
      <>
        <Navbar />
        <div className="pt-20 min-h-screen flex items-center justify-center">
          <div className="font-mono text-sm text-ink-mute">Loading...</div>
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
          <div className="text-center">
            <h1 className="font-serif text-3xl font-medium mb-3">Course not found</h1>
            <Link
              href="/dashboard"
              className="inline-block bg-ink text-paper px-6 py-3 rounded-full text-sm font-medium hover:bg-accent transition"
            >
              Back to Dashboard
            </Link>
          </div>
        </div>
      </>
    );
  }

  const renderConfigure = () => (
    <div className="space-y-8">
      {/* Document selection */}
      <div>
        <h3 className="font-serif text-xl font-medium mb-1 tracking-tight">
          Select lecture documents
        </h3>
        <p className="text-sm text-ink-soft mb-4">
          Choose which uploaded documents to include as source material.
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
              Go to course page to upload
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
                <div className="w-10 h-10 rounded-xl bg-sage/10 flex items-center justify-center text-sage text-xs font-mono uppercase flex-shrink-0">
                  {doc.fileType}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="font-medium truncate">{doc.title}</div>
                  <div className="text-xs text-ink-mute font-mono">
                    {doc.analysis?.topics?.length || 0} topics
                    {doc.analysis?.keyConceptCount
                      ? ` · ${doc.analysis.keyConceptCount} concepts`
                      : ""}
                  </div>
                </div>
              </label>
            ))}
            <div className="px-5 py-3 bg-bg-alt border-t border-line flex items-center justify-between">
              <span className="text-xs text-ink-mute font-mono">
                {selectedDocs.size} of {documents.length} selected
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
                  ? "Deselect all"
                  : "Select all"}
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Past exam selection */}
      {histExams.length > 0 && (
        <div>
          <h3 className="font-serif text-xl font-medium mb-1 tracking-tight">
            Base it on past exams
          </h3>
          <p className="text-sm text-ink-soft mb-4">
            The generated exam mirrors the format and grading weights of the past
            exams you select here, and weights topics by how heavily they appear in them.
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
                  📋
                </div>
                <div className="flex-1 min-w-0">
                  <div className="font-medium truncate">{h.title}</div>
                  <div className="text-xs text-ink-mute font-mono">
                    {h.analysis?.totalQuestions
                      ? `${h.analysis.totalQuestions} questions`
                      : "analyzed"}
                  </div>
                </div>
              </label>
            ))}
            <div className="px-5 py-3 bg-bg-alt border-t border-line flex items-center justify-between">
              <span className="text-xs text-ink-mute font-mono">
                {selectedHist.size} of {histExams.length} selected
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
                {selectedHist.size === histExams.length ? "Deselect all" : "Select all"}
              </button>
            </div>
          </div>
        </div>
      )}

      {tutorials.length > 0 && (
        <div>
          <h3 className="font-serif text-xl font-medium mb-1 tracking-tight">
            Include tutorial problems
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
                  style={{ accentColor: "#3f6f7d" }}
                />
                <div
                  className="w-10 h-10 rounded-xl flex items-center justify-center flex-shrink-0"
                  style={{ backgroundColor: "#3f6f7d1a", color: "#3f6f7d" }}
                >
                  ✏️
                </div>
                <div className="flex-1 min-w-0">
                  <div className="font-medium truncate">{t.title}</div>
                  <div className="text-xs text-ink-mute font-mono">
                    {t.analysis?.problems?.length
                      ? `${t.analysis.problems.length} problems`
                      : t.analysis?.problemCount
                      ? `${t.analysis.problemCount} problems`
                      : "analyzed"}
                  </div>
                </div>
              </label>
            ))}
            <div className="px-5 py-3 bg-bg-alt border-t border-line flex items-center justify-between">
              <span className="text-xs text-ink-mute font-mono">
                {selectedTut.size} of {tutorials.length} selected
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
                style={{ color: "#3f6f7d" }}
              >
                {selectedTut.size === tutorials.length ? "Deselect all" : "Select all"}
              </button>
            </div>
          </div>
        </div>
      )}

      {audioRecs.length > 0 && (
        <div>
          <h3 className="font-serif text-xl font-medium mb-1 tracking-tight">
            Include lecture recordings
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
                  style={{ accentColor: "#b8923a" }}
                />
                <div
                  className="w-10 h-10 rounded-xl flex items-center justify-center flex-shrink-0"
                  style={{ backgroundColor: "#b8923a1a", color: "#b8923a" }}
                >
                  🎙️
                </div>
                <div className="flex-1 min-w-0">
                  <div className="font-medium truncate">{a.title}</div>
                  <div className="text-xs text-ink-mute font-mono">
                    {a.insights?.examHints?.length
                      ? `${a.insights.examHints.length} exam hints`
                      : "analyzed"}
                  </div>
                </div>
              </label>
            ))}
            <div className="px-5 py-3 bg-bg-alt border-t border-line flex items-center justify-between">
              <span className="text-xs text-ink-mute font-mono">
                {selectedAudio.size} of {audioRecs.length} selected
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
                style={{ color: "#b8923a" }}
              >
                {selectedAudio.size === audioRecs.length ? "Deselect all" : "Select all"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Intelligence summary */}
      {intelligence &&
        (intelligence.historical_exams > 0 ||
          intelligence.audio > 0 ||
          intelligence.tutorials > 0) && (
          <div className="bg-paper border border-line rounded-2xl p-5">
            <h3 className="font-serif text-lg font-medium tracking-tight mb-2">
              Intelligence Data
            </h3>
            <p className="text-xs text-ink-soft mb-3">
              Topics are weighted by how often they appeared (and the marks they earned) in your past exams; rarely-tested topics get less coverage. Tutorials add practice-problem ideas (reused with different numbers) — never marks or format.
            </p>
            <div className="flex flex-wrap gap-3 text-xs font-mono">
              {intelligence.historical_exams > 0 && (
                <span className="bg-accent/10 text-accent px-2.5 py-1 rounded-full">
                  {intelligence.historical_exams} past exam
                  {intelligence.historical_exams > 1 ? "s" : ""} (topic weighting)
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
                  style={{ backgroundColor: "#3f6f7d1a", color: "#3f6f7d" }}
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
          <label className="block text-sm font-medium text-ink-soft">
            Exam total marks
          </label>
          <div className="flex items-center gap-2">
            {examType(totalMarks) && (
              <span
                className={`text-xs font-mono uppercase px-3 py-1 rounded-full ${
                  examType(totalMarks) === "Final"
                    ? "bg-accent/10 text-accent"
                    : examType(totalMarks) === "Midterm"
                    ? "bg-gold/10 text-gold"
                    : "bg-sage/10 text-sage"
                }`}
              >
                {examType(totalMarks)}
              </span>
            )}
            <span className="font-mono text-sm bg-bg-alt px-3 py-1.5 rounded-lg min-w-[3.5rem] text-center">
              {totalMarks} pts
            </span>
          </div>
        </div>

        <input
          type="range"
          min={5}
          max={40}
          step={5}
          value={totalMarks}
          onChange={(e) => setTotalMarks(Number(e.target.value))}
          className="w-full accent-accent"
        />

        {/* Labeled zones */}
        <div className="relative mt-2 h-5 text-[11px] font-mono">
          <span
            className={`absolute left-0 ${
              examType(totalMarks) === "Quiz" ? "text-sage font-medium" : "text-ink-mute"
            }`}
          >
            Quiz
            <span className="opacity-60"> ≤10</span>
          </span>
          <span
            className={`absolute left-1/2 -translate-x-1/2 ${
              examType(totalMarks) === "Midterm" ? "text-gold font-medium" : "text-ink-mute"
            }`}
          >
            Midterm
            <span className="opacity-60"> 20–30</span>
          </span>
          <span
            className={`absolute right-0 ${
              examType(totalMarks) === "Final" ? "text-accent font-medium" : "text-ink-mute"
            }`}
          >
            <span className="opacity-60">40 </span>
            Final
          </span>
        </div>
      </div>

      {/* Topics */}
      <div>
        <label className="block text-sm font-medium text-ink-soft mb-2">
          Topics{" "}
          <span className="text-ink-mute font-normal">(optional, comma-separated)</span>
        </label>
        <input
          type="text"
          value={topics}
          onChange={(e) => setTopics(e.target.value)}
          placeholder={`e.g. ${course.title}, Key concepts`}
          className="w-full px-4 py-3 border border-line rounded-xl bg-bg focus:outline-none focus:border-accent transition"
        />
      </div>

      {/* Custom instructions */}
      <div>
        <label className="block text-sm font-medium text-ink-soft mb-2">
          Custom instructions{" "}
          <span className="text-ink-mute font-normal">(optional)</span>
        </label>
        <textarea
          value={preference}
          onChange={(e) => setPreference(e.target.value)}
          placeholder="e.g. Focus on practical applications, include diagrams..."
          rows={2}
          className="w-full px-4 py-3 border border-line rounded-xl bg-bg focus:outline-none focus:border-accent transition resize-none"
        />
      </div>

      {/* Generate button */}
      <button
        onClick={handleGenerate}
        disabled={documents.length > 0 && selectedDocs.size === 0}
        className="w-full bg-ink text-paper py-4 rounded-full text-sm font-medium hover:bg-accent transition-all hover:-translate-y-0.5 hover:shadow-lift flex items-center justify-center gap-2.5 disabled:opacity-50 disabled:cursor-not-allowed"
      >
        Generate Exam <span>→</span>
      </button>

      <p className="text-xs text-ink-mute text-center font-mono">
        Generation usually takes 2–3 minutes. Question count and format are derived
        from your past exams. Please keep this tab open.
      </p>

      {/* Previous exams */}
      {savedExams.length > 0 && (
        <div>
          <h3 className="font-serif text-xl font-medium mb-4 tracking-tight">
            Previous Exams
          </h3>
          <div className="bg-paper border border-line rounded-2xl overflow-hidden">
            {savedExams.map((exam, idx) => (
              <Link
                key={exam.id}
                href={`/course/${courseId}/exam/${exam.id}`}
                className={`flex items-center justify-between p-5 hover:bg-bg-alt transition ${
                  idx !== 0 ? "border-t border-line" : ""
                }`}
              >
                <div className="flex items-center gap-4">
                  <div
                    className={`w-10 h-10 rounded-xl flex items-center justify-center text-sm ${
                      exam.status === "graded"
                        ? "bg-sage/10 text-sage"
                        : "bg-accent/10 text-accent"
                    }`}
                  >
                    {exam.status === "graded" ? "A+" : "?"}
                  </div>
                  <div>
                    <div className="font-medium font-mono text-sm">
                      {exam.examId}
                    </div>
                    <div className="text-xs text-ink-mute font-mono mt-0.5">
                      {new Date(exam.createdAt).toLocaleDateString()} ·{" "}
                      {exam.questionCount} questions
                    </div>
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  {exam.grade ? (
                    <span className="font-mono text-sm text-sage font-medium">
                      {exam.grade.percentage}%
                    </span>
                  ) : (
                    <span className="font-mono text-xs text-ink-mute">
                      Not submitted
                    </span>
                  )}
                  <span className="text-ink-mute text-sm">→</span>
                  <button
                    onClick={(e) => handleDeleteExam(e, exam.id, exam.examId)}
                    title="Delete exam"
                    className="w-8 h-8 rounded-full flex items-center justify-center text-ink-mute hover:bg-accent hover:text-paper transition text-sm"
                  >
                    🗑
                  </button>
                </div>
              </Link>
            ))}
          </div>
        </div>
      )}
    </div>
  );

  const renderGenerating = () => (
    <div className="flex items-start justify-center pt-6 pb-16">
      <div className="max-w-xl w-full text-center">
        {/* Spinning ring */}
        <div className="w-24 h-24 mx-auto mb-7 relative">
          <div className="w-24 h-24 border-[3px] border-bg-alt border-t-accent rounded-full animate-spin-slow" />
          <div className="absolute inset-0 flex items-center justify-center font-serif italic text-4xl text-accent">
            m
          </div>
        </div>

        <h2 className="font-serif text-2xl md:text-3xl font-medium mb-2 tracking-tight">
          Generating your exam…
        </h2>
        <p className="text-ink-soft text-sm mb-8 max-w-md mx-auto leading-relaxed">
          Matching the format of your past exams with content from your selected
          lectures.{" "}
          <span className="text-ink font-medium">
            This usually takes 2–3 minutes
          </span>{" "}
          — please keep this tab open.
        </p>

        {/* Pipeline steps */}
        <div className="bg-paper border border-line rounded-2xl p-5 md:p-6 text-left shadow-soft">
          {GEN_STEPS.map((step, i) => {
            const stepDone = genCompleted.has(i);
            const isActive = i === genStep && !stepDone;
            const isPending = i > genStep && !stepDone;

            return (
              <div
                key={i}
                className={`flex items-center gap-3.5 py-3 ${
                  i < GEN_STEPS.length - 1 ? "border-b border-line" : ""
                } ${isPending ? "opacity-40" : "opacity-100"}`}
              >
                <div
                  className={`w-8 h-8 rounded-full flex items-center justify-center font-mono text-xs font-semibold flex-shrink-0 transition-all ${
                    stepDone
                      ? "bg-sage text-paper"
                      : isActive
                      ? "bg-accent text-paper animate-pulse-soft"
                      : "bg-bg-alt text-ink-soft"
                  }`}
                >
                  {stepDone ? "✓" : i + 1}
                </div>
                <div className="flex-1 text-sm font-medium">{step.label}</div>
                <div className="font-mono text-[11px] text-ink-mute flex-shrink-0">
                  {stepDone
                    ? formatGenTime(genTimings[i] || 0)
                    : isActive
                    ? "in progress…"
                    : "queued"}
                </div>
              </div>
            );
          })}
        </div>

        <p className="text-xs text-ink-mute mt-5 font-mono">
          Hang tight — building your exam from the selected material.
        </p>
      </div>
    </div>
  );

  const downloadPdf = () => {
    if (!pdfUrl) return;
    const a = document.createElement("a");
    a.href = pdfUrl;
    a.download = `${examId || "exam"}.pdf`;
    a.click();
  };

  const renderDone = () => (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-3">
        <span className="font-mono text-xs text-sage bg-sage/10 px-3 py-1.5 rounded-full">
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
            Answer & Submit →
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
          <span className="font-mono text-xs text-ink-mute">{examId}.pdf</span>
        </div>

        {pdfStatus === "loading" && (
          <div className="flex items-center justify-center py-24 text-ink-mute text-sm font-mono">
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
              The server&apos;s LaTeX engine isn&apos;t available, so we
              can&apos;t render the printable sheet right now. You can still take
              the exam — click{" "}
              <span className="font-medium text-ink">Answer &amp; Submit</span>{" "}
              above. The source is shown below for reference.
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
      <div className="text-center max-w-md">
        <h2 className="font-serif text-2xl font-medium mb-3 tracking-tight">
          Generation failed
        </h2>
        <p className="text-ink-soft text-sm mb-8">{errorMsg}</p>
        <button
          onClick={() => setPageState("configure")}
          className="bg-ink text-paper px-6 py-3 rounded-full text-sm font-medium hover:bg-accent transition"
        >
          Try again
        </button>
      </div>
    </div>
  );

  return (
    <>
      <Navbar />
      <div className="pt-20 flex">
        <Sidebar courses={allCourses} />
        <main className="flex-1 px-6 md:px-10 lg:px-12 pb-20 max-w-7xl mx-auto w-full">
          <div className="my-8 flex items-center gap-2 text-xs font-mono">
            <Link href="/dashboard" className="text-ink-soft hover:text-accent transition">
              Dashboard
            </Link>
            <span className="text-ink-mute">›</span>
            <Link href={`/course/${courseId}`} className="text-ink-soft hover:text-accent transition">
              {course.code}
            </Link>
            <span className="text-ink-mute">›</span>
            <span className="text-ink">Exam</span>
          </div>

          <div
            className="bg-paper border border-line rounded-3xl p-8 mb-10 relative overflow-hidden"
            style={{ borderTop: `6px solid ${course.color}` }}
          >
            <div className="font-mono text-xs text-ink-mute uppercase tracking-widest mb-3">
              {course.code} · Exam Generator
            </div>
            <h1 className="font-serif text-3xl md:text-4xl font-medium tracking-tight leading-tight mb-2">
              Generate <em className="italic text-accent">practice exam</em>
            </h1>
            <p className="text-ink-soft text-sm">
              Select your lecture documents. The exam format and question count
              will match your uploaded past exams.
            </p>
          </div>

          {pageState === "configure" && renderConfigure()}
          {pageState === "generating" && renderGenerating()}
          {pageState === "done" && renderDone()}
          {pageState === "error" && renderError()}
        </main>
      </div>
    </>
  );
}
