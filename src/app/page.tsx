"use client";

import { useRouter } from "next/navigation";
import Navbar from "@/components/Navbar";
import Icon from "@/components/Icon";
import { useAuth } from "@/lib/auth-context";
import { useLang } from "@/lib/i18n";
import "./entry.css";

export default function Home() {
  const { user } = useAuth();
  const { t, dir } = useLang();
  const router = useRouter();
  const handleCTA = () => router.push(user ? "/dashboard" : "/signup");
  const tools = [
    { icon: "exam", title: "Practice Exams", copy: "Build a Quiz, Midterm, or Final from your selected course material. Solve it, then reveal the answers." },
    { icon: "cards", title: "Flashcards", copy: "Turn course concepts into a focused deck, with the source behind each side within reach." },
    { icon: "summary", title: "Summaries", copy: "Bring concepts, definitions, and formulas into a structured summary you can return to." },
    { icon: "chat", title: "AI Coach", copy: "Choose your sources and work through questions with a coach grounded in your course." },
  ] as const;

  return (
    <>
      <Navbar />
      <main className="home-main">
        <section className="home-hero">
          <div className="home-hero-copy">
            <h1>{t("A home for your lectures. Room to understand.")}</h1>
            <p>{t("Turn your lecture documents into a course workspace for practice exams, flashcards, summaries, and questions. Start with what you're actually studying.")}</p>
            <div className="home-actions">
              <button onClick={handleCTA} className="ui-button primary">{user ? t("Open Dashboard") : t("Create your workspace")}<Icon name={dir === "rtl" ? "arrow-left" : "arrow-right"} size={18} /></button>
              <a href="#how-it-works" className="ui-button secondary">{t("How it works")}</a>
            </div>
            <div className="home-language"><Icon name="globe" size={16} />{t("Your material in Arabic, English, or both.")}</div>
          </div>
          <div className="home-preview" aria-label={t("Illustrative course workspace")}>
            <div className="home-preview-caption"><span>{t("A look inside Mudaris")}</span><span>{t("Illustrative example")}</span></div>
            <div className="home-preview-window">
              <div className="home-preview-topbar"><span>{t("Mudaris")}</span><div className="home-preview-dots" aria-hidden="true"><i /><i /><i /></div></div>
              <div className="home-preview-body">
                <div className="home-preview-course"><span><Icon name="folder" size={21} /></span><div><h2>{t("Machine Learning")}</h2><p>{t("Your course workspace")}</p></div></div>
                <div className="home-preview-tabs" aria-hidden="true"><span>{t("Overview")}</span><span>{t("Materials")}</span><span>{t("Study tools")}</span></div>
                <div className="home-preview-foundation">
                  <strong>{t("A foundation built from your lectures")}</strong>
                  <p>{t("Prepare your lecture documents, then confirm that your course material is complete.")}</p>
                  <div className="home-preview-files">
                    {["Introduction to learning.pdf", "Neural networks.pdf"].map((file) => <div className="home-preview-file" key={file}><Icon name="file" size={15} /><span>{t(file)}</span><Icon name="check-circle" size={15} /></div>)}
                  </div>
                </div>
                <div className="home-preview-tools">{tools.map((tool) => <div className="home-preview-tool" key={tool.title}><Icon name={tool.icon} size={16} /><span>{t(tool.title)}</span></div>)}</div>
              </div>
            </div>
          </div>
        </section>

        <section id="how-it-works" className="home-flow">
          <h2 className="home-section-title">{t("Start with your course. Find your way through it.")}</h2>
          <div className="home-flow-grid">
            {[
              ["1", "Bring your lectures together", "Upload all your lecture documents first. Preparation and analysis make the original material ready for your study tools."],
              ["2", "Confirm your foundation", "Check that every lecture document is ready, then confirm you've added them all. Add past exams, recordings, and tutorials when you need them."],
              ["3", "Choose how you study", "Select your sources, make a practice exam, review a deck, read a summary, or talk through a question with the AI Coach."],
            ].map(([step, title, copy]) => <div className="home-flow-item" key={step}><span className="home-flow-number">{step}</span><h3>{t(title)}</h3><p>{t(copy)}</p></div>)}
          </div>
        </section>

        <section id="features" className="home-tools-section">
          <div className="home-tools-inner">
            <h2 className="home-section-title">{t("Four ways to work with what you're learning.")}</h2>
            <div className="home-tools-grid">{tools.map((tool) => <article key={tool.title}><div className="home-tool-icon"><Icon name={tool.icon} size={22} /></div><h3>{t(tool.title)}</h3><p>{t(tool.copy)}</p></article>)}</div>
          </div>
        </section>

        <section className="home-evidence">
          <div className="home-evidence-copy">
            <h2 className="home-section-title">{t("Keep the source in sight.")}</h2>
            <p>{t("Open the lecture evidence behind supported answers, concepts, and study materials. Your original sources stay connected to the work you create, so you can check the context for yourself.")}</p>
            <button onClick={handleCTA} className="ui-button primary">{user ? t("Go to Dashboard") : t("Get Started")}<Icon name={dir === "rtl" ? "arrow-left" : "arrow-right"} size={17} /></button>
          </div>
          <div className="home-source-sample">
            <p>{t("Illustrative source preview")}</p>
            <div className="home-source-paper">
              <h3>{t("Neural networks.pdf")}</h3>
              <blockquote>{t("An activation function introduces non-linearity, allowing a neural network to learn more complex relationships.")}</blockquote>
              <small><Icon name="file" size={14} />{t("Original lecture material")}</small>
            </div>
          </div>
        </section>
        <footer className="home-footer"><span>{t("Mudaris © 2026")}</span><span>{t("Made for studying in Arabic and English.")}</span></footer>
      </main>
    </>
  );
}
