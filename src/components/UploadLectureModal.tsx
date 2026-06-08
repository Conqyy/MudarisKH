"use client";

import { useState, useRef, FormEvent, ChangeEvent, DragEvent } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth-context";
import { createLecture, Course } from "@/lib/firestore-helpers";

interface Props {
  courses: Course[];
  defaultCourseId?: string;
  onClose: () => void;
  onSuccess: () => void;
}

// Accepted file types
const ACCEPTED_TYPES = [
  "audio/mpeg",
  "audio/mp3",
  "audio/mp4",
  "audio/wav",
  "audio/x-wav",
  "audio/x-m4a",
  "audio/m4a",
  "video/mp4",
  "video/webm",
];

const ACCEPTED_EXT = "MP3, MP4, WAV, M4A, WEBM";
const MAX_SIZE_MB = 25; // Whisper API limit

export default function UploadLectureModal({
  courses,
  defaultCourseId,
  onClose,
  onSuccess,
}: Props) {
  const { user } = useAuth();
  const router = useRouter();
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [courseId, setCourseId] = useState(
    defaultCourseId || courses[0]?.id || ""
  );
  const [dragActive, setDragActive] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  // ============ FILE HANDLING ============
  const validateFile = (f: File): string | null => {
    // Size check
    const sizeMB = f.size / 1024 / 1024;
    if (sizeMB > MAX_SIZE_MB) {
      return `File is too large (${sizeMB.toFixed(1)}MB). Max is ${MAX_SIZE_MB}MB.`;
    }

    // Type check (lenient - some browsers report different MIME types)
    const ext = f.name.split(".").pop()?.toLowerCase();
    const validExts = ["mp3", "mp4", "wav", "m4a", "webm"];
    if (!ext || !validExts.includes(ext)) {
      return `Invalid file type. Please use: ${ACCEPTED_EXT}`;
    }

    return null;
  };

  const handleFileSelect = (selectedFile: File) => {
    setError("");
    const validationError = validateFile(selectedFile);
    if (validationError) {
      setError(validationError);
      return;
    }
    setFile(selectedFile);
    // Auto-fill title from filename (without extension)
    if (!title) {
      const nameWithoutExt = selectedFile.name.replace(/\.[^/.]+$/, "");
      setTitle(nameWithoutExt);
    }
  };

  const handleFileChange = (e: ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    if (f) handleFileSelect(f);
  };

  // Drag & Drop handlers
  const handleDrag = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === "dragenter" || e.type === "dragover") {
      setDragActive(true);
    } else if (e.type === "dragleave") {
      setDragActive(false);
    }
  };

  const handleDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);

    if (e.dataTransfer.files?.[0]) {
      handleFileSelect(e.dataTransfer.files[0]);
    }
  };

  // ============ SUBMIT ============
  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");

    if (!user) return;
    if (!file) return setError("Please select a file");
    if (!title.trim()) return setError("Please enter a lecture title");
    if (!courseId) return setError("Please select a course");

    setSubmitting(true);

    try {
      // Create lecture document in Firestore with "processing" status
      const lectureId = await createLecture({
        userId: user.uid,
        courseId,
        title: title.trim(),
        duration: 0, // Will be set after processing
        status: "processing",
      });

      // TODO: This is where we'll send the file to Whisper API later
      // For now, just navigate to the lecture page where processing will happen
      onSuccess();
      onClose();

      // Redirect to processing page (will build next phase)
      router.push(`/lecture/${lectureId}/processing`);
    } catch (err: any) {
      console.error(err);
      setError(err.message || "Failed to upload. Please try again.");
      setSubmitting(false);
    }
  };

  // ============ FORMAT FILE SIZE ============
  const formatFileSize = (bytes: number) => {
    const mb = bytes / 1024 / 1024;
    if (mb < 1) return `${(bytes / 1024).toFixed(0)} KB`;
    return `${mb.toFixed(1)} MB`;
  };

  return (
    <div
      className="fixed inset-0 bg-ink/50 backdrop-blur-md z-[100] flex items-center justify-center p-6 animate-fade-in"
      onClick={onClose}
    >
      <div
        className="bg-paper rounded-3xl p-8 md:p-10 max-w-lg w-full shadow-lift relative max-h-[90vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <button
          onClick={onClose}
          disabled={submitting}
          className="absolute top-5 right-5 text-2xl text-ink-soft hover:text-ink leading-none w-8 h-8 flex items-center justify-center rounded-full hover:bg-bg-alt transition disabled:opacity-50"
        >
          ×
        </button>

        <h2 className="font-serif text-3xl font-medium mb-2 tracking-tight">
          Upload a lecture
        </h2>
        <p className="text-ink-soft text-sm mb-8">
          Audio or video. We&apos;ll transcribe, summarize, and generate study
          material.
        </p>

        {error && (
          <div className="bg-accent/10 border border-accent text-accent text-sm rounded-xl p-3 mb-5">
            {error}
          </div>
        )}

        {/* ============ FILE DROP ZONE ============ */}
        <div
          onDragEnter={handleDrag}
          onDragOver={handleDrag}
          onDragLeave={handleDrag}
          onDrop={handleDrop}
          onClick={() => fileInputRef.current?.click()}
          className={`border-2 border-dashed rounded-2xl p-8 text-center cursor-pointer transition mb-6 ${
            dragActive
              ? "border-accent bg-accent/5 scale-[1.01]"
              : file
              ? "border-sage bg-sage/5"
              : "border-line bg-bg hover:border-accent hover:bg-bg-alt"
          }`}
        >
          {file ? (
            <>
              <div className="text-4xl mb-3">✓</div>
              <div className="font-serif text-lg mb-1 text-sage">
                {file.name}
              </div>
              <div className="text-xs text-ink-mute mb-3">
                {formatFileSize(file.size)}
              </div>
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  setFile(null);
                  setTitle("");
                  if (fileInputRef.current) fileInputRef.current.value = "";
                }}
                className="text-xs text-accent hover:underline"
              >
                Choose a different file
              </button>
            </>
          ) : (
            <>
              <div className="text-4xl mb-3 opacity-50">
                {dragActive ? "📥" : "📁"}
              </div>
              <div className="font-serif text-lg mb-1">
                {dragActive
                  ? "Drop your file here"
                  : "Drop a file or click to browse"}
              </div>
              <div className="text-xs text-ink-mute">
                {ACCEPTED_EXT} · Up to {MAX_SIZE_MB}MB
              </div>
            </>
          )}

          <input
            ref={fileInputRef}
            type="file"
            accept={ACCEPTED_TYPES.join(",")}
            onChange={handleFileChange}
            className="hidden"
          />
        </div>

        {/* ============ FORM FIELDS ============ */}
        <form onSubmit={handleSubmit} className="space-y-5">
          <div>
            <label className="block text-sm font-medium text-ink-soft mb-2">
              Course <span className="text-accent">*</span>
            </label>
            <select
              value={courseId}
              onChange={(e) => setCourseId(e.target.value)}
              className="w-full px-4 py-3 border border-line rounded-xl bg-bg focus:outline-none focus:border-accent transition"
              required
            >
              {courses.length === 0 ? (
                <option value="">No courses available</option>
              ) : (
                courses.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.code} — {c.title}
                  </option>
                ))
              )}
            </select>
          </div>

          <div>
            <label className="block text-sm font-medium text-ink-soft mb-2">
              Lecture title <span className="text-accent">*</span>
            </label>
            <input
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="e.g. Convolutional Neural Networks"
              className="w-full px-4 py-3 border border-line rounded-xl bg-bg focus:outline-none focus:border-accent transition"
              maxLength={100}
              required
            />
          </div>

          <button
            type="submit"
            disabled={!file || !title || !courseId || submitting}
            className="w-full mt-3 bg-ink text-paper py-3.5 rounded-full font-medium hover:bg-accent transition disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2"
          >
            {submitting ? (
              <>
                <span className="w-4 h-4 border-2 border-paper/30 border-t-paper rounded-full animate-spin"></span>
                Uploading…
              </>
            ) : (
              <>Start Processing →</>
            )}
          </button>

          <p className="text-xs text-ink-mute text-center pt-2">
            Processing usually takes 1–3 minutes depending on file length.
          </p>
        </form>
      </div>
    </div>
  );
}