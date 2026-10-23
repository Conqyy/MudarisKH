"use client";

import Icon from "@/components/Icon";
import { COURSE_COLORS as COLORS } from "@/components/material-presentation";
import { useLang } from "@/lib/i18n";
import { useOverlayMotion } from "@/lib/use-overlay-motion";

import { useState, FormEvent } from "react";
import { useAuth } from "@/lib/auth-context";
import { createCourse } from "@/lib/firestore-helpers";

interface Props {
  onClose: () => void;
  onSuccess: () => void;
  existingCoursesCount: number;
}

export default function CreateCourseModal({
  onClose,
  onSuccess,
  existingCoursesCount,
}: Props) {
  const { user } = useAuth();

  const { t } = useLang();
  const { ref: dialogRef, close: closeDialog } = useOverlayMotion(onClose, { kind: "dialog" });
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
    if (!code.trim()) return setError(t("Course code is required"));
    if (!title.trim()) return setError(t("Course title is required"));

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
      ref={dialogRef} role="dialog" aria-modal="true" aria-label={t("Create a course")} tabIndex={-1} className="dialog-overlay"
      onClick={closeDialog}
    >
      <div
        className="dialog-panel material-dialog max-w-md"
        onClick={(e) => e.stopPropagation()}
      >
        <button
          onClick={closeDialog}
          aria-label={t("Close dialog")}
          className="icon-button material-dialog-close"
        ><Icon name="close" /></button>

        <h2 className="font-sans text-3xl font-medium mb-2 tracking-tight">
              {t("Create a course")}
        </h2>
        <p className="text-ink-soft text-sm mb-8">
              {t("Organize your lectures under a subject.")}
        </p>

        {error && (
          <div role="alert" className="material-inline-notice danger mb-5">
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-5">
          <div>
            <label htmlFor="course-code" className="block text-sm font-medium text-ink-soft mb-2">
              {t("Course code")} <span className="text-accent">*</span>
            </label>
            <input id="course-code"
              type="text"
              value={code}
              onChange={(e) => setCode(e.target.value)}
              placeholder="e.g. CS464"
              className="ui-input w-full uppercase"
              maxLength={20}
              required
            />
          </div>

          <div>
            <label htmlFor="course-title" className="block text-sm font-medium text-ink-soft mb-2">
              {t("Course title")} <span className="text-accent">*</span>
            </label>
            <input id="course-title"
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="e.g. Neural Networks & Deep Learning"
              className="ui-input w-full"
              maxLength={80}
              required
            />
          </div>

          <div>
            <label htmlFor="course-instructor" className="block text-sm font-medium text-ink-soft mb-2">
              {t("Instructor")}{" "}
              <span className="text-ink-mute font-normal">{t("(optional)")}</span>
            </label>
            <input id="course-instructor"
              type="text"
              value={instructor}
              onChange={(e) => setInstructor(e.target.value)}
              placeholder="e.g. Dr. Qaisar Abbas"
              className="ui-input w-full"
              maxLength={60}
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-ink-soft mb-2">
              {t("Color")}
            </label>
            <div className="flex gap-2 flex-wrap">
              {COLORS.map((c) => (
                <button
                  key={c.value}
                  type="button"
                  onClick={() => setSelectedColor(c.value)}
                  className="material-course-color"
                  aria-label={t(c.name)} aria-pressed={selectedColor === c.value}
                  style={{ background: c.value }}
                  title={t(c.name)}
                />
              ))}
            </div>
          </div>

          <button
            type="submit"
            disabled={!code || !title || submitting}
            className="ui-button primary w-full mt-3"
          >
            {submitting ? t("Creating…") : t("Create Course")}
          </button>
        </form>
      </div>
    </div>
  );
}