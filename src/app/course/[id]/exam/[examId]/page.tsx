"use client";

import { useEffect, useState, useRef } from "react";
import { useRouter, useParams } from "next/navigation";
import Link from "next/link";
import Navbar from "@/components/Navbar";
import Sidebar from "@/components/Sidebar";
import BookmarkButton from "@/components/BookmarkButton";
import { useAuth } from "@/lib/auth-context";
import { getCourse, getUserCourses, Course } from "@/lib/firestore-helpers";
import { useTrackRecent } from "@/lib/activity";

const API_URL =
  process.env.NEXT_PUBLIC_BACKEND_URL || "http://127.0.0.1:8000";

interface Question {
  id: string;
  type: string;
}

interface ExamData {
  id: string;
  examId: string;
  texContent?: string;
  questionStructure: Question[];
  status: string;
  createdAt: number;
  solutionPath?: string;
  solutionType?: string;
  solutionName?: string;
}

export default function ExamAnswerPage() {
  const { user, loading } = useAuth();
  const router = useRouter();
  const params = useParams();
  const courseId = params.id as string;
  const examDbId = params.examId as string;

  const [course, setCourse] = useState<Course | null>(null);
  const [allCourses, setAllCourses] = useState<Course[]>([]);
  const [exam, setExam] = useState<ExamData | null>(null);
  const [pageLoading, setPageLoading] = useState(true);

  // The model answers are hidden until the student chooses to reveal them
  // (so they solve the exam themselves first).
  const [showAnswers, setShowAnswers] = useState(false);
  const [answersLoading, setAnswersLoading] = useState(false);

  // Optional: the student's OWN uploaded solution (shown left, for comparison).
  const [uploadingSolution, setUploadingSolution] = useState(false);
  const [uploadError, setUploadError] = useState("");
  const [dragActive, setDragActive] = useState(false);
  const solutionInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!loading && !user) router.push("/signin");
  }, [user, loading, router]);

  useEffect(() => {
    if (user && courseId && examDbId) loadData();
  }, [user, courseId, examDbId]);

  useTrackRecent(
    exam && course
      ? {
          kind: "exam",
          id: examDbId,
          title: exam.examId,
          href: `/course/${courseId}/exam/${examDbId}`,
          courseCode: course.code,
          courseColor: course.color,
        }
      : null
  );

  const loadData = async () => {
    if (!user) return;
    setPageLoading(true);
    try {
      const [courseData, allCoursesData] = await Promise.all([
        getCourse(courseId),
        getUserCourses(user.uid),
      ]);
      setCourse(courseData);
      setAllCourses(allCoursesData);

      const examRes = await fetch(`${API_URL}/api/exams/detail/${examDbId}`);
      if (!examRes.ok) throw new Error("Exam not found");
      const examData = await examRes.json();
      setExam(examData.exam as ExamData);
    } catch (error) {
      console.error(error);
    } finally {
      setPageLoading(false);
    }
  };

  const revealAnswers = () => {
    setAnswersLoading(true);
    setShowAnswers(true);
  };

  const handleSolutionDrag = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === "dragenter" || e.type === "dragover") setDragActive(true);
    else if (e.type === "dragleave") setDragActive(false);
  };

  const handleSolutionDrop = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);
    const f = e.dataTransfer.files?.[0];
    if (f) uploadSolution(f);
  };

  const uploadSolution = async (file: File) => {
    setUploadError("");
    setUploadingSolution(true);
    try {
      const formData = new FormData();
      formData.append("file", file);
      const res = await fetch(`${API_URL}/api/exams/${examDbId}/solution`, {
        method: "POST",
        body: formData,
      });
      if (!res.ok) {
        const err = await res.json().catch(() => null);
        throw new Error(err?.detail || `Upload failed (${res.status})`);
      }
      await loadData(); // refresh exam so solutionPath is present
    } catch (e: any) {
      setUploadError(e.message || "Could not upload your solution.");
    } finally {
      setUploadingSolution(false);
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

  if (!user || !course || !exam) {
    return (
      <>
        <Navbar />
        <div className="pt-20 min-h-screen flex items-center justify-center">
          <div className="text-center">
            <h1 className="font-serif text-3xl font-medium mb-3">
              Exam not found
            </h1>
            <Link
              href={`/course/${courseId}/exam`}
              className="inline-block bg-ink text-paper px-6 py-3 rounded-full text-sm font-medium hover:bg-accent transition"
            >
              Back to Exams
            </Link>
          </div>
        </div>
      </>
    );
  }

  return (
    <>
      <Navbar />
      <div className="pt-20 flex">
        <Sidebar courses={allCourses} />
        <main className="flex-1 px-6 md:px-10 lg:px-12 pb-20 max-w-7xl mx-auto w-full">
          {/* Breadcrumb */}
          <div className="my-8 flex items-center gap-2 text-xs font-mono">
            <Link
              href={`/course/${courseId}`}
              className="text-ink-soft hover:text-accent transition"
            >
              {course.code}
            </Link>
            <span className="text-ink-mute">›</span>
            <Link
              href={`/course/${courseId}/exam`}
              className="text-ink-soft hover:text-accent transition"
            >
              Exams
            </Link>
            <span className="text-ink-mute">›</span>
            <span className="text-ink">{exam.examId}</span>
            <span className="ml-auto">
              <BookmarkButton
                item={{
                  kind: "exam",
                  id: examDbId,
                  title: exam.examId,
                  href: `/course/${courseId}/exam/${examDbId}`,
                  courseCode: course.code,
                  courseColor: course.color,
                }}
                size="sm"
              />
            </span>
          </div>

          {(() => {
            const hasSolution = !!exam.solutionPath;
            const solutionUrl = exam.solutionPath
              ? `${API_URL}/api/files/serve?path=${encodeURIComponent(exam.solutionPath)}`
              : "";
            const solIsImage = ["png", "jpg", "jpeg", "webp"].includes(
              exam.solutionType || ""
            );
            const solIsPdf = exam.solutionType === "pdf";

            const hiddenInput = (
              <input
                ref={solutionInputRef}
                type="file"
                accept=".pdf,.png,.jpg,.jpeg,.webp,.docx,.txt"
                className="hidden"
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) uploadSolution(f);
                  if (solutionInputRef.current) solutionInputRef.current.value = "";
                }}
              />
            );

            // Obvious drag-and-drop zone for the student's own solution.
            const solutionDropzone = (
              <div
                onDragEnter={handleSolutionDrag}
                onDragOver={handleSolutionDrag}
                onDragLeave={handleSolutionDrag}
                onDrop={handleSolutionDrop}
                onClick={() => solutionInputRef.current?.click()}
                className={`border-2 border-dashed rounded-2xl p-6 text-center cursor-pointer transition ${
                  dragActive
                    ? "border-accent bg-accent/5 scale-[1.01]"
                    : hasSolution
                    ? "border-sage bg-sage/5"
                    : "border-line bg-bg hover:border-accent hover:bg-bg-alt"
                }`}
              >
                {uploadingSolution ? (
                  <>
                    <div className="w-8 h-8 mx-auto mb-3 border-2 border-bg-alt border-t-accent rounded-full animate-spin" />
                    <div className="text-sm font-medium">Uploading your solution…</div>
                  </>
                ) : hasSolution ? (
                  <>
                    <div className="text-3xl mb-2">✓</div>
                    <div className="text-sm font-medium text-sage">
                      {exam.solutionName || "Your solution uploaded"}
                    </div>
                    <div className="text-xs text-ink-mute mt-1">
                      Drop a new file or click to replace
                    </div>
                  </>
                ) : (
                  <>
                    <div className="text-3xl mb-2 opacity-50">
                      {dragActive ? "📥" : "📤"}
                    </div>
                    <div className="text-sm font-medium">
                      {dragActive
                        ? "Drop your solution here"
                        : "Drop your solved exam here, or click to browse"}
                    </div>
                    <div className="text-xs text-ink-mute mt-1">
                      PDF, photo (PNG/JPG), DOCX or TXT — shown beside the answers
                    </div>
                  </>
                )}
              </div>
            );

            // ---- Panels ----
            const examPanel = (
              <div className="bg-paper border border-line rounded-3xl overflow-hidden shadow-soft">
                <div className="bg-bg-alt border-b border-line px-5 py-3 flex items-center justify-between gap-3">
                  <div className="flex items-center gap-3">
                    <div className="w-2.5 h-2.5 bg-sage rounded-full" />
                    <span className="font-mono text-xs text-ink-mute">{exam.examId}.pdf</span>
                  </div>
                  <a
                    href={`${API_URL}/api/exams/${examDbId}/pdf`}
                    download={`${exam.examId}.pdf`}
                    className="border border-line text-ink-soft px-3 py-1.5 rounded-full text-xs font-medium hover:bg-paper transition"
                  >
                    ↓ Download exam
                  </a>
                </div>
                <iframe
                  src={`${API_URL}/api/exams/${examDbId}/pdf`}
                  className="w-full border-0"
                  style={{ height: "85vh" }}
                  title="Exam PDF"
                />
              </div>
            );

            const solutionPanel = (
              <div className="bg-paper border border-line rounded-3xl overflow-hidden shadow-soft">
                <div className="bg-bg-alt border-b border-line px-5 py-3 flex items-center justify-between gap-3">
                  <div className="flex items-center gap-3 min-w-0">
                    <div className="w-2.5 h-2.5 bg-sage rounded-full" />
                    <span className="font-mono text-xs text-ink-mute truncate">
                      Your solution — {exam.solutionName || "uploaded"}
                    </span>
                  </div>
                  <button
                    onClick={() => solutionInputRef.current?.click()}
                    className="border border-line text-ink-soft px-3 py-1.5 rounded-full text-xs font-medium hover:bg-paper transition flex-shrink-0"
                  >
                    Replace
                  </button>
                </div>
                {solIsPdf ? (
                  <iframe
                    src={solutionUrl}
                    className="w-full border-0"
                    style={{ height: "85vh" }}
                    title="Your solution"
                  />
                ) : solIsImage ? (
                  <div className="overflow-auto" style={{ height: "85vh" }}>
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img src={solutionUrl} alt="Your solution" className="w-full" />
                  </div>
                ) : (
                  <div
                    className="flex flex-col items-center justify-center text-center p-8"
                    style={{ height: "85vh" }}
                  >
                    <div className="text-4xl mb-3 opacity-60">📎</div>
                    <p className="text-sm text-ink-soft mb-4">
                      {exam.solutionName || "Your solution"} can&apos;t be previewed here.
                    </p>
                    <a
                      href={solutionUrl}
                      download={exam.solutionName || "solution"}
                      className="bg-ink text-paper px-5 py-2.5 rounded-full text-sm font-medium hover:bg-accent transition"
                    >
                      ↓ Download your solution
                    </a>
                  </div>
                )}
              </div>
            );

            const answersPanel = (
              <div className="bg-paper border border-line rounded-3xl overflow-hidden shadow-soft">
                <div className="bg-bg-alt border-b border-line px-5 py-3 flex items-center justify-between gap-3">
                  <div className="flex items-center gap-3">
                    <div className="w-2.5 h-2.5 bg-accent rounded-full" />
                    <span className="font-mono text-xs text-ink-mute">
                      {exam.examId}-answers.pdf
                    </span>
                  </div>
                  <div className="flex items-center gap-2">
                    <a
                      href={`${API_URL}/api/exams/${examDbId}/answer-key-pdf`}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="border border-line text-ink-soft px-3 py-1.5 rounded-full text-xs font-medium hover:bg-paper transition"
                    >
                      ↗ Open
                    </a>
                    <a
                      href={`${API_URL}/api/exams/${examDbId}/answer-key-pdf`}
                      download={`${exam.examId}-answers.pdf`}
                      className="border border-line text-ink-soft px-3 py-1.5 rounded-full text-xs font-medium hover:bg-paper transition"
                    >
                      ↓ Download
                    </a>
                  </div>
                </div>
                <div className="relative" style={{ height: "85vh" }}>
                  <iframe
                    src={`${API_URL}/api/exams/${examDbId}/answer-key-pdf`}
                    className="w-full h-full border-0"
                    title="Model Answers PDF"
                    onLoad={() => setAnswersLoading(false)}
                  />
                  {answersLoading && (
                    <div className="absolute inset-0 bg-paper flex flex-col items-center justify-center text-center px-8">
                      {/* Spinning ring */}
                      <div className="w-20 h-20 mb-6 relative">
                        <div className="w-20 h-20 border-[3px] border-bg-alt border-t-accent rounded-full animate-spin-slow" />
                        <div className="absolute inset-0 flex items-center justify-center text-2xl">
                          📝
                        </div>
                      </div>
                      <h3 className="font-serif text-xl md:text-2xl font-medium tracking-tight mb-2">
                        Preparing your model answers…
                      </h3>
                      <p className="text-ink-soft text-sm max-w-xs leading-relaxed mb-1">
                        Writing the exact answer (and why) for every question.
                      </p>
                      <p className="text-xs text-ink-mute font-mono">
                        This usually takes 2–3 minutes — please keep this tab open.
                      </p>
                    </div>
                  )}
                </div>
              </div>
            );

            const gatePanel = (
              <div className="bg-paper border border-line rounded-3xl overflow-hidden shadow-soft flex flex-col" style={{ minHeight: "85vh" }}>
                <div className="flex-1 flex flex-col items-center justify-center text-center p-8">
                  <div className="w-16 h-16 rounded-2xl bg-sage/10 flex items-center justify-center text-4xl mb-5">
                    📝
                  </div>
                  <h2 className="font-serif text-2xl font-medium tracking-tight mb-2">
                    Solve it yourself first
                  </h2>
                  <p className="text-ink-soft text-sm mb-1 max-w-sm">
                    Download the exam, work through all{" "}
                    <span className="text-ink font-medium">
                      {exam.questionStructure.length || ""}
                    </span>{" "}
                    questions on your own, then reveal the model answers to check your work.
                  </p>
                  <p className="text-xs text-ink-mute font-mono mb-7">
                    The answer key shows each full question with its answer in red.
                  </p>

                  {uploadError && (
                    <div className="bg-accent/10 border border-accent text-accent text-xs rounded-xl p-2.5 mb-4 max-w-sm">
                      {uploadError}
                    </div>
                  )}

                  <button
                    onClick={revealAnswers}
                    className="bg-ink text-paper px-7 py-3.5 rounded-full text-sm font-medium hover:bg-accent transition-all hover:-translate-y-0.5 hover:shadow-lift mb-6"
                  >
                    Reveal model answers →
                  </button>

                  <div className="w-full max-w-sm">
                    <div className="text-[11px] font-mono uppercase tracking-widest text-ink-mute mb-2">
                      Optional · compare your work
                    </div>
                    {solutionDropzone}
                  </div>
                </div>
              </div>
            );

            // ---- Layout ----
            // Left = your uploaded solution if present, else the exam PDF.
            // Right = the reveal gate, then the model answers once revealed.
            // If answers are shown and there's no uploaded solution, show only the answers.
            if (showAnswers && !hasSolution) {
              return (
                <div className="grid grid-cols-1 gap-5 max-w-4xl mx-auto">
                  {hiddenInput}
                  {answersPanel}
                  <div>
                    <div className="text-[11px] font-mono uppercase tracking-widest text-ink-mute mb-2 text-center">
                      Upload your solved exam to compare it beside the answers
                    </div>
                    {uploadError && (
                      <div className="bg-accent/10 border border-accent text-accent text-xs rounded-xl p-2.5 mb-3 text-center">
                        {uploadError}
                      </div>
                    )}
                    {solutionDropzone}
                  </div>
                </div>
              );
            }

            return (
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                {hiddenInput}
                {hasSolution ? solutionPanel : examPanel}
                {showAnswers ? answersPanel : gatePanel}
              </div>
            );
          })()}
        </main>
      </div>
    </>
  );
}
