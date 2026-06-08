"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter, useParams } from "next/navigation";
import Link from "next/link";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import Navbar from "@/components/Navbar";
import Sidebar from "@/components/Sidebar";
import { useAuth } from "@/lib/auth-context";
import { getCourse, getUserCourses, Course } from "@/lib/firestore-helpers";
import { ordered } from "@/lib/ordering";

// Tailwind-styled renderers for the tutor's Markdown replies.
// dir="auto" + logical paddings (ps-*) let Arabic render RTL and English LTR
// automatically within the same reply.
const md = {
  p: (p: any) => <p dir="auto" className="mb-2.5 last:mb-0 leading-relaxed" {...p} />,
  strong: (p: any) => <strong className="font-semibold" {...p} />,
  em: (p: any) => <em className="italic" {...p} />,
  ul: (p: any) => <ul dir="auto" className="list-disc ps-5 mb-2.5 space-y-1" {...p} />,
  ol: (p: any) => <ol dir="auto" className="list-decimal ps-5 mb-2.5 space-y-1" {...p} />,
  li: (p: any) => <li className="leading-relaxed" {...p} />,
  h1: (p: any) => <h1 dir="auto" className="font-serif text-lg font-medium mt-4 mb-1.5 first:mt-0" {...p} />,
  h2: (p: any) => <h2 dir="auto" className="font-serif text-base font-medium mt-4 mb-1.5 first:mt-0" {...p} />,
  h3: (p: any) => <h3 dir="auto" className="font-semibold text-sm mt-3 mb-1 first:mt-0" {...p} />,
  a: (p: any) => <a className="text-accent underline" target="_blank" rel="noopener noreferrer" {...p} />,
  code: (p: any) => <code className="bg-bg-alt px-1 py-0.5 rounded font-mono text-[0.85em]" {...p} />,
  pre: (p: any) => (
    <pre
      dir="ltr"
      className="bg-ink text-paper p-3 rounded-lg overflow-x-auto font-mono text-xs my-2 [&_code]:bg-transparent [&_code]:text-paper [&_code]:p-0"
      {...p}
    />
  ),
  blockquote: (p: any) => <blockquote dir="auto" className="border-s-2 border-line ps-3 italic text-ink-soft my-2" {...p} />,
  table: (p: any) => <table className="border-collapse my-2 text-xs" {...p} />,
  th: (p: any) => <th className="border border-line px-2 py-1 bg-bg-alt text-left" {...p} />,
  td: (p: any) => <td className="border border-line px-2 py-1" {...p} />,
  hr: () => <hr className="border-line my-3" />,
};

const API_URL =
  process.env.NEXT_PUBLIC_BACKEND_URL || "http://127.0.0.1:8000";

interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

interface ChatSummary {
  id: string;
  title: string;
  messageCount: number;
  updatedAt: number;
}

interface ResourceItem {
  id: string;
  title: string;
  kind: "document" | "recording" | "exam" | "tutorial";
}

const SUGGESTIONS = [
  "What topics should I focus on for the exam?",
  "Explain the hardest concept simply.",
  "Quiz me with 3 questions.",
  "Summarize the key definitions.",
];

