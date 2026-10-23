"use client";

import Icon from "@/components/Icon";
import { COURSE_COLORS as COLORS } from "@/components/material-presentation";
import { useLang } from "@/lib/i18n";
import { useDialog } from "@/lib/use-dialog";

import { useState, FormEvent } from "react";
import { updateCourse, Course } from "@/lib/firestore-helpers";

interface Props {
  course: Course;
  onClose: () => void;
  onSuccess: () => void;
}

export default function EditCourseModal({ course, onClose, onSuccess }: Props) {
  const { t } = useLang();
  const dialogRef = useDialog(onClose);
  const [code, setCode] = useState(course.code);
  const [title, setTitle] = useState(course.title);
  const [instructor, setInstructor] = useState(
    course.instructor === "—" ? "" : course.instructor
  );
  const [selectedColor, setSelectedColor] = useState(course.color);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");

    if (!code.trim()) return setError(t("Course code is required"));
    if (!title.trim()) return setError(t("Course title is required"));

    setSubmitting(true);
    try {
      await updateCourse(course.id, {
        code: code.trim().toUpperCase(),
        title: title.trim(),
        instructor: instructor.trim() || "—",
        color: selectedColor,
      });
      onSuccess();
      onClose();
    } catch (err: any) {
      console.error(err);
      setError(err.message || "Failed to update course.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div
      ref={dialogRef} role="dialog" aria-modal="true" aria-label={t("Edit course")} tabIndex={-1} className="dialog-overlay"
      onClick={onClose}
    >
      <div
        className="dialog-panel material-dialog max-w-md"
        onClick={(e) => e.stopPropagation()}
      >
        <button
          onClick={onClose}
          aria-label={t("Close dialog")}
          className="icon-button material-dialog-close"
        ><Icon name="close" /></button>

        <h2 className="font-sans text-3xl font-medium mb-2 tracking-tight">
              {t("Edit course")}
        </h2>
        <p className="text-ink-soft text-sm mb-8">
              {t("Update your course details.")}
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
              className="ui-input w-full"
              maxLength={80}
              required
            />
          </div>

          <div>
            <label htmlFor="course-instructor" className="block text-sm font-medium text-ink-soft mb-2">
              {t("Instructor")}
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

          <div className="flex gap-3 pt-3">
            <button
              type="button"
              onClick={onClose}
              className="ui-button secondary flex-1"
            >
              {t("Cancel")}
            </button>
            <button
              type="submit"
              disabled={submitting}
              className="ui-button primary flex-1"
            >
              {submitting ? t("Saving…") : t("Save changes")}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}