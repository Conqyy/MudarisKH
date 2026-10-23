"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter, useParams } from "next/navigation";
import Link from "next/link";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import SourceCitation, { SourceRef, validatedSourceRefs } from "@/components/SourceCitation";
import SupportingCitation from "@/components/SupportingCitation";
import { SupportingRef, validatedSupportingRefs } from "@/lib/supporting-materials";
import { citationsForPath, firstSupportingBlocker, retainSelectedRows, supportingPresentation } from "@/lib/supporting-materials";
import SupportingSelectionNotice from "@/components/SupportingSelectionNotice";
import AppShell from "@/components/AppShell";
import Icon from "@/components/Icon";
import { StudyBusy, StudySourceStatus } from "@/components/StudyWorkspace";
import { CourseFoundationGate } from "@/components/CourseFoundationGate";
import { useDialog } from "@/lib/use-dialog";
import { useCourseFoundation } from "@/hooks/useCourseFoundation";
import { useAuth } from "@/lib/auth-context";
import { useLang } from "@/lib/i18n";
import { getCourse, getUserCourses, Course } from "@/lib/firestore-helpers";
import { ordered } from "@/lib/ordering";

import { apiFetch, apiJson } from "@/lib/api";
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
  h1: (p: any) => <h1 dir="auto" className="font-sans text-lg font-medium mt-4 mb-1.5 first:mt-0" {...p} />,
  h2: (p: any) => <h2 dir="auto" className="font-sans text-base font-medium mt-4 mb-1.5 first:mt-0" {...p} />,
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
  sourceRefs?: SourceRef[];
  supportingSourceRefs?: SupportingRef[];
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
  status?: string; legacy?: boolean; stale?: boolean; sourceRevision?: string | null; reportRevision?: string | null; jobId?: string | null; sourceType?: string;
}

const SUGGESTIONS = [
  "What topics should I focus on for the exam?",
  "Explain the hardest concept simply.",
  "Quiz me with 3 questions.",
  "Summarize the key definitions.",
];

export default function TutorPage() {
  const { user } = useAuth();
  const params = useParams();
  return <TutorPageContent key={JSON.stringify([user?.uid, params.id])} />;
}

