"use client";

import { useEffect, useState, useRef } from "react";
import { useRouter, useParams } from "next/navigation";
import Link from "next/link";
import Navbar from "@/components/Navbar";
import Sidebar from "@/components/Sidebar";
import { useAuth } from "@/lib/auth-context";
import { getCourse, getUserCourses, Course } from "@/lib/firestore-helpers";
import { ordered } from "@/lib/ordering";

const API_URL =
  process.env.NEXT_PUBLIC_BACKEND_URL || "http://127.0.0.1:8000";

interface DocItem {
  id: string;
  title: string;
  fileType: string;
  status: string;
  analysis?: { topics?: string[] };
}

interface Flashcard {
  front: string;
  back: string;
  topic?: string;
  examLikelihood?: "high" | "medium" | "low";
}

interface HistExamItem {
  id: string;
  title: string;
  status: string;
}

interface TutorialItem {
  id: string;
  title: string;
  status: string;
  analysis?: { problems?: unknown[]; problemCount?: number };
}

interface AudioItem {
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

type PageState = "configure" | "generating" | "study" | "error";

// Pipeline steps shown while flashcards are generated. The last step is held
// "in progress" until the real backend request resolves.
const GEN_STEPS = [
  { label: "Reading lecture documents", duration: 2500 },
  { label: "Weighting topics by past exams", duration: 2500 },
  { label: "Pulling professor exam hints", duration: 2500 },
  { label: "Including tutorial problem types", duration: 2500 },
  { label: "Writing flashcards", duration: 4000 },
];

export default function FlashcardsPage() {
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
  const [savedSets, setSavedSets] = useState<SavedSet[]>([]);
  const [pageLoading, setPageLoading] = useState(true);

  const [selectedDocs, setSelectedDocs] = useState<Set<string>>(new Set());
  const [selectedHist, setSelectedHist] = useState<Set<string>>(new Set());
  const [selectedTut, setSelectedTut] = useState<Set<string>>(new Set());
  const [selectedAudio, setSelectedAudio] = useState<Set<string>>(new Set());
  const [count, setCount] = useState(15);

  const [pageState, setPageState] = useState<PageState>("configure");
  const [cards, setCards] = useState<Flashcard[]>([]);
  const [current, setCurrent] = useState(0);
  const [flipped, setFlipped] = useState(false);
  const [errorMsg, setErrorMsg] = useState("");

  // Generation pipeline animation state
  const [genStep, setGenStep] = useState(0);
  const [genCompleted, setGenCompleted] = useState<Set<number>>(new Set());
  const [genTimings, setGenTimings] = useState<Record<number, number>>({});
  const genCancelled = useRef(false);
  const genFinished = useRef(false);

  const formatGenTime = (ms: number) => {
    const sec = Math.floor(ms / 1000);
    const mins = Math.floor(sec / 60);
    const secs = sec % 60;
    return `${mins}:${String(secs).padStart(2, "0")}`;
  };

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

      const [docsRes, histRes, setsRes, tutRes, audioRes] = await Promise.all([
        fetch(`${API_URL}/api/documents/${courseId}`).then((r) => r.json()).catch(() => ({ documents: [] })),
        fetch(`${API_URL}/api/historical-exams/${courseId}`).then((r) => r.json()).catch(() => ({ historical_exams: [] })),
        fetch(`${API_URL}/api/flashcards/list/${courseId}`).then((r) => r.json()).catch(() => ({ sets: [] })),
        fetch(`${API_URL}/api/tutorials/${courseId}`).then((r) => r.json()).catch(() => ({ tutorials: [] })),
        fetch(`${API_URL}/api/audio/${courseId}`).then((r) => r.json()).catch(() => ({ audio_recordings: [] })),
      ]);
      const completed = ordered<DocItem>(
        (docsRes.documents || []).filter((d: DocItem) => d.status === "completed"),
        courseData?.documentOrder,
        courseData?.titleOverrides
      );
      setDocuments(completed);
      setSelectedDocs(new Set(completed.map((d: DocItem) => d.id)));

      const completedHist = ordered<HistExamItem>(
        (histRes.historical_exams || []).filter((h: HistExamItem) => h.status === "completed"),
        courseData?.examOrder,
        courseData?.titleOverrides
      );
      setHistExams(completedHist);
      setSelectedHist(new Set(completedHist.map((h: HistExamItem) => h.id)));

      const completedTut = ordered<TutorialItem>(
        (tutRes.tutorials || []).filter((t: TutorialItem) => t.status === "completed"),
        courseData?.tutorialOrder,
        courseData?.titleOverrides
      );
      setTutorials(completedTut);
      setSelectedTut(new Set(completedTut.map((t: TutorialItem) => t.id)));

      const completedAudio = ordered<AudioItem>(
        (audioRes.audio_recordings || []).filter((a: AudioItem) => a.status === "completed"),
        courseData?.audioOrder,
        courseData?.titleOverrides
      );
      setAudioRecs(completedAudio);
      setSelectedAudio(new Set(completedAudio.map((a: AudioItem) => a.id)));

      setSavedSets(setsRes.sets || []);
    } catch (e) {
      console.error(e);
    } finally {
      setPageLoading(false);
    }
  };

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
    setCards(deck);
    setCurrent(0);
    setFlipped(false);
    setPageState("study");
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

    try {
      const res = await fetch(`${API_URL}/api/flashcards/generate`, {
        method: "POST",
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
        throw new Error(err?.detail || `Backend returned ${res.status}`);
      }
      const data = await res.json();
      genFinished.current = true;
      setGenCompleted(new Set(GEN_STEPS.map((_, i) => i)));
      startStudy(data.cards || []);
      loadData();
    } catch (e: any) {
      genFinished.current = true;
      setErrorMsg(e.message || "Could not generate flashcards.");
      setPageState("error");
    }
  };

  const openSet = async (id: string) => {
    setPageState("generating");
    try {
      const res = await fetch(`${API_URL}/api/flashcards/detail/${id}`);
      if (!res.ok) throw new Error("Set not found");
      const data = await res.json();
      startStudy(data.set?.cards || []);
    } catch (e: any) {
      setErrorMsg(e.message || "Could not open set.");
      setPageState("error");
    }
  };

  const deleteSet = async (e: React.MouseEvent, id: string, title: string) => {
    e.stopPropagation();
    if (!confirm(`Delete flashcard set "${title}"?`)) return;
    try {
      const res = await fetch(`${API_URL}/api/flashcards/${id}`, { method: "DELETE" });
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
            <Link href="/dashboard" className="inline-block bg-ink text-paper px-6 py-3 rounded-full text-sm font-medium hover:bg-accent transition">
              Back to Dashboard
            </Link>
          </div>
        </div>
      </>
    );
  }

  const renderConfigure = () => (
    <div className="space-y-8">
      <div>
        <h3 className="font-serif text-xl font-medium mb-1 tracking-tight">
          Select lecture documents
        </h3>
        <p className="text-sm text-ink-soft mb-4">
          Flashcards are built from these documents, weighted by your past exams and professor emphasis.
        </p>

        {documents.length === 0 ? (
          <div className="bg-bg-alt border border-line rounded-2xl p-6 text-center">
            <p className="text-ink-mute text-sm mb-3">
              No analyzed documents yet. Upload lecture PDFs on the course page first.
            </p>
            <Link href={`/course/${courseId}`} className="text-accent text-sm hover:underline">
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
                  </div>
                </div>
              </label>
            ))}
          </div>
        )}
      </div>

      {histExams.length > 0 && (
        <div>
          <h3 className="font-serif text-xl font-medium mb-1 tracking-tight">
            Weight by past exams
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
                  📋
                </div>
                <div className="flex-1 min-w-0">
                  <div className="font-medium truncate">{h.title}</div>
                </div>
              </label>
            ))}
          </div>
        </div>
      )}

      {tutorials.length > 0 && (
        <div>
          <h3 className="font-serif text-xl font-medium mb-1 tracking-tight">
            Include tutorials
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
                      : "analyzed"}
                  </div>
                </div>
              </label>
            ))}
          </div>
        </div>
      )}

      {audioRecs.length > 0 && (
        <div>
          <h3 className="font-serif text-xl font-medium mb-1 tracking-tight">
            Include lecture recordings
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
          </div>
        </div>
      )}

      <div>
        <label className="block text-sm font-medium text-ink-soft mb-2">
          Number of cards <span className="text-ink-mute font-normal">(max 20)</span>
        </label>
        <div className="flex items-center gap-4">
          <input
            type="range"
            min={5}
            max={20}
            step={5}
            value={count}
            onChange={(e) => setCount(Number(e.target.value))}
            className="flex-1 accent-accent"
          />
          <span className="font-mono text-sm bg-bg-alt px-3 py-1.5 rounded-lg min-w-[3rem] text-center">
            {count}
          </span>
        </div>
      </div>

      <button
        onClick={handleGenerate}
        disabled={documents.length > 0 && selectedDocs.size === 0}
        className="w-full bg-ink text-paper py-4 rounded-full text-sm font-medium hover:bg-accent transition-all hover:-translate-y-0.5 hover:shadow-lift disabled:opacity-50 disabled:cursor-not-allowed"
      >
        Generate Flashcards →
      </button>

      {savedSets.length > 0 && (
        <div>
          <h3 className="font-serif text-xl font-medium mb-4 tracking-tight">
            Saved Sets
          </h3>
          <div className="bg-paper border border-line rounded-2xl overflow-hidden">
            {savedSets.map((set, idx) => (
              <div
                key={set.id}
                onClick={() => openSet(set.id)}
                className={`flex items-center justify-between p-5 hover:bg-bg-alt transition cursor-pointer ${
                  idx !== 0 ? "border-t border-line" : ""
                }`}
              >
                <div className="flex items-center gap-4">
                  <div className="w-10 h-10 rounded-xl bg-accent/10 flex items-center justify-center text-accent">
                    🗂️
                  </div>
                  <div>
                    <div className="font-medium text-sm">{set.title}</div>
                    <div className="text-xs text-ink-mute font-mono mt-0.5">
                      {new Date(set.createdAt).toLocaleDateString()} · {set.cardCount} cards
                    </div>
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  <span className="text-ink-mute text-sm">→</span>
                  <button
                    onClick={(e) => deleteSet(e, set.id, set.title)}
                    title="Delete set"
                    className="w-8 h-8 rounded-full flex items-center justify-center text-ink-mute hover:bg-accent hover:text-paper transition text-sm"
                  >
                    🗑
                  </button>
                </div>
              </div>
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
          Building your flashcards…
        </h2>
        <p className="text-ink-soft text-sm mb-8 max-w-md mx-auto leading-relaxed">
          Pulling the most exam-relevant concepts from your materials. This usually
          takes 15–45 seconds.
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
          Hang tight — building your cards from the selected material.
        </p>
      </div>
    </div>
  );

  const renderStudy = () => {
    const card = cards[current];
    if (!card) return null;
    return (
      <div className="max-w-2xl mx-auto">
        {/* Progress */}
        <div className="flex items-center justify-between mb-4">
          <span className="font-mono text-xs text-ink-mute">
            Card {current + 1} of {cards.length}
          </span>
          <div className="flex items-center gap-2">
            {card.examLikelihood && (
              <span
                className={`text-[10px] font-mono uppercase px-2.5 py-1 rounded-full ${
                  card.examLikelihood === "high"
                    ? "bg-accent/10 text-accent"
                    : card.examLikelihood === "medium"
                    ? "bg-gold/10 text-gold"
                    : "bg-bg-alt text-ink-mute"
                }`}
                title="Likelihood of appearing on the exam"
              >
                {card.examLikelihood === "high" ? "🔥 likely exam" : `${card.examLikelihood} exam`}
              </span>
            )}
            {card.topic && (
              <span className="text-xs font-mono bg-sage/10 text-sage px-3 py-1 rounded-full">
                {card.topic}
              </span>
            )}
          </div>
          <button
            onClick={() => {
              setPageState("configure");
              loadData();
            }}
            className="font-mono text-xs text-ink-soft hover:text-accent transition"
          >
            ✕ Exit
          </button>
        </div>

        <div className="w-full bg-bg-alt rounded-full h-1.5 mb-6 overflow-hidden">
          <div
            className="bg-accent h-full transition-all"
            style={{ width: `${((current + 1) / cards.length) * 100}%` }}
          />
        </div>

        {/* Card */}
        <div
          className="flashcard-scene h-80 mb-6 cursor-pointer"
          onClick={() => setFlipped((f) => !f)}
        >
          <div className={`flashcard relative w-full h-full ${flipped ? "flipped" : ""}`}>
            {/* Front */}
            <div className="flashcard-face absolute inset-0 bg-paper border border-line rounded-3xl p-8 flex flex-col items-center justify-center text-center shadow-soft">
              <span className="font-mono text-[10px] text-ink-mute uppercase tracking-widest mb-4">
                Question
              </span>
              <p className="font-serif text-2xl font-medium leading-snug">
                {card.front}
              </p>
              <span className="font-mono text-xs text-ink-mute mt-6">
                click to flip
              </span>
            </div>
            {/* Back */}
            <div className="flashcard-face flashcard-back absolute inset-0 bg-ink text-paper rounded-3xl p-8 flex flex-col items-center justify-center text-center shadow-soft">
              <span className="font-mono text-[10px] text-paper/50 uppercase tracking-widest mb-4">
                Answer
              </span>
              <p className="text-lg leading-relaxed">{card.back}</p>
            </div>
          </div>
        </div>

        {/* Controls */}
        <div className="flex items-center justify-between gap-4">
          <button
            onClick={prev}
            disabled={current === 0}
            className="px-6 py-3 border border-line rounded-full text-sm font-medium hover:bg-bg-alt transition disabled:opacity-40 disabled:cursor-not-allowed"
          >
            ← Previous
          </button>
          <button
            onClick={() => setFlipped((f) => !f)}
            className="px-6 py-3 border border-line rounded-full text-sm font-medium hover:bg-bg-alt transition"
          >
            Flip
          </button>
          {current === cards.length - 1 ? (
            <button
              onClick={() => {
                setPageState("configure");
                loadData();
              }}
              className="px-6 py-3 bg-sage text-paper rounded-full text-sm font-medium hover:bg-ink transition"
            >
              Done ✓
            </button>
          ) : (
            <button
              onClick={next}
              className="px-6 py-3 bg-ink text-paper rounded-full text-sm font-medium hover:bg-accent transition"
            >
              Next →
            </button>
          )}
        </div>
      </div>
    );
  };

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
        <main className="flex-1 px-6 md:px-10 lg:px-12 pb-20 max-w-6xl">
          <div className="my-8 flex items-center gap-2 text-xs font-mono">
            <Link href="/dashboard" className="text-ink-soft hover:text-accent transition">
              Dashboard
            </Link>
            <span className="text-ink-mute">›</span>
            <Link href={`/course/${courseId}`} className="text-ink-soft hover:text-accent transition">
              {course.code}
            </Link>
            <span className="text-ink-mute">›</span>
            <span className="text-ink">Flashcards</span>
          </div>

          <div
            className="bg-paper border border-line rounded-3xl p-8 mb-10 relative overflow-hidden"
            style={{ borderTop: `6px solid ${course.color}` }}
          >
            <div className="font-mono text-xs text-ink-mute uppercase tracking-widest mb-3">
              {course.code} · Flashcards
            </div>
            <h1 className="font-serif text-3xl md:text-4xl font-medium tracking-tight leading-tight mb-2">
              Study <em className="italic text-accent">flashcards</em>
            </h1>
            <p className="text-ink-soft text-sm">
              AI-generated cards from your documents, weighted by past exams and lecture emphasis.
            </p>
          </div>

          {pageState === "configure" && renderConfigure()}
          {pageState === "generating" && renderGenerating()}
          {pageState === "study" && renderStudy()}
          {pageState === "error" && renderError()}
        </main>
      </div>
    </>
  );
}