export default function TutorPage() {
  const { user, loading } = useAuth();
  const router = useRouter();
  const params = useParams();
  const courseId = params.id as string;

  const [course, setCourse] = useState<Course | null>(null);
  const [allCourses, setAllCourses] = useState<Course[]>([]);
  const [pageLoading, setPageLoading] = useState(true);

  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [chatId, setChatId] = useState("");
  const [chats, setChats] = useState<ChatSummary[]>([]);
  const [input, setInput] = useState("");
  const [thinking, setThinking] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  // Selectable sources
  const [lectures, setLectures] = useState<ResourceItem[]>([]); // documents only
  const [recordings, setRecordings] = useState<ResourceItem[]>([]);
  const [pastExams, setPastExams] = useState<ResourceItem[]>([]);
  const [tutorials, setTutorials] = useState<ResourceItem[]>([]);
  const [selLectures, setSelLectures] = useState<Set<string>>(new Set());
  const [selRecs, setSelRecs] = useState<Set<string>>(new Set());
  const [selExams, setSelExams] = useState<Set<string>>(new Set());
  const [selTuts, setSelTuts] = useState<Set<string>>(new Set());
  const [sourcesOpen, setSourcesOpen] = useState(false);

  // Fullscreen / focus mode for the chat
  const [fullscreen, setFullscreen] = useState(false);

  // Press Esc to leave fullscreen
  useEffect(() => {
    if (!fullscreen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setFullscreen(false);
    };
    window.addEventListener("keydown", onKey);
    // Lock body scroll while the chat is full-screen
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = prevOverflow;
    };
  }, [fullscreen]);

  useEffect(() => {
    if (!loading && !user) router.push("/signin");
  }, [user, loading, router]);

  useEffect(() => {
    if (user && courseId) loadData();
  }, [user, courseId]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, thinking]);

  const loadChats = async () => {
    if (!user) return;
    try {
      const res = await fetch(`${API_URL}/api/tutor/chats/${user.uid}/${courseId}`);
      const data = await res.json();
      setChats(data.chats || []);
    } catch {
      setChats([]);
    }
  };

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
      await loadChats();

      // Load selectable sources (completed lectures/recordings + past exams + tutorials)
      const [docsRes, audioRes, histRes, tutRes] = await Promise.all([
        fetch(`${API_URL}/api/documents/${courseId}`).then((r) => r.json()).catch(() => ({ documents: [] })),
        fetch(`${API_URL}/api/audio/${courseId}`).then((r) => r.json()).catch(() => ({ audio_recordings: [] })),
        fetch(`${API_URL}/api/historical-exams/${courseId}`).then((r) => r.json()).catch(() => ({ historical_exams: [] })),
        fetch(`${API_URL}/api/tutorials/${courseId}`).then((r) => r.json()).catch(() => ({ tutorials: [] })),
      ]);
      const docsList = ordered(
        (docsRes.documents || []).filter((d: any) => d.status === "completed"),
        courseData?.documentOrder,
        courseData?.titleOverrides
      );
      const audioList = ordered(
        (audioRes.audio_recordings || []).filter(
          (a: any) => a.status === "completed"
        ),
        courseData?.audioOrder,
        courseData?.titleOverrides
      );
      const lec: ResourceItem[] = docsList.map((d: any) => ({
        id: d.id,
        title: d.title,
        kind: "document" as const,
      }));
      const recs: ResourceItem[] = audioList.map((a: any) => ({
        id: a.id,
        title: a.title,
        kind: "recording" as const,
      }));
      const exams: ResourceItem[] = ordered(
        (histRes.historical_exams || []).filter(
          (h: any) => h.status === "completed"
        ),
        courseData?.examOrder,
        courseData?.titleOverrides
      ).map((h: any) => ({ id: h.id, title: h.title, kind: "exam" as const }));
      const tuts: ResourceItem[] = ordered(
        (tutRes.tutorials || []).filter((t: any) => t.status === "completed"),
        courseData?.tutorialOrder,
        courseData?.titleOverrides
      ).map((t: any) => ({ id: t.id, title: t.title, kind: "tutorial" as const }));
      setLectures(lec);
      setRecordings(recs);
      setPastExams(exams);
      setTutorials(tuts);
      setSelLectures(new Set(lec.map((x) => x.id)));
      setSelRecs(new Set(recs.map((x) => x.id)));
      setSelExams(new Set(exams.map((x) => x.id)));
      setSelTuts(new Set(tuts.map((x) => x.id)));
    } catch (e) {
      console.error(e);
    } finally {
      setPageLoading(false);
    }
  };

  const toggleSel = (set: Set<string>, setter: (s: Set<string>) => void, id: string) => {
    const next = new Set(set);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setter(next);
  };

  const newChat = () => {
    setMessages([]);
    setChatId("");
    setInput("");
    setHistoryOpen(false);
  };

  const openChat = async (id: string) => {
    setHistoryOpen(false);
    try {
      const res = await fetch(`${API_URL}/api/tutor/chat/${id}`);
      if (!res.ok) throw new Error();
      const data = await res.json();
      setMessages(data.chat?.messages || []);
      setChatId(id);
    } catch {
      alert("Could not open this conversation.");
    }
  };

  const deleteChat = async (e: React.MouseEvent, id: string) => {
    e.stopPropagation();
    if (!confirm("Delete this conversation?")) return;
    try {
      await fetch(`${API_URL}/api/tutor/chat/${id}`, { method: "DELETE" });
      setChats((prev) => prev.filter((c) => c.id !== id));
      if (id === chatId) newChat();
    } catch {
      alert("Failed to delete.");
    }
  };

  const send = async (text: string) => {
    const content = text.trim();
    if (!content || thinking || !user) return;
    const next = [...messages, { role: "user" as const, content }];
    setMessages(next);
    setInput("");
    setThinking(true);
    try {
      const res = await fetch(`${API_URL}/api/tutor/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          user_id: user.uid,
          course_id: courseId,
          chat_id: chatId,
          messages: next,
          document_ids: Array.from(selLectures),
          recording_ids: Array.from(selRecs),
          historical_exam_ids: Array.from(selExams),
          tutorial_ids: Array.from(selTuts),
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => null);
        throw new Error(err?.detail || `Tutor error (${res.status})`);
      }
      const data = await res.json();
      setMessages((prev) => [...prev, { role: "assistant", content: data.reply || "" }]);
      if (data.chat_id && data.chat_id !== chatId) setChatId(data.chat_id);
      loadChats();
    } catch (e: any) {
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: `⚠️ ${e.message || "Something went wrong."}` },
      ]);
    } finally {
      setThinking(false);
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

  const HistoryList = () => (
    <>
      <button
        onClick={newChat}
        className="w-full bg-ink text-paper px-4 py-2.5 rounded-full text-sm font-medium hover:bg-accent transition mb-4 flex-shrink-0"
      >
        + New chat
      </button>
      <div className="flex-1 overflow-y-auto space-y-1">
        <div className="text-[11px] font-mono text-ink-mute uppercase tracking-widest mb-2 px-1">
          History
        </div>
        {chats.length === 0 ? (
          <div className="text-xs text-ink-mute/60 italic px-1 py-2">No conversations yet</div>
        ) : (
          chats.map((c) => (
            <div
              key={c.id}
              onClick={() => openChat(c.id)}
              className={`group flex items-center justify-between gap-2 px-3 py-2 rounded-xl cursor-pointer transition ${
                c.id === chatId ? "bg-accent/10 text-accent" : "hover:bg-bg-alt"
              }`}
            >
              <span className="text-sm truncate flex-1">{c.title}</span>
              <button
                onClick={(e) => deleteChat(e, c.id)}
                title="Delete"
                className="w-5 h-5 rounded-full text-ink-mute opacity-0 group-hover:opacity-100 hover:bg-accent hover:text-paper transition flex items-center justify-center text-[11px] leading-none flex-shrink-0"
              >
                ×
              </button>
            </div>
          ))
        )}
      </div>
    </>
  );

  const SourcesPanel = () => (
    <>
      <div className="flex items-center justify-between mb-3 flex-shrink-0">
        <span className="text-[11px] font-mono text-ink-mute uppercase tracking-widest">Sources</span>
        <span className="text-[11px] text-ink-soft">{selLectures.size + selRecs.size + selExams.size + selTuts.size}/{lectures.length + recordings.length + pastExams.length + tutorials.length}</span>
      </div>
      <div className="flex-1 overflow-y-auto space-y-4">
        {/* Lecture documents */}
        <div>
          <div className="flex items-center justify-between mb-1.5">
            <span className="text-[11px] font-mono text-ink-mute uppercase tracking-widest">Lectures</span>
            {lectures.length > 0 && (
              <button
                onClick={() => setSelLectures(selLectures.size === lectures.length ? new Set() : new Set(lectures.map((l) => l.id)))}
                className="text-[11px] text-accent hover:underline"
              >
                {selLectures.size === lectures.length ? "Clear" : "All"}
              </button>
            )}
          </div>
          {lectures.length === 0 ? (
            <div className="text-xs text-ink-mute/60 italic">None uploaded</div>
          ) : (
            <div className="space-y-1">
              {lectures.map((l) => (
                <button
                  key={l.id}
                  onClick={() => toggleSel(selLectures, setSelLectures, l.id)}
                  className={`w-full flex items-center gap-2 px-2.5 py-1.5 rounded-lg text-left transition ${
                    selLectures.has(l.id) ? "bg-sage/10 text-sage" : "text-ink-mute hover:bg-bg-alt"
                  }`}
                >
                  <span className={`w-3.5 h-3.5 rounded border flex-shrink-0 flex items-center justify-center text-[9px] ${
                    selLectures.has(l.id) ? "bg-sage border-sage text-paper" : "border-line"
                  }`}>{selLectures.has(l.id) ? "✓" : ""}</span>
                  <span className="flex-shrink-0">📄</span>
                  <span className="text-xs truncate">{l.title}</span>
                </button>
              ))}
            </div>
          )}
        </div>
        {/* Recordings */}
        <div>
          <div className="flex items-center justify-between mb-1.5">
            <span className="text-[11px] font-mono text-ink-mute uppercase tracking-widest">Recordings</span>
            {recordings.length > 0 && (
              <button
                onClick={() => setSelRecs(selRecs.size === recordings.length ? new Set() : new Set(recordings.map((r) => r.id)))}
                className="text-[11px] hover:underline"
                style={{ color: "#b8923a" }}
              >
                {selRecs.size === recordings.length ? "Clear" : "All"}
              </button>
            )}
          </div>
          {recordings.length === 0 ? (
            <div className="text-xs text-ink-mute/60 italic">None uploaded</div>
          ) : (
            <div className="space-y-1">
              {recordings.map((r) => (
                <button
                  key={r.id}
                  onClick={() => toggleSel(selRecs, setSelRecs, r.id)}
                  className="w-full flex items-center gap-2 px-2.5 py-1.5 rounded-lg text-left transition"
                  style={
                    selRecs.has(r.id)
                      ? { backgroundColor: "#b8923a1a", color: "#b8923a" }
                      : undefined
                  }
                >
                  <span
                    className="w-3.5 h-3.5 rounded border flex-shrink-0 flex items-center justify-center text-[9px]"
                    style={
                      selRecs.has(r.id)
                        ? { backgroundColor: "#b8923a", borderColor: "#b8923a", color: "#faf7f2" }
                        : { borderColor: "var(--line, #d9d2c5)" }
                    }
                  >
                    {selRecs.has(r.id) ? "✓" : ""}
                  </span>
                  <span className="flex-shrink-0">🎙️</span>
                  <span className={`text-xs truncate ${selRecs.has(r.id) ? "" : "text-ink-mute"}`}>{r.title}</span>
                </button>
              ))}
            </div>
          )}
        </div>
        {/* Past exams */}
        <div>
          <div className="flex items-center justify-between mb-1.5">
            <span className="text-[11px] font-mono text-ink-mute uppercase tracking-widest">Past exams</span>
            {pastExams.length > 0 && (
              <button
                onClick={() => setSelExams(selExams.size === pastExams.length ? new Set() : new Set(pastExams.map((x) => x.id)))}
                className="text-[11px] text-accent hover:underline"
              >
                {selExams.size === pastExams.length ? "Clear" : "All"}
              </button>
            )}
          </div>
          {pastExams.length === 0 ? (
            <div className="text-xs text-ink-mute/60 italic">None uploaded</div>
          ) : (
            <div className="space-y-1">
              {pastExams.map((x) => (
                <button
                  key={x.id}
                  onClick={() => toggleSel(selExams, setSelExams, x.id)}
                  className={`w-full flex items-center gap-2 px-2.5 py-1.5 rounded-lg text-left transition ${
                    selExams.has(x.id) ? "bg-accent/10 text-accent" : "text-ink-mute hover:bg-bg-alt"
                  }`}
                >
                  <span className={`w-3.5 h-3.5 rounded border flex-shrink-0 flex items-center justify-center text-[9px] ${
                    selExams.has(x.id) ? "bg-accent border-accent text-paper" : "border-line"
                  }`}>{selExams.has(x.id) ? "✓" : ""}</span>
                  <span className="flex-shrink-0">📋</span>
                  <span className="text-xs truncate">{x.title}</span>
                </button>
              ))}
            </div>
          )}
        </div>
        {/* Tutorials */}
        <div>
          <div className="flex items-center justify-between mb-1.5">
            <span className="text-[11px] font-mono text-ink-mute uppercase tracking-widest">Tutorials</span>
            {tutorials.length > 0 && (
              <button
                onClick={() => setSelTuts(selTuts.size === tutorials.length ? new Set() : new Set(tutorials.map((x) => x.id)))}
                className="text-[11px] text-accent hover:underline"
              >
                {selTuts.size === tutorials.length ? "Clear" : "All"}
              </button>
            )}
          </div>
          {tutorials.length === 0 ? (
            <div className="text-xs text-ink-mute/60 italic">None uploaded</div>
          ) : (
            <div className="space-y-1">
              {tutorials.map((x) => (
                <button
                  key={x.id}
                  onClick={() => toggleSel(selTuts, setSelTuts, x.id)}
                  className="w-full flex items-center gap-2 px-2.5 py-1.5 rounded-lg text-left transition"
                  style={
                    selTuts.has(x.id)
                      ? { backgroundColor: "#3f6f7d1a", color: "#3f6f7d" }
                      : undefined
                  }
                >
                  <span
                    className="w-3.5 h-3.5 rounded border flex-shrink-0 flex items-center justify-center text-[9px]"
                    style={
                      selTuts.has(x.id)
                        ? { backgroundColor: "#3f6f7d", borderColor: "#3f6f7d", color: "#faf7f2" }
                        : { borderColor: "var(--line, #d9d2c5)" }
                    }
                  >
                    {selTuts.has(x.id) ? "✓" : ""}
                  </span>
                  <span className="flex-shrink-0">✏️</span>
                  <span className={`text-xs truncate ${selTuts.has(x.id) ? "" : "text-ink-mute"}`}>{x.title}</span>
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
    </>
  );

  return (
    <>
      {/* Hide the top nav entirely while in fullscreen so the chat truly fills
          the viewport and the corner toggle isn't covered by it. */}
      {!fullscreen && <Navbar />}
      <div className={fullscreen ? "flex" : "pt-20 flex"}>
        {!fullscreen && <Sidebar courses={allCourses} />}
        <main
          className={
            fullscreen
              ? "flex-1 w-full flex flex-col"
              : "flex-1 w-full px-4 md:px-8 lg:px-10 pb-6 max-w-[1500px] mx-auto flex flex-col"
          }
          style={fullscreen ? { height: "100vh" } : { height: "calc(100vh - 5rem)" }}
        >
          {/* Breadcrumb — hidden in fullscreen so the chat is truly distraction-free */}
          {!fullscreen && (
            <div className="my-6 flex items-center gap-2 text-xs font-mono flex-shrink-0">
              <Link href="/dashboard" className="text-ink-soft hover:text-accent transition">Dashboard</Link>
              <span className="text-ink-mute">›</span>
              <Link href={`/course/${courseId}`} className="text-ink-soft hover:text-accent transition">{course.code}</Link>
              <span className="text-ink-mute">›</span>
              <span className="text-ink">AI Coach</span>
            </div>
          )}

          <div
            className={
              fullscreen
                ? "fixed inset-0 z-[100] bg-paper flex overflow-hidden"
                : "bg-paper border border-line rounded-3xl flex-1 flex overflow-hidden shadow-soft"
            }
          >
            {/* History sidebar (desktop) */}
            <aside className="w-60 bg-bg/40 border-r border-line p-4 hidden md:flex flex-col flex-shrink-0">
              <HistoryList />
            </aside>

            {/* Chat column */}
            <div className="flex-1 flex flex-col min-w-0">
              {/* Header */}
              <div className="border-b border-line px-6 py-4 flex items-center gap-3 flex-shrink-0">
                <button
                  onClick={() => setHistoryOpen((o) => !o)}
                  className="md:hidden w-8 h-8 rounded-full border border-line flex items-center justify-center text-sm"
                  title="History"
                >
                  ☰
                </button>
                <div className="w-9 h-9 rounded-full bg-accent/10 flex items-center justify-center text-lg">🎓</div>
                <div className="flex-1 min-w-0">
                  <div className="font-serif text-lg font-medium tracking-tight">AI Coach</div>
                  <div className="text-xs text-ink-mute font-mono truncate">{course.code} · grounded in your course materials</div>
                </div>
                <button
                  onClick={() => setSourcesOpen((o) => !o)}
                  className="lg:hidden text-xs border border-line rounded-full px-3 py-1.5 hover:bg-bg-alt transition"
                  title="Sources"
                >
                  Sources
                </button>
                <button
                  onClick={() => setFullscreen((f) => !f)}
                  className="w-8 h-8 rounded-full border border-line flex items-center justify-center text-ink-soft hover:bg-bg-alt hover:text-ink transition flex-shrink-0"
                  title={fullscreen ? "Exit fullscreen (Esc)" : "Expand to fullscreen"}
                  aria-label={fullscreen ? "Exit fullscreen" : "Enter fullscreen"}
                >
                  {fullscreen ? (
                    // collapse icon (arrows pointing inward)
                    <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M10 2v4h4" />
                      <path d="M14 2l-4 4" />
                      <path d="M6 14v-4H2" />
                      <path d="M2 14l4-4" />
                    </svg>
                  ) : (
                    // expand icon (arrows pointing outward)
                    <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M3 7V3h4" />
                      <path d="M3 3l4 4" />
                      <path d="M13 9v4h-4" />
                      <path d="M13 13l-4-4" />
                    </svg>
                  )}
                </button>
                <button
                  onClick={newChat}
                  className="md:hidden text-xs border border-line rounded-full px-3 py-1.5 hover:bg-bg-alt transition"
                >
                  New
                </button>
              </div>

              {/* Mobile history dropdown */}
              {historyOpen && (
                <div className="md:hidden border-b border-line p-4 max-h-60 overflow-y-auto flex flex-col">
                  <HistoryList />
                </div>
              )}

              {/* Mobile sources dropdown */}
              {sourcesOpen && (
                <div className="lg:hidden border-b border-line p-4 max-h-64 overflow-y-auto flex flex-col">
                  <SourcesPanel />
                </div>
              )}

              {/* Messages */}
              <div ref={scrollRef} className="flex-1 overflow-y-auto px-4 md:px-8 py-8">
                {messages.length === 0 ? (
                  <div className="h-full flex flex-col items-center justify-center text-center px-4">
                    <div className="w-16 h-16 rounded-2xl bg-accent/10 flex items-center justify-center text-4xl mb-5">
                      🎓
                    </div>
                    <h2 className="font-serif text-3xl font-medium tracking-tight mb-3">
                      Ask me anything about {course.code}
                    </h2>
                    <p className="text-ink-soft text-sm mb-8 max-w-md leading-relaxed">
                      I draw on your lecture documents, recordings, past exams, and tutorials
                      to help you understand the material and prepare.
                    </p>
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5 w-full max-w-lg">
                      {SUGGESTIONS.map((s) => (
                        <button
                          key={s}
                          onClick={() => send(s)}
                          className="text-sm text-left border border-line rounded-2xl px-4 py-3 hover:bg-bg-alt hover:border-accent hover:-translate-y-0.5 transition-all"
                        >
                          {s}
                        </button>
                      ))}
                    </div>
                  </div>
                ) : (
                  <div
                    className={`${
                      fullscreen ? "max-w-[1150px]" : "max-w-3xl"
                    } mx-auto space-y-6`}
                  >
                    {messages.map((m, i) => (
                      <div key={i} className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}>
                        <div
                          className={`rounded-2xl px-5 py-3.5 text-sm leading-relaxed ${
                            m.role === "user"
                              ? "max-w-[85%] bg-ink text-paper whitespace-pre-wrap"
                              : "max-w-[90%] bg-bg border border-line text-ink"
                          }`}
                        >
                          {m.role === "user" ? (
                            m.content
                          ) : (
                            <ReactMarkdown remarkPlugins={[remarkGfm]} components={md}>
                              {m.content}
                            </ReactMarkdown>
                          )}
                        </div>
                      </div>
                    ))}
                    {thinking && (
                      <div className="flex justify-start">
                        <div className="bg-bg border border-line rounded-2xl px-5 py-4 flex items-center gap-1.5">
                          <span className="w-2 h-2 bg-ink-mute rounded-full animate-bounce" style={{ animationDelay: "0ms" }} />
                          <span className="w-2 h-2 bg-ink-mute rounded-full animate-bounce" style={{ animationDelay: "150ms" }} />
                          <span className="w-2 h-2 bg-ink-mute rounded-full animate-bounce" style={{ animationDelay: "300ms" }} />
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>

              {/* Input */}
              <div className="border-t border-line p-4 flex-shrink-0 bg-bg/30">
                <form
                  onSubmit={(e) => { e.preventDefault(); send(input); }}
                  className={`${
                    fullscreen ? "max-w-[1150px]" : "max-w-3xl"
                  } mx-auto flex items-end gap-2.5 bg-paper border border-line rounded-3xl px-2 py-2 focus-within:border-accent transition shadow-soft`}
                >
                  <textarea
                    value={input}
                    onChange={(e) => setInput(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(input); }
                    }}
                    placeholder="Ask about a concept, request a quiz, get exam tips…"
                    rows={1}
                    className="flex-1 px-3 py-2.5 bg-transparent text-sm focus:outline-none resize-none max-h-40 leading-relaxed"
                  />
                  <button
                    type="submit"
                    disabled={!input.trim() || thinking}
                    className="bg-ink text-paper px-5 py-2.5 rounded-2xl text-sm font-medium hover:bg-accent transition disabled:opacity-40 disabled:cursor-not-allowed flex-shrink-0"
                  >
                    Send
                  </button>
                </form>
                <p
                  className={`${
                    fullscreen ? "max-w-[1150px]" : "max-w-3xl"
                  } mx-auto text-[11px] text-ink-mute font-mono mt-2 px-2 text-center`}
                >
                  Enter to send · Shift + Enter for a new line
                </p>
              </div>
            </div>

            {/* Sources sidebar (desktop) */}
            <aside className="w-64 bg-bg/40 border-l border-line p-4 hidden lg:flex flex-col flex-shrink-0">
              <SourcesPanel />
            </aside>
          </div>
        </main>
      </div>
    </>
  );
}
