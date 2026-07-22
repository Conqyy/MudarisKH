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
  examDate?: string; // final exam date
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
export async function createLecture(
  lecture: Omit<Lecture, "id" | "uploadedAt">
): Promise<string> {
  const docRef = await addDoc(collection(db, "lectures"), {
    ...lecture,
    uploadedAt: Date.now(),
  });
  return docRef.id;
}

export async function getUserLectures(userId: string): Promise<Lecture[]> {
  const q = query(collection(db, "lectures"), where("userId", "==", userId));
  const snapshot = await getDocs(q);
  return snapshot.docs.map(
    (d) => ({ id: d.id, ...d.data() } as Lecture)
  );
}

export async function getCourseLectures(
  courseId: string
): Promise<Lecture[]> {
  const q = query(
    collection(db, "lectures"),
    where("courseId", "==", courseId)
  );
  const snapshot = await getDocs(q);
  return snapshot.docs.map(
    (d) => ({ id: d.id, ...d.data() } as Lecture)
  );
}

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

export async function deleteLecture(lectureId: string): Promise<void> {
  await deleteDoc(doc(db, "lectures", lectureId));
}

// ============ DOCUMENTS CRUD ============
export async function createDocument(
  document: Omit<CourseDocument, "id" | "uploadedAt">
): Promise<string> {
  const docRef = await addDoc(collection(db, "documents"), {
    ...document,
    uploadedAt: Date.now(),
  });
  return docRef.id;
}

export async function getCourseDocuments(
  courseId: string
): Promise<CourseDocument[]> {
  const q = query(
    collection(db, "documents"),
    where("courseId", "==", courseId)
  );
  const snapshot = await getDocs(q);
  return snapshot.docs.map(
    (d) => ({ id: d.id, ...d.data() } as CourseDocument)
  );
}

export async function updateDocument(
  docId: string,
  data: Partial<CourseDocument>
): Promise<void> {
  await updateDoc(doc(db, "documents", docId), data);
}

export async function deleteDocument(docId: string): Promise<void> {
  await deleteDoc(doc(db, "documents", docId));
}

// ============ AUDIO RECORDINGS CRUD ============
export async function createAudioRecording(
  recording: Omit<AudioRecording, "id" | "uploadedAt">
): Promise<string> {
  const docRef = await addDoc(collection(db, "audio_recordings"), {
    ...recording,
    uploadedAt: Date.now(),
  });
  return docRef.id;
}

export async function getCourseAudioRecordings(
  courseId: string
): Promise<AudioRecording[]> {
  const q = query(
    collection(db, "audio_recordings"),
    where("courseId", "==", courseId)
  );
  const snapshot = await getDocs(q);
  return snapshot.docs.map(
    (d) => ({ id: d.id, ...d.data() } as AudioRecording)
  );
}

export async function updateAudioRecording(
  recId: string,
  data: Partial<AudioRecording>
): Promise<void> {
  await updateDoc(doc(db, "audio_recordings", recId), data);
}

export async function deleteAudioRecording(recId: string): Promise<void> {
  await deleteDoc(doc(db, "audio_recordings", recId));
}

// ============ HISTORICAL EXAMS CRUD ============
export async function createHistoricalExam(
  exam: Omit<HistoricalExam, "id" | "uploadedAt">
): Promise<string> {
  const docRef = await addDoc(collection(db, "historical_exams"), {
    ...exam,
    uploadedAt: Date.now(),
  });
  return docRef.id;
}

export async function getCourseHistoricalExams(
  courseId: string
): Promise<HistoricalExam[]> {
  const q = query(
    collection(db, "historical_exams"),
    where("courseId", "==", courseId)
  );
  const snapshot = await getDocs(q);
  return snapshot.docs.map(
    (d) => ({ id: d.id, ...d.data() } as HistoricalExam)
  );
}

export async function updateHistoricalExam(
  examId: string,
  data: Partial<HistoricalExam>
): Promise<void> {
  await updateDoc(doc(db, "historical_exams", examId), data);
}

export async function deleteHistoricalExam(examId: string): Promise<void> {
  await deleteDoc(doc(db, "historical_exams", examId));
}