function TutorPageContent() {
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
  const [pageLoading, setPageLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const loadRequest = useRef<AbortController | null>(null);
  const loadDataRef = useRef<(() => Promise<void>) | null>(null);
  useEffect(() => () => { loadRequest.current?.abort(); }, [courseId, user?.uid]);

  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [chatId, setChatId] = useState("");
  const [chats, setChats] = useState<ChatSummary[]>([]);
  const [input, setInput] = useState("");
  const [thinking, setThinking] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [historyCollapsed, setHistoryCollapsed] = useState(false);
  const conversationVersion = useRef(0);
  const conversationRequest = useRef<AbortController | null>(null);
  const historyRequest = useRef<AbortController | null>(null);
  const pendingTurn = useRef<{ messages: ChatMessage[]; content: string } | null>(null);
  const activeChatId = useRef("");
  const [chatError, setChatError] = useState("");
  const [sendError, setSendError] = useState("");
  const [openingChat, setOpeningChat] = useState(false);
  const invalidateConversation = (restoreDraft = false) => {
    conversationVersion.current += 1;
    conversationRequest.current?.abort();
    conversationRequest.current = null;
    if (restoreDraft && pendingTurn.current) {
      setMessages(pendingTurn.current.messages);
      setInput(pendingTurn.current.content);
    }
    pendingTurn.current = null;
    setThinking(false);
    setOpeningChat(false);
    setSendError("");
  };
  useEffect(() => () => { conversationVersion.current += 1; conversationRequest.current?.abort(); historyRequest.current?.abort(); }, [courseId, user?.uid]);
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
  const initialSupportingSelection = useRef("");
  const selectionRef = useRef({ recs: selRecs, exams: selExams, tuts: selTuts });
  selectionRef.current = { recs: selRecs, exams: selExams, tuts: selTuts };
  const asRows = (rows: ResourceItem[]) => rows.map(row => ({ ...row, status: row.status || "legacy" }));
  const supportingBlocker = firstSupportingBlocker([{ selected: selRecs, rows: asRows(recordings) }, { selected: selExams, rows: asRows(pastExams) }, { selected: selTuts, rows: asRows(tutorials) }]);
  const deselectBlocking = (id: string) => {
    setSelRecs(previous => new Set([...previous].filter(value => value !== id)));
    setSelExams(previous => new Set([...previous].filter(value => value !== id)));
    setSelTuts(previous => new Set([...previous].filter(value => value !== id)));
  };
  const [sourcesOpen, setSourcesOpen] = useState(false);
  const sourceDialogRef = useDialog(() => setSourcesOpen(false), sourcesOpen);
  const historyDialogRef = useDialog(() => setHistoryOpen(false), historyOpen);

  // Fullscreen / focus mode for the chat
  const [fullscreen, setFullscreen] = useState(false);

  useEffect(() => {
    if (foundationLoading || foundationError || foundationReady) return;
    if (pendingTurn.current) invalidateConversation(true);
    setFullscreen(false);
  }, [foundationReady, foundationLoading, foundationError]);

  // Press Esc to leave fullscreen
  useEffect(() => {
    if (!fullscreen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !e.defaultPrevented) setFullscreen(false);
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
    if (user && courseId) loadDataRef.current?.();
  }, [user, courseId]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, thinking]);

  const loadChats = async (signal?: AbortSignal) => {
    if (!user) return;
    historyRequest.current?.abort();
    const controller = new AbortController();
    historyRequest.current = controller;
    const activeSignal = signal || controller.signal;
    try {
      const res = await apiFetch(`${API_URL}/api/tutor/chats/${user.uid}/${courseId}`, { signal: activeSignal });
      if (!res.ok) throw new Error("Could not load conversations.");
      const data = await res.json();
      if (activeSignal.aborted || controller.signal.aborted) return;
      setChatError("");
      setChats(data.chats || []);
    } catch {
      if (!activeSignal.aborted && !controller.signal.aborted) setChatError(t("Could not load conversations."));
    }
  };

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
      await loadChats(controller.signal);
      if (controller.signal.aborted) return;

      // Load selectable sources (completed lectures/recordings + past exams + tutorials)
      const [docsRes, audioRes, histRes, tutRes] = await Promise.all([
        apiJson(`${API_URL}/api/documents/${courseId}`, { signal: controller.signal }),
        apiJson(`${API_URL}/api/audio/${courseId}`, { signal: controller.signal }),
        apiJson(`${API_URL}/api/historical-exams/${courseId}`, { signal: controller.signal }),
        apiJson(`${API_URL}/api/tutorials/${courseId}`, { signal: controller.signal }),
      ]);
      if (controller.signal.aborted) return;
      const docsList = ordered(
        (docsRes.documents || []).filter((d: any) => d.status === "completed"),
        courseData?.documentOrder,
        courseData?.titleOverrides
      );
      const audioList = ordered(
        audioRes.audio_recordings || [],
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
        status: a.status, legacy: a.legacy, stale: a.stale, sourceRevision: a.sourceRevision, reportRevision: a.reportRevision, jobId: a.jobId, sourceType: a.sourceType,
      }));
      const exams: ResourceItem[] = ordered(
        histRes.historical_exams || [],
        courseData?.examOrder,
        courseData?.titleOverrides
      ).map((h: any) => ({ id: h.id, title: h.title, kind: "exam" as const, status: h.status, legacy: h.legacy, stale: h.stale, sourceRevision: h.sourceRevision, reportRevision: h.reportRevision, jobId: h.jobId }));
      const tuts: ResourceItem[] = ordered(
        tutRes.tutorials || [],
        courseData?.tutorialOrder,
        courseData?.titleOverrides
      ).map((t: any) => ({ id: t.id, title: t.title, kind: "tutorial" as const, status: t.status, legacy: t.legacy, stale: t.stale, sourceRevision: t.sourceRevision, reportRevision: t.reportRevision, jobId: t.jobId }));
      setLectures(lec);
      setRecordings(previous => retainSelectedRows(recs.map(row => ({ ...row, status: row.status || "legacy" })), previous.map(row => ({ ...row, status: row.status || "legacy" })), selectionRef.current.recs));
      setPastExams(previous => retainSelectedRows(exams.map(row => ({ ...row, status: row.status || "legacy" })), previous.map(row => ({ ...row, status: row.status || "legacy" })), selectionRef.current.exams));
      setTutorials(previous => retainSelectedRows(tuts.map(row => ({ ...row, status: row.status || "legacy" })), previous.map(row => ({ ...row, status: row.status || "legacy" })), selectionRef.current.tuts));
      setSelLectures(new Set(lec.map((x) => x.id)));
      if (initialSupportingSelection.current !== `${user.uid}:${courseId}`) {
        initialSupportingSelection.current = `${user.uid}:${courseId}`;
        setSelRecs(new Set(recs.filter(row => supportingPresentation({ ...row, status: row.status || "legacy" }) === "usable").map(row => row.id)));
        setSelExams(new Set(exams.filter(row => supportingPresentation({ ...row, status: row.status || "legacy" }) === "usable").map(row => row.id)));
        setSelTuts(new Set(tuts.filter(row => supportingPresentation({ ...row, status: row.status || "legacy" }) === "usable").map(row => row.id)));
      }
    } catch (error: any) {
      if (!controller.signal.aborted) setLoadError(error.message || "Could not load course data.");
    } finally {
      if (!controller.signal.aborted) setPageLoading(false);
    }
  };

  loadDataRef.current = loadData;
  const toggleSel = (set: Set<string>, setter: (s: Set<string>) => void, id: string) => {
    const next = new Set(set);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setter(next);
  };

  const newChat = () => {
    invalidateConversation();
    activeChatId.current = "";
    setMessages([]);
    setChatId("");
    setInput("");
    setHistoryOpen(false);
  };

  const openChat = async (id: string) => {
    invalidateConversation();
    const version = conversationVersion.current;
    const controller = new AbortController();
    conversationRequest.current = controller;
    setOpeningChat(true);
    setHistoryOpen(false);
    try {
      const data = await apiJson(API_URL + "/api/tutor/chat/" + id, { signal: controller.signal });
      if (version !== conversationVersion.current) return;
      const savedMessages = data.chat?.messages || [];
      const turns = Array.isArray(data.chat?.sourceTurns) ? data.chat.sourceTurns : [];
      setMessages(savedMessages.map((message: ChatMessage, index: number) => {
        const turn = turns.find((entry: { messageIndex?: number }) => entry.messageIndex === index);
        const citations = citationsForPath(turn?.provenance, "/reply", turn);
        return { role: message.role, content: message.content, ...(message.role === "assistant" ? { sourceRefs: validatedSourceRefs(citations.sourceRefs), supportingSourceRefs: validatedSupportingRefs(citations.supportingSourceRefs) } : {}) };
      }));
      activeChatId.current = id;
      setChatId(id);
    } catch {
      if (version === conversationVersion.current) alert(t("Could not open this conversation."));
    } finally {
      if (version === conversationVersion.current) { setOpeningChat(false); conversationRequest.current = null; }
    }
  };

  const deleteChat = async (e: React.MouseEvent, id: string) => {
    e.stopPropagation();
    if (!confirm(t("Delete this conversation?"))) return;
    if (id === activeChatId.current) invalidateConversation(true);
    try {
      const res = await apiFetch(`${API_URL}/api/tutor/chat/${id}`, { method: "DELETE" });
      if (!res.ok) throw new Error("Delete failed");
      setChats((prev) => prev.filter((c) => c.id !== id));
      if (id === activeChatId.current) newChat();
    } catch {
      alert(t("Failed to delete."));
    }
  };

  const send = async (text: string) => {
    const content = text.trim();
    if (!content || thinking || openingChat || conversationRequest.current || !user || !foundationReadyRef.current) return;
    if (supportingBlocker) { setSendError(t("Selected material is unavailable. Retry or deselect it.")); return; }
    const version = conversationVersion.current;
    const controller = new AbortController();
    conversationRequest.current = controller;
    pendingTurn.current = { messages, content };
    const next = [...messages, { role: "user" as const, content }];
    setMessages(next);
    setInput("");
    setThinking(true);
    setSendError("");
    try {
      const res = await apiFetch(`${API_URL}/api/tutor/chat`, {
        method: "POST",
        signal: controller.signal,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          user_id: user.uid,
          course_id: courseId,
          chat_id: chatId,
          messages: next.map(({ role, content }) => ({ role, content })),
          document_ids: Array.from(selLectures),
          recording_ids: Array.from(selRecs),
          historical_exam_ids: Array.from(selExams),
          tutorial_ids: Array.from(selTuts),
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => null);
        if (res.status === 409) {
          if (controller.signal.aborted || version !== conversationVersion.current) return;
          const currentFoundation = await refreshFoundation();
          if (currentFoundation?.ready) {
            setMessages(messages);
            setInput(content);
            setSendError(t("This conversation changed. Reopen it from History, then send your draft again."));
          }
          return;
        }
        throw new Error(err?.detail || `Tutor error (${res.status})`);
      }
      const data = await res.json();
      if (version !== conversationVersion.current || controller.signal.aborted || (!foundationReadyRef.current && !foundationUnknownRef.current)) return;
      setMessages((prev) => [...prev, { role: "assistant", content: data.reply || "", sourceRefs: validatedSourceRefs(data.sourceRefs), supportingSourceRefs: validatedSupportingRefs(data.supportingSourceRefs) }]);
      if (data.chat_id) { activeChatId.current = data.chat_id; setChatId(data.chat_id); }
      loadChats();
    } catch (e: any) {
      if (version !== conversationVersion.current) return;
      setMessages(messages);
      setInput(content);
      setSendError(e.message || t("Something went wrong. Please retry."));
    } finally {
      if (version === conversationVersion.current) { conversationRequest.current = null; pendingTurn.current = null; setThinking(false); }
    }
  };

  if (loadError && !pageLoading) return <AppShell courses={allCourses} course={course} courseId={courseId} activeTab="tutor"><main className="workspace-main study-workspace"><div className="ui-panel study-busy" role="alert"><Icon name="alert" size={28} /><p>{loadError}</p><button onClick={() => loadData()} className="ui-button secondary">{t("Retry loading")}</button></div></main></AppShell>;

  if (loading || pageLoading) {
    return (
      <AppShell courses={allCourses} course={course} courseId={courseId} activeTab="tutor"><main className="workspace-main study-workspace"><StudyBusy loading title="Loading…" /></main></AppShell>
    );
  }
  if (!user) return null;
  if (!course) {
    return (
      <AppShell courses={allCourses} course={course} courseId={courseId} activeTab="tutor"><main className="workspace-main study-workspace"><div className="ui-panel study-busy">
          <div className="text-center">
            <h1 className="font-sans text-3xl font-medium mb-3">{t("Course not found")}</h1>
            <Link href="/dashboard" className="inline-block bg-ink text-paper px-6 py-3 rounded-full text-sm font-medium hover:bg-accent transition">
              {t("Back to Dashboard")}
            </Link>
          </div>
        </div></main></AppShell>
    );
  }

  if (!foundationReady) {
    return (
      <AppShell courses={allCourses} course={course} courseId={courseId} activeTab="tutor"><main className="workspace-main study-workspace">
            <Link href={`/course/${courseId}`} className="inline-block mb-6 text-sm text-ink-soft hover:text-accent transition">
              ← {t("Back to course")}
            </Link>
            <CourseFoundationGate courseId={courseId} foundation={foundation} loading={foundationLoading} error={foundationError} onRetry={refreshFoundation} />
          </main></AppShell>
    );
  }

  const HistoryList = () => (
    <>
      <button
        onClick={newChat}
        className="ui-button primary w-full mb-4"
      >
        <Icon name="plus" size={16} /> {t("New chat")}
      </button>
      <div className="flex-1 overflow-y-auto space-y-1">
        <div className="text-[11px] tabular-nums text-ink-mute  mb-2 px-1">
          {t("History")}
        </div>
        {chatError ? <div role="alert" className="text-xs text-accent">{chatError}<button onClick={() => loadChats()} className="block underline mt-2">{t("Retry history")}</button></div> : chats.length === 0 ? (
          <div className="text-xs text-ink-mute/60 italic px-1 py-2">{t("No conversations yet")}</div>
        ) : (
          chats.map((c) => (
            <div
              key={c.id}
              role="button" tabIndex={0}
              onKeyDown={(e) => { if (e.target === e.currentTarget && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); openChat(c.id); } }}
              onClick={() => openChat(c.id)}
              className={`group flex items-center justify-between gap-2 px-3 py-2 rounded-xl cursor-pointer transition ${
                c.id === chatId ? "bg-accent/10 text-accent" : "hover:bg-bg-alt"
              }`}
            >
              <span className="text-sm truncate flex-1">{c.title}</span>
              <button
                onClick={(e) => deleteChat(e, c.id)}
                title={t("Delete")} aria-label={t("Delete") + " " + c.title}
                className="icon-button danger flex-shrink-0"
              >
                <Icon name="trash" size={15} />
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
        <span className="text-[11px] tabular-nums text-ink-mute ">{t("Sources")}</span>
        <span className="text-[11px] text-ink-soft">{selLectures.size + selRecs.size + selExams.size + selTuts.size}/{lectures.length + recordings.length + pastExams.length + tutorials.length}</span>
      </div>
      <div className="flex-1 overflow-y-auto space-y-4">
        {/* Lecture documents */}
        <div>
          <div className="flex items-center justify-between mb-1.5">
            <span className="text-[11px] tabular-nums text-ink-mute ">{t("Lectures")}</span>
            {lectures.length > 0 && (
              <button
                onClick={() => setSelLectures(selLectures.size === lectures.length ? new Set() : new Set(lectures.map((l) => l.id)))}
                className="text-[11px] text-accent hover:underline"
              >
                {selLectures.size === lectures.length ? t("Clear") : t("All")}
              </button>
            )}
          </div>
          {lectures.length === 0 ? (
            <div className="text-xs text-ink-mute/60 italic">{t("None uploaded")}</div>
          ) : (
            <div className="space-y-1">
              {lectures.map((l) => (
                <button
                  key={l.id}
                  aria-pressed={selLectures.has(l.id)}
                  onClick={() => toggleSel(selLectures, setSelLectures, l.id)}
                  className={`tutor-source-button w-full flex items-center gap-2 px-2.5 py-1.5 rounded-lg transition-colors ${
                    selLectures.has(l.id) ? "bg-sage/10 text-sage" : "text-ink-mute hover:bg-bg-alt"
                  }`}
                >
                  <span className={`w-3.5 h-3.5 rounded border flex-shrink-0 flex items-center justify-center text-[9px] ${
                    selLectures.has(l.id) ? "bg-sage border-sage text-paper" : "border-line"
                  }`}>{selLectures.has(l.id) ? "✓" : ""}</span>
                  <span className="flex-shrink-0"><Icon name="file" size={20} /></span>
                  <span className="text-xs truncate">{l.title}</span>
                </button>
              ))}
            </div>
          )}
        </div>
        {/* Recordings */}
        <div>
          <div className="flex items-center justify-between mb-1.5">
            <span className="text-[11px] tabular-nums text-ink-mute ">{t("Recordings")}</span>
            {recordings.length > 0 && (
              <button
                onClick={() => setSelRecs(selRecs.size === recordings.length ? new Set() : new Set(recordings.map((r) => r.id)))}
                className="text-[11px] hover:underline"
                style={{ color: "var(--accent)" }}
              >
                {selRecs.size === recordings.length ? t("Clear") : t("All")}
              </button>
            )}
          </div>
          {recordings.length === 0 ? (
            <div className="text-xs text-ink-mute/60 italic">{t("None uploaded")}</div>
          ) : (
            <div className="space-y-1">
              {recordings.map((r) => (
                <button
                  key={r.id}
                  aria-pressed={selRecs.has(r.id)}
                  onClick={() => toggleSel(selRecs, setSelRecs, r.id)}
                  className="tutor-source-button w-full flex items-center gap-2 px-2.5 py-1.5 rounded-lg transition-colors"
                >
                  <span
                    className="w-3.5 h-3.5 rounded border flex-shrink-0 flex items-center justify-center text-[9px]"
                    style={{ borderColor: "var(--control-border)", color: "var(--accent)" }}
                  >
                    {selRecs.has(r.id) ? "✓" : ""}
                  </span>
                  <span className="flex-shrink-0"><Icon name="layers" size={18} /></span>
                  <span className="flex-1 min-w-0"><span className="text-xs">{r.title}</span><StudySourceStatus row={{ ...r, status: r.status || "legacy" }} /></span>
                </button>
              ))}
            </div>
          )}
        </div>
        {/* Past exams */}
        <div>
          <div className="flex items-center justify-between mb-1.5">
            <span className="text-[11px] tabular-nums text-ink-mute ">{t("Past exams")}</span>
            {pastExams.length > 0 && (
              <button
                onClick={() => setSelExams(selExams.size === pastExams.length ? new Set() : new Set(pastExams.map((x) => x.id)))}
                className="text-[11px] text-accent hover:underline"
              >
                {selExams.size === pastExams.length ? t("Clear") : t("All")}
              </button>
            )}
          </div>
          {pastExams.length === 0 ? (
            <div className="text-xs text-ink-mute/60 italic">{t("None uploaded")}</div>
          ) : (
            <div className="space-y-1">
              {pastExams.map((x) => (
                <button
                  key={x.id}
                  aria-pressed={selExams.has(x.id)}
                  onClick={() => toggleSel(selExams, setSelExams, x.id)}
                  className={`tutor-source-button w-full flex items-center gap-2 px-2.5 py-1.5 rounded-lg transition-colors ${
                    selExams.has(x.id) ? "bg-accent/10 text-accent" : "text-ink-mute hover:bg-bg-alt"
                  }`}
                >
                  <span className={`w-3.5 h-3.5 rounded border flex-shrink-0 flex items-center justify-center text-[9px] ${
                    selExams.has(x.id) ? "bg-accent border-accent text-paper" : "border-line"
                  }`}>{selExams.has(x.id) ? "✓" : ""}</span>
                  <span className="flex-shrink-0"><Icon name="exam" size={18} /></span>
                  <span className="flex-1 min-w-0"><span className="text-xs">{x.title}</span><StudySourceStatus row={{ ...x, status: x.status || "legacy" }} /></span>
                </button>
              ))}
            </div>
          )}
        </div>
        {/* Tutorials */}
        <div>
          <div className="flex items-center justify-between mb-1.5">
            <span className="text-[11px] tabular-nums text-ink-mute ">{t("Tutorials")}</span>
            {tutorials.length > 0 && (
              <button
                onClick={() => setSelTuts(selTuts.size === tutorials.length ? new Set() : new Set(tutorials.map((x) => x.id)))}
                className="text-[11px] text-accent hover:underline"
              >
                {selTuts.size === tutorials.length ? t("Clear") : t("All")}
              </button>
            )}
          </div>
          {tutorials.length === 0 ? (
            <div className="text-xs text-ink-mute/60 italic">{t("None uploaded")}</div>
          ) : (
            <div className="space-y-1">
              {tutorials.map((x) => (
                <button
                  key={x.id}
                  aria-pressed={selTuts.has(x.id)}
                  onClick={() => toggleSel(selTuts, setSelTuts, x.id)}
                  className="tutor-source-button w-full flex items-center gap-2 px-2.5 py-1.5 rounded-lg transition-colors"
                >
                  <span
                    className="w-3.5 h-3.5 rounded border flex-shrink-0 flex items-center justify-center text-[9px]"
                    style={{ borderColor: "var(--control-border)", color: "var(--accent)" }}
                  >
                    {selTuts.has(x.id) ? "✓" : ""}
                  </span>
                  <span className="flex-shrink-0"><Icon name="edit" size={18} /></span>
                  <span className="flex-1 min-w-0"><span className="text-xs">{x.title}</span><StudySourceStatus row={{ ...x, status: x.status || "legacy" }} /></span>
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
    </>
  );

  const workspace = (
    <main className={`workspace-main study-workspace tutor-workspace ${fullscreen ? "tutor-fullscreen" : ""}`}>
          <div className={fullscreen ? "fixed inset-0 z-[100] bg-paper flex overflow-hidden study-workspace" : "tutor-frame"}>
            {/* History sidebar (desktop) */}
            <aside className={`tutor-history flex-col ${historyCollapsed ? "hidden" : "hidden md:flex"}`}>
              {HistoryList()}
            </aside>

            {/* Chat column */}
            <div className="flex-1 flex flex-col min-w-0">
              {sendError && <div role="alert" className="p-3 text-sm text-accent border-b border-line">{sendError}</div>}
              {openingChat && <p role="status" className="p-3 text-sm">{t("Opening conversation...")}</p>}
              {/* Header */}
              <div className="tutor-header border-b border-line px-5 py-4 flex items-center gap-3 flex-shrink-0">
                <button
                  onClick={() => { setSourcesOpen(false); setHistoryOpen((o) => !o); }}
                  className="icon-button md:hidden"
                  title={t("History")} aria-label={t("History")} aria-expanded={historyOpen}
                >
                  <Icon name="menu" size={18} />
                </button>
                <button type="button" className="icon-button hidden md:flex" aria-label={t("Toggle chat history")} aria-expanded={!historyCollapsed} onClick={() => setHistoryCollapsed(value => !value)}><Icon name="history" size={18} /></button>
                <div className="w-9 h-9 rounded-full bg-accent/10 flex items-center justify-center text-lg"><Icon name="chat" size={24} /></div>
                <div className="tutor-title flex-1 min-w-0">
                  <h1 className="text-base font-semibold">{t("AI Tutor")}</h1>
                  <div className="text-xs text-ink-mute tabular-nums truncate">{course.code} · {t("grounded in your course materials")}</div>
                </div>
                <button
                  onClick={() => { setHistoryOpen(false); setSourcesOpen((o) => !o); }}
                  className="ui-button secondary tutor-source-trigger" aria-label={t("Sources")} aria-expanded={sourcesOpen}
                  title={t("Sources")}
                >
                  <Icon name="layers" size={16} /> {t("Sources")} <span className="study-count">{selLectures.size + selRecs.size + selExams.size + selTuts.size}</span>
                </button>
                <button
                  onClick={() => setFullscreen((f) => !f)}
                  className="icon-button"
                  title={t(fullscreen ? "Exit fullscreen (Esc)" : "Expand to fullscreen")}
                  aria-label={t(fullscreen ? "Exit fullscreen" : "Enter fullscreen")}
                >
                  <Icon name={fullscreen ? "minimize" : "fullscreen"} size={18} />
                </button>
                <button
                  onClick={newChat}
                  className="md:hidden text-xs border border-line rounded-full px-3 py-1.5 hover:bg-bg-alt transition"
                >
                  {t("New")}
                </button>
              </div>

              {/* Mobile history dropdown */}
              {historyOpen && (
                <div className="tutor-overlay" onClick={() => setHistoryOpen(false)}><div ref={historyDialogRef} role="dialog" aria-modal="true" aria-label={t("History")} tabIndex={-1} className="tutor-context-panel" onClick={event => event.stopPropagation()}><div className="flex justify-end mb-3"><button type="button" className="icon-button" aria-label={t("Close history")} onClick={() => setHistoryOpen(false)}><Icon name="close" size={18} /></button></div>{HistoryList()}</div></div>
              )}

              {/* Mobile sources dropdown */}
              {sourcesOpen && (
                <div className="tutor-overlay" onClick={() => setSourcesOpen(false)}><div ref={sourceDialogRef} role="dialog" aria-modal="true" aria-label={t("Sources")} tabIndex={-1} className="tutor-context-panel" onClick={event => event.stopPropagation()}><div className="flex justify-between items-center mb-3"><h2 className="section-heading">{t("Sources")}</h2><button type="button" className="icon-button" aria-label={t("Close sources")} onClick={() => setSourcesOpen(false)}><Icon name="close" size={18} /></button></div>{SourcesPanel()}</div></div>
              )}

              {/* Messages */}
              <div ref={scrollRef} className="flex-1 overflow-y-auto px-4 md:px-8 py-8">
                {messages.length === 0 ? (
                  <div className="h-full flex flex-col items-center justify-center text-center px-4">
                    <div className="w-16 h-16 rounded-2xl bg-accent/10 flex items-center justify-center text-4xl mb-5">
                      <Icon name="chat" size={24} />
                    </div>
                    <h2 className="font-sans text-3xl font-medium tracking-tight mb-3">
                      {t("Ask me anything about")} {course.code}
                    </h2>
                    <p className="text-ink-soft text-sm mb-8 max-w-md leading-relaxed">
                      {t("I draw on your lecture documents, recordings, past exams, and tutorials to help you understand the material and prepare.")}
                    </p>
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5 w-full max-w-lg">
                      {SUGGESTIONS.map((s) => (
                        <button
                          key={s}
                          onClick={() => send(s)}
                          className="text-sm text-left border border-line rounded-2xl px-4 py-3 hover:bg-bg-alt hover:border-accent  transition-colors"
                        >
                          {t(s)}
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
                          className={`tutor-message rounded-2xl px-5 py-3.5 text-sm leading-relaxed ${
                            m.role === "user"
                              ? "user-message max-w-[85%] whitespace-pre-wrap"
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
                          {m.role === "assistant" && <SourceCitation key={`${chatId}:${conversationVersion.current}:${i}`} courseId={courseId} sourceRefs={m.sourceRefs} />}
                          {m.role === "assistant" && <SupportingCitation key={`supporting:${chatId}:${conversationVersion.current}:${i}`} courseId={courseId} sourceRefs={m.supportingSourceRefs} />}
                        </div>
                      </div>
                    ))}
                    {thinking && (
                      <div className="flex justify-start">
                        <div className="bg-bg border border-line rounded-2xl px-5 py-4 flex items-center gap-1.5">
                          <Icon name="loader" size={18} className="animate-spin" /><span role="status">{t("Thinking…")}</span>
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>

              {/* Input */}
              <div className="tutor-composer border-t border-line p-4 flex-shrink-0 bg-bg/30">
      <SupportingSelectionNotice blocker={supportingBlocker} onDeselect={deselectBlocking} onRefresh={() => void loadDataRef.current?.()} />
                <form
                  onSubmit={(e) => { e.preventDefault(); send(input); }}
                  className={`${
                    fullscreen ? "max-w-[1150px]" : "max-w-3xl"
                  } mx-auto flex items-end gap-2.5 bg-paper border border-line rounded-3xl px-2 py-2 focus-within:border-accent transition shadow-soft`}
                >
                  <textarea
                    aria-label={t("Message your tutor")}
                    value={input}
                    onChange={(e) => setInput(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(input); }
                    }}
                    placeholder={t("Ask about a concept, request a quiz, get exam tips…")}
                    rows={1}
                    className="flex-1 px-3 py-2.5 bg-transparent text-sm focus:outline-none resize-none max-h-40 leading-relaxed"
                  />
                  <button
                    type="submit"
                    disabled={!input.trim() || thinking || openingChat || !foundationReady || !!supportingBlocker}
                    className="ui-button primary"
                  >
                    {t("Send")} <Icon name="arrow-right" size={16} />
                  </button>
                </form>
                <p
                  className={`${
                    fullscreen ? "max-w-[1150px]" : "max-w-3xl"
                  } mx-auto text-[11px] text-ink-mute tabular-nums mt-2 px-2 text-center`}
                >
                  {t("Enter to send · Shift + Enter for a new line")}
                </p>
              </div>
            </div>

          </div>
    </main>
  );
  return <AppShell courses={allCourses} course={course} courseId={courseId} activeTab="tutor" className={fullscreen ? "tutor-is-fullscreen" : ""} fullWidth>{workspace}</AppShell>;
}
