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

interface SummarySection {
  heading: string;
  content: string;
  keyPoints?: string[];
  examLikelihood?: "high" | "medium" | "low";
  examWeight?: number;
}

interface SummaryData {
  title: string;
  overview: string;
  sections: SummarySection[];
  keyTerms?: { term: string; definition: string }[];
  examFocus?: string[];
}

interface SavedSummary {
  id: string;
  summaryId: string;
  title: string;
  sectionCount: number;
  createdAt: number;
}

type PageState = "configure" | "generating" | "view" | "error";

// Pipeline steps shown while the summary is generated. The last step is held
// "in progress" until the real backend request resolves.
const GEN_STEPS = [
  { label: "Reading lecture documents", duration: 2500 },
  { label: "Weighting topics by past exams", duration: 2500 },
  { label: "Folding in professor emphasis", duration: 2500 },
  { label: "Adding tutorial problem methods", duration: 2500 },
  { label: "Writing the study summary", duration: 4000 },
];

export default function SummaryPage() {
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
  const [savedSummaries, setSavedSummaries] = useState<SavedSummary[]>([]);
  const [pageLoading, setPageLoading] = useState(true);

  const [selectedDocs, setSelectedDocs] = useState<Set<string>>(new Set());
  const [selectedHist, setSelectedHist] = useState<Set<string>>(new Set());
  const [selectedTut, setSelectedTut] = useState<Set<string>>(new Set());
  const [selectedAudio, setSelectedAudio] = useState<Set<string>>(new Set());
  const [instructions, setInstructions] = useState("");

  const [pageState, setPageState] = useState<PageState>("configure");
  const [summary, setSummary] = useState<SummaryData | null>(null);
  const [viewingId, setViewingId] = useState("");
  const [errorMsg, setErrorMsg] = useState("");
  const [pdfNote, setPdfNote] = useState("");
  const [downloadingPdf, setDownloadingPdf] = useState(false);

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

      const [docsRes, histRes, sumRes, tutRes, audioRes] = await Promise.all([
        fetch(`${API_URL}/api/documents/${courseId}`).then((r) => r.json()).catch(() => ({ documents: [] })),
        fetch(`${API_URL}/api/historical-exams/${courseId}`).then((r) => r.json()).catch(() => ({ historical_exams: [] })),
        fetch(`${API_URL}/api/summaries/list/${courseId}`).then((r) => r.json()).catch(() => ({ summaries: [] })),
        fetch(`${API_URL}/api/tutorials/${courseId}`).then((r) => r.json()).catch(() => ({ tutorials: [] })),
        fetch(`${API_URL}/api/audio/${courseId}`).then((r) => r.json()).catch(() => ({ audio_recordings: [] })),
      ]);

      const completedDocs = ordered<DocItem>(
        (docsRes.documents || []).filter((d: DocItem) => d.status === "completed"),
        courseData?.documentOrder,
        courseData?.titleOverrides
      );
      setDocuments(completedDocs);
      setSelectedDocs(new Set(completedDocs.map((d: DocItem) => d.id)));

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

      setSavedSummaries(sumRes.summaries || []);
    } catch (e) {
      console.error(e);
    } finally {
      setPageLoading(false);
    }
  };

  const toggle = (set: Set<string>, setter: (s: Set<string>) => void, id: string) => {
    const next = new Set(set);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setter(next);
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
      const res = await fetch(`${API_URL}/api/summaries/generate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          user_id: user.uid,
          course_id: courseId,
          document_ids: Array.from(selectedDocs),
          historical_exam_ids: Array.from(selectedHist),
          tutorial_ids: Array.from(selectedTut),
          audio_ids: Array.from(selectedAudio),
          instructions: instructions.trim(),
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => null);
        throw new Error(err?.detail || `Backend returned ${res.status}`);
      }
      const data = await res.json();
      genFinished.current = true;
      setGenCompleted(new Set(GEN_STEPS.map((_, i) => i)));
      setViewingId(data.doc_id || "");
      setSummary({
        title: data.title,
        overview: data.overview,
        sections: data.sections || [],
        keyTerms: data.keyTerms || [],
        examFocus: data.examFocus || [],
      });
      setPageState("view");
      loadData();
    } catch (e: any) {
      genFinished.current = true;
      setErrorMsg(e.message || "Could not generate summary.");
      setPageState("error");
    }
  };

  const openSummary = async (id: string) => {
    setPageState("generating");
    try {
      const res = await fetch(`${API_URL}/api/summaries/detail/${id}`);
      if (!res.ok) throw new Error("Summary not found");
      const data = await res.json();
      const s = data.summary;
      setViewingId(id);
      setSummary({
        title: s.title,
        overview: s.overview,
        sections: s.sections || [],
        keyTerms: s.keyTerms || [],
        examFocus: s.examFocus || [],
      });
      setPageState("view");
    } catch (e: any) {
      setErrorMsg(e.message || "Could not open summary.");
      setPageState("error");
    }
  };

  const deleteSummary = async (e: React.MouseEvent, id: string, title: string) => {
    e.stopPropagation();
    if (!confirm(`Delete summary "${title}"?`)) return;
    try {
      const res = await fetch(`${API_URL}/api/summaries/${id}`, { method: "DELETE" });
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

    const sections = s.sections
      .map(
        (sec, i) => `
      <section class="sec">
        <h2>${i + 1}. ${esc(sec.heading)}${
          sec.examLikelihood
            ? ` <span class="badge ${sec.examLikelihood}">${esc(
                sec.examLikelihood
              )} exam${sec.examWeight ? ` · ~${sec.examWeight}%` : ""}</span>`
            : ""
        }</h2>
        ${sec.content ? `<p>${esc(sec.content)}</p>` : ""}
        ${
          (sec.keyPoints?.length ?? 0) > 0
            ? `<ul>${sec
                .keyPoints!.map((p) => `<li>${esc(p)}</li>`)
                .join("")}</ul>`
            : ""
        }
      </section>`
      )
      .join("");

    const examFocus =
      (s.examFocus?.length ?? 0) > 0
        ? `<div class="focus"><h3>🎯 Focus for the exam</h3><ul>${s
            .examFocus!.map((f) => `<li>${esc(f)}</li>`)
            .join("")}</ul></div>`
        : "";

    const keyTerms =
      (s.keyTerms?.length ?? 0) > 0
        ? `<div class="terms"><h3>Key Terms</h3>${s
            .keyTerms!.map(
              (t) =>
                `<p><strong>${esc(t.term)}</strong> — ${esc(t.definition)}</p>`
            )
            .join("")}</div>`
        : "";

    return `<!doctype html><html><head><meta charset="utf-8"><title>${esc(
      s.title
    )}</title>
    <style>
      * { box-sizing: border-box; }
      body { font-family: Georgia, 'Times New Roman', serif; color: #2b2b2b; max-width: 760px; margin: 40px auto; padding: 0 24px; line-height: 1.65; }
      h1 { font-size: 28px; margin: 0 0 12px; }
      h2 { font-size: 18px; margin: 0 0 8px; }
      h3 { font-size: 15px; margin: 0 0 8px; }
      p { margin: 0 0 10px; }
      .overview { background: #f6f4ef; padding: 16px; border-radius: 8px; }
      .focus { border: 1px solid rgba(200,71,47,.35); background: rgba(200,71,47,.05); padding: 16px; border-radius: 8px; margin: 20px 0; }
      .sec { border: 1px solid #e6e2da; padding: 16px; border-radius: 8px; margin-bottom: 16px; }
      .terms p { padding: 8px 0; border-bottom: 1px solid #eee; }
      .badge { font-size: 11px; padding: 2px 8px; border-radius: 10px; background: #eee; font-family: monospace; }
      .badge.high { background: rgba(200,71,47,.1); color: #c8472f; }
      .badge.medium { background: rgba(184,146,58,.1); color: #b8923a; }
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
        const res = await fetch(`${API_URL}/api/summaries/${viewingId}/pdf`);
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
          The summary is built from these documents, with more depth on topics your past exams emphasize.
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
                  onChange={() => toggle(selectedDocs, setSelectedDocs, doc.id)}
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
                {selectedDocs.size === documents.length ? "Deselect all" : "Select all"}
              </button>
            </div>
          </div>
        )}
      </div>

      {histExams.length > 0 && (
        <div>
          <h3 className="font-serif text-xl font-medium mb-1 tracking-tight">
            Weight by past exams
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
                  📋
                </div>
                <div className="flex-1 min-w-0">
                  <div className="font-medium truncate">{h.title}</div>
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
            Include tutorials
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
                className="text-xs text-accent hover:underline"
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
                className="text-xs text-accent hover:underline"
              >
                {selectedAudio.size === audioRecs.length ? "Deselect all" : "Select all"}
              </button>
            </div>
          </div>
        </div>
      )}

      <div>
        <h3 className="font-serif text-xl font-medium mb-1 tracking-tight">
          Custom instructions{" "}
          <span className="text-ink-mute text-sm font-normal">(optional)</span>
        </h3>
        <p className="text-sm text-ink-soft mb-3">
          Tell the AI how you want the summary — e.g. focus areas, depth, format,
          or language.
        </p>
        <textarea
          value={instructions}
          onChange={(e) => setInstructions(e.target.value)}
          rows={3}
          placeholder="e.g. Focus on chapters 3–5, keep it concise with bullet points, and explain the formulas with examples."
          className="w-full px-4 py-3 border border-line rounded-2xl bg-paper focus:outline-none focus:border-accent transition resize-y text-sm"
        />
      </div>

      <button
        onClick={handleGenerate}
        disabled={documents.length > 0 && selectedDocs.size === 0}
        className="w-full bg-ink text-paper py-4 rounded-full text-sm font-medium hover:bg-accent transition-all hover:-translate-y-0.5 hover:shadow-lift disabled:opacity-50 disabled:cursor-not-allowed"
      >
        Generate Summary →
      </button>

      {savedSummaries.length > 0 && (
        <div>
          <h3 className="font-serif text-xl font-medium mb-4 tracking-tight">
            Saved Summaries
          </h3>
          <div className="bg-paper border border-line rounded-2xl overflow-hidden">
            {savedSummaries.map((s, idx) => (
              <div
                key={s.id}
                onClick={() => openSummary(s.id)}
                className={`flex items-center justify-between p-5 hover:bg-bg-alt transition cursor-pointer ${
                  idx !== 0 ? "border-t border-line" : ""
                }`}
              >
                <div className="flex items-center gap-4">
                  <div className="w-10 h-10 rounded-xl bg-sage/10 flex items-center justify-center text-sage">
                    📝
                  </div>
                  <div>
                    <div className="font-medium text-sm">{s.title}</div>
                    <div className="text-xs text-ink-mute font-mono mt-0.5">
                      {new Date(s.createdAt).toLocaleDateString()} · {s.sectionCount} sections
                    </div>
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  <span className="text-ink-mute text-sm">→</span>
                  <button
                    onClick={(e) => deleteSummary(e, s.id, s.title)}
                    title="Delete summary"
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
          Writing your summary…
        </h2>
        <p className="text-ink-soft text-sm mb-8 max-w-md mx-auto leading-relaxed">
          Distilling your materials, weighted toward what your exams emphasize.
          This usually takes 15–45 seconds.
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
          Hang tight — distilling your selected material.
        </p>
      </div>
    </div>
  );

  const renderView = () => {
    if (!summary) return null;
    return (
      <div className="max-w-3xl">
        <div className="flex items-center justify-between mb-3 gap-3">
          <h2 className="font-serif text-2xl font-medium tracking-tight">{summary.title}</h2>
          <div className="flex items-center gap-3 flex-shrink-0">
            <button
              onClick={handleDownloadPdf}
              disabled={downloadingPdf}
              className="border border-ink text-ink px-4 py-2 rounded-full text-xs font-medium hover:bg-ink hover:text-paper transition disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {downloadingPdf ? "Preparing…" : "↓ Download PDF"}
            </button>
            <button
              onClick={() => { setPageState("configure"); setPdfNote(""); loadData(); }}
              className="font-mono text-xs text-ink-soft hover:text-accent transition"
            >
              ← Back
            </button>
          </div>
        </div>

        {pdfNote && (
          <div className="bg-gold/10 border border-gold/40 text-ink-soft text-xs rounded-xl p-3 mb-6">
            {pdfNote}
          </div>
        )}

        {summary.overview && (
          <p className="text-ink-soft leading-relaxed bg-paper border border-line rounded-2xl p-6 mb-6">
            {summary.overview}
          </p>
        )}

        {(summary.examFocus?.length ?? 0) > 0 && (
          <div className="bg-accent/5 border border-accent/30 rounded-2xl p-6 mb-8">
            <div className="font-mono text-xs text-accent uppercase tracking-widest mb-3">
              🎯 Focus for the exam
            </div>
            <ul className="space-y-1.5">
              {summary.examFocus!.map((f, i) => (
                <li key={i} className="text-sm text-ink flex items-start gap-2">
                  <span className="text-accent flex-shrink-0">●</span>
                  <span>{f}</span>
                </li>
              ))}
            </ul>
          </div>
        )}

        <div className="space-y-6">
          {summary.sections.map((sec, i) => (
            <section key={i} className="bg-paper border border-line rounded-2xl p-6">
              <div className="flex items-start justify-between gap-3 mb-2">
                <h3 className="font-serif text-xl font-medium tracking-tight flex items-center gap-3">
                  <span className="w-7 h-7 rounded-full bg-sage/10 text-sage text-xs flex items-center justify-center font-mono flex-shrink-0">
                    {i + 1}
                  </span>
                  {sec.heading}
                </h3>
                {sec.examLikelihood && (
                  <span
                    className={`text-[10px] font-mono uppercase px-2.5 py-1 rounded-full flex-shrink-0 ${
                      sec.examLikelihood === "high"
                        ? "bg-accent/10 text-accent"
                        : sec.examLikelihood === "medium"
                        ? "bg-gold/10 text-gold"
                        : "bg-bg-alt text-ink-mute"
                    }`}
                    title="Likelihood of appearing on the exam"
                  >
                    {sec.examLikelihood === "high" ? "🔥 " : ""}
                    {sec.examLikelihood} exam
                    {sec.examWeight ? ` · ~${sec.examWeight}%` : ""}
                  </span>
                )}
              </div>
              {sec.content && (
                <p className="text-sm text-ink-soft leading-relaxed mb-3">{sec.content}</p>
              )}
              {(sec.keyPoints?.length ?? 0) > 0 && (
                <ul className="space-y-1.5">
                  {sec.keyPoints!.map((p, j) => (
                    <li key={j} className="text-sm text-ink-soft flex items-start gap-2">
                      <span className="text-sage flex-shrink-0">–</span>
                      <span>{p}</span>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          ))}
        </div>

        {(summary.keyTerms?.length ?? 0) > 0 && (
          <section className="mt-8">
            <h3 className="font-serif text-xl font-medium tracking-tight mb-4">Key Terms</h3>
            <div className="bg-paper border border-line rounded-2xl overflow-hidden">
              {summary.keyTerms!.map((t, i) => (
                <div key={i} className={`px-5 py-4 ${i !== 0 ? "border-t border-line" : ""}`}>
                  <div className="font-medium text-sm text-accent">{t.term}</div>
                  <div className="text-sm text-ink-soft mt-1">{t.definition}</div>
                </div>
              ))}
            </div>
          </section>
        )}
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
            <span className="text-ink">Summary</span>
          </div>

          <div
            className="bg-paper border border-line rounded-3xl p-8 mb-10 relative overflow-hidden"
            style={{ borderTop: `6px solid ${course.color}` }}
          >
            <div className="font-mono text-xs text-ink-mute uppercase tracking-widest mb-3">
              {course.code} · Summary
            </div>
            <h1 className="font-serif text-3xl md:text-4xl font-medium tracking-tight leading-tight mb-2">
              Study <em className="italic text-accent">summary</em>
            </h1>
            <p className="text-ink-soft text-sm">
              A structured summary of your documents, weighted toward what your past exams emphasize.
            </p>
          </div>

          {pageState === "configure" && renderConfigure()}
          {pageState === "generating" && renderGenerating()}
          {pageState === "view" && renderView()}
          {pageState === "error" && renderError()}
        </main>
      </div>
    </>
  );
}
