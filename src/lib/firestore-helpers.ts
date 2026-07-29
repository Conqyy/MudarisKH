import {
  collection,
  doc,
  addDoc,
  getDoc,
  getDocs,
  updateDoc,
  deleteDoc,
  query,
  where,
} from "firebase/firestore";
import { db } from "./firebase";

// ============ TYPES ============
export type ReminderType =
  | "quiz"
  | "midterm"
  | "final"
  | "assignment"
  | "project"
  | "presentation"
  | "other";

export interface CourseReminder {
  id: string;
  title: string;
  type: ReminderType;
  date?: string; // YYYY-MM-DD
  time?: string; // HH:MM (optional)
  notes?: string;
  done: boolean;
  createdAt: number;
}

export interface Course {
  id: string;
  userId: string;
  code: string;
  title: string;
  instructor: string;
  color: string;
  // User-defined ordering of materials (arrays of item ids), stored on the
  // course doc because the materials collections are backend-only (the client
  // can't write to them, but it CAN write to its own courses).
  documentOrder?: string[];
  audioOrder?: string[];
  examOrder?: string[];
  tutorialOrder?: string[];
  // User-defined display names for materials, keyed by item id.
  titleOverrides?: Record<string, string>;
  // Student-managed reminders (quizzes, assignments, midterms, etc.) — stored
  // on the course doc since courses are client-writable.
  reminders?: CourseReminder[];
  // Archived courses are hidden from the active dashboard grid, sidebar, and
  // stats, but keep all their materials and remain fully restorable.
  archived?: boolean;
  createdAt: number;
}

export interface Lecture {
  id: string;
  courseId: string;
  userId: string;
  title: string;
  duration: number;
  uploadedAt: number;
  status: "processing" | "ready" | "failed";
  audioUrl?: string;
  transcript?: any[];
  summary?: any;
  quiz?: any[];
  flashcards?: any[];
}

// ============ DOCUMENTS (Model 1) ============
export interface CourseDocument {
  id: string;
  courseId: string;
  userId: string;
  lectureId?: string;
  title: string;
  fileType: "pdf" | "pptx" | "docx";
  fileUrl: string;
  storagePath: string;
  fileSize: number;
  status: "pending" | "processing" | "completed" | "failed";
  errorMessage?: string;
  extractedText?: string;
  analysis?: {
    topics: string[];
    definitions: { term: string; definition: string }[];
    formulas: string[];
    chapterMapping: { chapter: string; content: string }[];
    keyConceptCount: number;
  };
  order?: number;
  uploadedAt: number;
  processedAt?: number;
}

// ============ AUDIO RECORDINGS (Model 2) ============
export interface AudioRecording {
  id: string;
  courseId: string;
  userId: string;
  lectureId?: string;
  title: string;
  fileUrl: string;
  storagePath: string;
  fileSize: number;
  duration?: number;
  status:
    | "pending"
    | "queued"
    | "downloading"
    | "converting"
    | "transcribing"
    | "analyzing"
    | "completed"
    | "failed";
  errorMessage?: string;
  transcript?: string;
  insights?: {
    chapterMapping: { chapter: string; segments: string[] }[];
    examHints: { hint: string; confidence: number; source: string }[];
    keyEmphasis: {
      topic: string;
      emphasisLevel: "high" | "medium" | "low";
      quote: string;
    }[];
    summary: string;
  };
  order?: number;
  uploadedAt: number;
  processedAt?: number;
}

// ============ HISTORICAL EXAMS (Model 3) ============
export interface HistoricalExam {
  id: string;
  courseId: string;
  userId: string;
  title: string;
  fileUrl: string;
  storagePath: string;
  fileSize: number;
  status: "pending" | "processing" | "completed" | "failed";
  errorMessage?: string;
  extractedText?: string;
  analysis?: {
    topicWeights: {
      topic: string;
      weight: number;
      questionCount: number;
    }[];
    questionTypes: { type: string; count: number; percentage: number }[];
    difficultyDistribution: { level: string; percentage: number }[];
    gradingBlueprint: string;
    patterns: string[];
    totalQuestions: number;
  };
  order?: number;
  uploadedAt: number;
  processedAt?: number;
}

// ============ TUTORIALS (practice problems — ideas only) ============
// Tutorials are ungraded practice sheets. They are analyzed for topics and
// worked-problem IDEAS and feed the exam generator's CONTENT only — never its
// grading weight or format (that comes from past exams).
export interface Tutorial {
  id: string;
  courseId: string;
  userId: string;
  title: string;
  fileType: "pdf" | "pptx" | "docx";
  fileUrl: string;
  storagePath: string;
  fileSize: number;
  status: "pending" | "processing" | "completed" | "failed";
  errorMessage?: string;
  extractedText?: string;
  analysis?: {
    topics: string[];
    problems: {
      label: string;
      statement: string;
      given?: string;
      asks?: string[];
      concept?: string;
      method?: string;
      type?: string;
    }[];
    formulas: string[];
    skills: string[];
    problemCount: number;
  };
  order?: number;
  uploadedAt: number;
  processedAt?: number;
}

// Firestore rejects `undefined` field values — strip them before writing.
// Firestore rejects `undefined` ANYWHERE in the payload — including values
// nested inside arrays/objects (e.g. reminders[].date when left blank). This
// strips `undefined` recursively so such writes don't silently throw.
function stripUndefinedDeep(value: any): any {
  if (Array.isArray(value)) {
    return value.map((v) => stripUndefinedDeep(v));
  }
  if (value && typeof value === "object" && !(value instanceof Date)) {
    const out: Record<string, any> = {};
    for (const [k, v] of Object.entries(value)) {
      if (v !== undefined) out[k] = stripUndefinedDeep(v);
    }
    return out;
  }
  return value;
}

function stripUndefined<T extends Record<string, any>>(obj: T): Partial<T> {
  return stripUndefinedDeep(obj) as Partial<T>;
}

// ============ COURSES ============
export async function createCourse(
  course: Omit<Course, "id" | "createdAt">
): Promise<string> {
  const docRef = await addDoc(collection(db, "courses"), {
    ...stripUndefined(course),
    createdAt: Date.now(),
  });
  return docRef.id;
}

export async function getUserCourses(userId: string): Promise<Course[]> {
  const q = query(collection(db, "courses"), where("userId", "==", userId));
  const snapshot = await getDocs(q);
  return snapshot.docs.map(
    (d) => ({ id: d.id, ...d.data() } as Course)
  );
}

export async function getCourse(courseId: string): Promise<Course | null> {
  const snapshot = await getDoc(doc(db, "courses", courseId));
  if (!snapshot.exists()) return null;
  return { id: snapshot.id, ...snapshot.data() } as Course;
}

export async function updateCourse(
  courseId: string,
  data: Partial<Course>
): Promise<void> {
  await updateDoc(doc(db, "courses", courseId), stripUndefined(data));
}

export async function deleteCourse(courseId: string): Promise<void> {
  await deleteDoc(doc(db, "courses", courseId));
}

// ============ LECTURES ============
export async function getLecture(lectureId: string): Promise<Lecture | null> {
  const snapshot = await getDoc(doc(db, "lectures", lectureId));
  if (!snapshot.exists()) return null;
  return { id: snapshot.id, ...snapshot.data() } as Lecture;
}

export async function updateLecture(
  lectureId: string,
  data: Partial<Lecture>
): Promise<void> {
  await updateDoc(doc(db, "lectures", lectureId), data);
}

// NOTE: documents, audio recordings, historical exams and tutorials are
// created/updated by the FastAPI backend (Admin SDK), not the client — their
// interfaces above are still used as types for what the API returns.
