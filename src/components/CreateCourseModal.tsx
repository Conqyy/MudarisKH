"use client";

import { useState, FormEvent } from "react";
import { useAuth } from "@/lib/auth-context";
import { createCourse } from "@/lib/firestore-helpers";

interface Props {
  onClose: () => void;
  onSuccess: () => void;
  existingCoursesCount: number;
}

// 6 colors for courses (same as prototype)
const COLORS = [
  { name: "Terracotta", value: "#c8472f" },
  { name: "Gold", value: "#b8923a" },
  { name: "Sage", value: "#6b7d5b" },
  { name: "Ink", value: "#4a4640" },
  { name: "Plum", value: "#8a6fa7" },
  { name: "Teal", value: "#3d7a8c" },
];

export default function CreateCourseModal({
  onClose,
  onSuccess,
  existingCoursesCount,
}: Props) {
  const { user } = useAuth();

  const [code, setCode] = useState("");
  const [title, setTitle] = useState("");
  const [instructor, setInstructor] = useState("");
  const [selectedColor, setSelectedColor] = useState(
    COLORS[existingCoursesCount % COLORS.length].value
  );
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");

    if (!user) return;
    if (!code.trim()) return setError("Course code is required");
    if (!title.trim()) return setError("Course title is required");

    setSubmitting(true);
    try {
      await createCourse({
        userId: user.uid,
        code: code.trim().toUpperCase(),
        title: title.trim(),
        instructor: instructor.trim() || "—",
        color: selectedColor,
      });
      onSuccess();
      onClose();
    } catch (err: any) {
      console.error(err);
      setError(err.message || "Failed to create course. Please try again.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div
      className="fixed inset-0 bg-ink/50 backdrop-blur-md z-[100] flex items-center justify-center p-6 animate-fade-in"
      onClick={onClose}
    >
      <div
        className="bg-paper rounded-3xl p-8 md:p-10 max-w-md w-full shadow-lift relative max-h-[90vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <button
          onClick={onClose}
          className="absolute top-5 right-5 text-2xl text-ink-soft hover:text-ink leading-none w-8 h-8 flex items-center justify-center rounded-full hover:bg-bg-alt transition"
        >
          ×
        </button>

        <h2 className="font-serif text-3xl font-medium mb-2 tracking-tight">
          Create a course
        </h2>
        <p className="text-ink-soft text-sm mb-8">
          Organize your lectures under a subject.
        </p>

        {error && (
          <div className="bg-accent/10 border border-accent text-accent text-sm rounded-xl p-3 mb-5">
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-5">
          <div>
            <label className="block text-sm font-medium text-ink-soft mb-2">
              Course code <span className="text-accent">*</span>
            </label>
            <input
              type="text"
              value={code}
              onChange={(e) => setCode(e.target.value)}
              placeholder="e.g. CS464"
              className="w-full px-4 py-3 border border-line rounded-xl bg-bg focus:outline-none focus:border-accent transition uppercase"
              maxLength={20}
              required
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-ink-soft mb-2">
              Course title <span className="text-accent">*</span>
            </label>
            <input
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="e.g. Neural Networks & Deep Learning"
              className="w-full px-4 py-3 border border-line rounded-xl bg-bg focus:outline-none focus:border-accent transition"
              maxLength={80}
              required
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-ink-soft mb-2">
              Instructor{" "}
              <span className="text-ink-mute font-normal">(optional)</span>
            </label>
            <input
              type="text"
              value={instructor}
              onChange={(e) => setInstructor(e.target.value)}
              placeholder="e.g. Dr. Qaisar Abbas"
              className="w-full px-4 py-3 border border-line rounded-xl bg-bg focus:outline-none focus:border-accent transition"
              maxLength={60}
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-ink-soft mb-2">
              Color
            </label>
            <div className="flex gap-2 flex-wrap">
              {COLORS.map((c) => (
                <button
                  key={c.value}
                  type="button"
                  onClick={() => setSelectedColor(c.value)}
                  className={`w-11 h-11 rounded-full transition relative ${
                    selectedColor === c.value
                      ? "ring-2 ring-ink ring-offset-2 ring-offset-paper"
                      : "hover:scale-110"
                  }`}
                  style={{ background: c.value }}
                  title={c.name}
                />
              ))}
            </div>
          </div>

          <button
            type="submit"
            disabled={!code || !title || submitting}
            className="w-full mt-3 bg-ink text-paper py-3.5 rounded-full font-medium hover:bg-accent transition disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {submitting ? "Creating…" : "Create Course"}
          </button>
        </form>
      </div>
    </div>
  );
}