"use client";

import { useRouter } from "next/navigation";
import Navbar from "@/components/Navbar";
import { useAuth } from "@/lib/auth-context";
import { useLang } from "@/lib/i18n";

export default function Home() {
  const { user } = useAuth();
  const { t } = useLang();
  const router = useRouter();

  const handleCTA = () => {
    if (user) {
      router.push("/dashboard");
    } else {
      router.push("/signup");
    }
  };

  return (
    <>
      <Navbar />

      <main className="pt-20">
        {/* ============ HERO ============ */}
        <section className="px-6 md:px-12 pt-20 pb-32 max-w-7xl mx-auto relative">
          <h1 className="font-serif text-5xl md:text-7xl lg:text-8xl font-normal leading-[0.95] tracking-tight mb-8 max-w-5xl">
            {t("Your lectures,")}{" "}
            <em className="italic font-light text-accent">{t("finally")}</em>
            <br />
            <span className="relative inline-block">
              {t("unforgotten.")}
              <span className="absolute bottom-2 left-0 right-0 h-3 bg-accent-soft -z-10 opacity-60"></span>
            </span>
          </h1>

          <p className="text-lg md:text-xl text-ink-soft max-w-2xl leading-relaxed mb-12">
            {t("Mudaris turns your lecture documents, recordings, and past exams — in Arabic, English, or both — into structured summaries, full practice exams, smart flashcards, and an AI coach that actually knows your material.")}
          </p>

          <div className="flex flex-wrap gap-4 items-center">
            <button
              onClick={handleCTA}
              className="bg-ink text-paper px-8 py-4 rounded-full text-sm font-medium hover:bg-accent transition-all hover:-translate-y-0.5 hover:shadow-lift inline-flex items-center gap-2.5"
            >
              {user ? t("Go to Dashboard") : t("Get started — it's free")}
              <span>→</span>
            </button>
            <a
              href="#features"
              className="border border-ink px-6 py-4 rounded-full text-sm font-medium hover:bg-ink hover:text-paper transition"
            >
              {t("How it works")}
            </a>
          </div>

          {/* ============ FLOATING DECO CARDS ============ */}
          <div className="absolute top-32 w-[400px] h-[500px] pointer-events-none hidden lg:block ltr:right-0 rtl:left-0">
            <div className="deco-card deco-card-1">
              <div className="font-mono text-[10px] text-ink-mute uppercase tracking-widest mb-2">
                {t("Summary · Generated")}
              </div>
              <div className="font-serif text-lg font-medium mb-1.5">
                {t("Neural Networks")}
              </div>
              <div className="text-xs text-ink-soft leading-relaxed">
                {t("Key concept: backpropagation adjusts weights by computing gradients from the output layer backward through the network…")}
              </div>
            </div>

            <div className="deco-card deco-card-2">
              <div className="font-mono text-[10px] text-ink-mute uppercase tracking-widest mb-2">
                {t("Practice Exam · Midterm · 24 questions")}
              </div>
              <div className="font-serif text-lg font-medium mb-1.5">
                {t("What is the role of an activation function?")}
              </div>
              <div className="text-xs text-ink-soft leading-relaxed">
                {t("A) To initialize weights")}
                <br />
                {t("B) To introduce non-linearity ✓")}
                <br />
                {t("C) To reduce overfitting")}
              </div>
            </div>

            <div className="deco-card deco-card-3">
              <div className="font-mono text-[10px] text-ink-mute uppercase tracking-widest mb-2">
                {t("Flashcard · 3 of 24")}
              </div>
              <div className="font-serif text-lg font-medium mb-1.5">{t("CNN")}</div>
              <div className="text-xs text-ink-soft leading-relaxed">
                {t("Convolutional Neural Network — a deep learning architecture specialized for processing grid-like data such as images.")}
              </div>
            </div>
          </div>
        </section>

        {/* ============ STATS STRIP ============ */}
        <section className="bg-ink text-paper px-6 md:px-12 py-16 grid grid-cols-2 md:grid-cols-4 gap-8 md:gap-12">
          {[
            { num: "40+", label: t("Hours saved per term"), em: true },
            { num: "2 min", label: t("Avg processing time"), em: false },
            { num: "AR + EN", label: t("Bilingual support"), em: true },
            { num: "94%", label: t("Exam confidence ↑"), em: false },
          ].map((s, i) => (
            <div key={i} className="border-s border-paper/15 ps-6">
              <div className="font-serif text-4xl md:text-5xl font-normal leading-none mb-2">
                {s.em ? (
                  <em className="italic text-accent-soft font-light">{s.num}</em>
                ) : (
                  s.num
                )}
              </div>
              <div className="text-xs text-paper/60 font-mono uppercase tracking-widest">
                {s.label}
              </div>
            </div>
          ))}
        </section>

        {/* ============ FEATURES ============ */}
        <section id="features" className="px-6 md:px-12 py-24 max-w-7xl mx-auto">
          <div className="font-mono text-xs text-accent uppercase tracking-widest mb-4 flex items-center gap-3">
            <span className="w-6 h-px bg-accent"></span>
            {t("Capabilities")}
          </div>

          <h2 className="font-serif text-4xl md:text-6xl font-normal leading-none tracking-tight mb-20 max-w-3xl">
            {t("One recording. Everything you need.")}
          </h2>

          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-px bg-line border border-line rounded-3xl overflow-hidden">
            {[
              {
                num: "01",
                icon: "🎙",
                title: t("Bilingual Transcription"),
                desc: t("Drop in lecture recordings — Arabic, English, or the natural mix. Whisper transcribes them and the AI surfaces exam hints, emphasized concepts, and chapter breakdowns."),
              },
              {
                num: "02",
                icon: "📋",
                title: t("Structured Summaries"),
                desc: t("Your chapters become key concepts, definitions, and formulas — with each section tagged high / medium / low likelihood for the exam, based on your past papers."),
              },
              {
                num: "03",
                icon: "📝",
                title: t("Practice Exams"),
                desc: t("Generate full Quiz, Midterm, or Final practice papers that match the format of your real past exams. Download the PDF, solve it yourself, then reveal the model answer key in red."),
              },
              {
                num: "04",
                icon: "🗂️",
                title: t("Smart Flashcards"),
                desc: t("Cards auto-built from your documents — weighted toward the topics your past exams emphasize, so you study what's actually likely to show up."),
              },
              {
                num: "05",
                icon: "🎓",
                title: t("AI Chat Coach"),
                desc: t("Pick which chapters, recordings, and past exams to ground the conversation in, then ask anything — explanations, quick quizzes, exam tips — in Arabic or English."),
              },
              {
                num: "06",
                icon: "🔍",
                title: t("Past-Exam Intelligence"),
                desc: t("Upload old exams once. Mudaris extracts topic weights, question patterns, and difficulty — and uses them to shape every summary, flashcard, exam, and coach reply."),
              },
            ].map((f) => (
              <div key={f.num} className="bg-paper p-10 hover:bg-bg-alt transition">
                <div className="font-serif italic text-sm text-ink-mute mb-6">
                  {f.num} / 06
                </div>
                <div className="w-12 h-12 flex items-center justify-center bg-bg-alt rounded-xl mb-5 text-2xl">
                  {f.icon}
                </div>
                <h3 className="font-serif text-2xl font-medium mb-3 tracking-tight">
                  {f.title}
                </h3>
                <p className="text-sm text-ink-soft leading-relaxed">{f.desc}</p>
              </div>
            ))}
          </div>
        </section>

        {/* ============ CTA ============ */}
        <section className="px-6 md:px-12 py-24 max-w-4xl mx-auto text-center">
          <h2 className="font-serif text-4xl md:text-6xl font-normal leading-tight tracking-tight mb-8">
            {t("Stop re-listening. Start mastering.")}
          </h2>
          <button
            onClick={handleCTA}
            className="bg-ink text-paper px-10 py-5 rounded-full text-base font-medium hover:bg-accent transition-all hover:-translate-y-0.5 hover:shadow-lift inline-flex items-center gap-2.5"
          >
            {user ? t("Open Dashboard") : t("Get Started Free")}
            <span>→</span>
          </button>
        </section>

        {/* ============ FOOTER ============ */}
        <footer className="border-t border-line px-6 md:px-12 py-8 text-center text-sm text-ink-mute">
          {t("Mudaris © 2026 · Built with ♥ in Riyadh")}
        </footer>
      </main>
    </>
  );
}