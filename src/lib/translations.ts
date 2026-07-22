// Arabic (Najdi-flavored) translations, keyed by the English source string.
// t(s) returns AR[s] when the language is Arabic, otherwise the English key.
// The "Mudaris" persona speaks in the first person ("مدرّس بيشوف… يحلّل…").

export const AR: Record<string, string> = {
  // ---- Brand / persona ----
  "Mudaris": "مُدرّس",
  "AI Study Assistant": "مساعدك الذكي للمذاكرة",

  // ---- Navbar / nav ----
  "Home": "الرئيسية",
  "Features": "المميزات",
  "Feedback": "ملاحظاتك",
  "Student": "طالب",
  "Sign In": "تسجيل الدخول",
  "Sign Out": "تسجيل الخروج",
  "Get Started": "ابدأ الحين",
  "Dashboard": "لوحتي",
  "Courses": "المواد",
  "Recent": "الأخيرة",
  "Bookmarked": "المحفوظة",
  "Workspace": "مساحة العمل",
  "Settings": "الإعدادات",
  "Account": "حسابي",
  "Sign out": "تسجيل الخروج",
  "Sign in": "تسجيل الدخول",
  "Profile": "الملف الشخصي",
  "Language": "اللغة",
  "Arabic": "العربية",
  "English": "الإنجليزية",
  "Switch to dark mode": "الوضع الليلي",
  "Switch to light mode": "الوضع النهاري",

  // ---- Common actions ----
  "Upload": "ارفع",
  "Cancel": "إلغاء",
  "Save": "حفظ",
  "Delete": "حذف",
  "Edit": "تعديل",
  "Close": "إغلاق",
  "Generate": "توليد",
  "Download": "تنزيل",
  "Open": "فتح",
  "Done": "تم",
  "Select all": "تحديد الكل",
  "Deselect all": "إلغاء التحديد",
  "Clear": "مسح",
  "All": "الكل",

  // ---- Dashboard ----
  "Good morning": "صباح الخير",
  "Good afternoon": "نهارك سعيد",
  "Good evening": "مساء الخير",
  "Create a course to start building your exam prep.":
    "أنشئ مادة وابدأ تجهّز للاختبار.",
  "exam in": "الاختبار بعد",
  "days": "يوم",
  "You've generated": "ولّدت",
  "practice exams. Keep practicing.": "اختبار تجريبي. واصل التمرين.",
  "Upload your lecture documents and past exams to generate practice exams.":
    "ارفع مستندات محاضراتك واختباراتك السابقة عشان نولّد اختبارات تجريبية.",
  "Practice Exams": "اختبارات تجريبية",
  "active subjects": "مواد نشطة",
  "analyzed": "تم تحليلها",
  "generated": "تم توليدها",
  "Your courses": "موادك",
  "Archive course": "أرشفة المادة",
  "Unarchive": "استرجاع من الأرشيف",
  "Archived courses": "المواد المؤرشفة",
  "Archived": "مؤرشفة",
  "No active courses": "ما عندك مواد نشطة",
  "All your courses are archived. Restore one below, or create a new course.":
    "كل موادك مؤرشفة. استرجع وحدة من تحت، أو أنشئ مادة جديدة.",
  "Create your first course, then upload its lecture documents and past exams to generate AI practice exams.":
    "أنشئ أول مادة، بعدها ارفع مستندات محاضراتها واختباراتها السابقة عشان نولّد اختبارات تجريبية.",
  "Create your first course": "أنشئ أول مادة لك",
  "Open course": "افتح المادة",
  "Until exam": "باقي للاختبار",
  "My Courses": "موادي",
  "New Course": "مادة جديدة",
  "Add Course": "أضف مادة",
  "Create Course": "إنشاء مادة",
  "No courses yet": "ما عندك مواد لحين",
  "Create your first course to get started.": "أنشئ أول مادة عشان نبدأ.",
  "Reminders": "التذكيرات",
  "upcoming": "قادمة",
  "overdue": "متأخرة",
  "Show done": "عرض المنجزة",
  "Hide done": "إخفاء المنجزة",
  "You're all caught up — no upcoming reminders.":
    "كل شي تمام — ما فيه تذكيرات قادمة.",
  "Today": "اليوم",
  "Tomorrow": "بكرة",
  "No date": "بدون تاريخ",
  "Overdue": "متأخّر",
  "In": "بعد",
  "d": "ي",
  // Reminder types
  "Quiz": "كويز",
  "Midterm": "نصفي",
  "Final": "نهائي",
  "Assignment": "واجب",
  "Project": "مشروع",
  "Presentation": "عرض",
  "Other": "غير ذلك",
  // Reminder panel (per course)
  "Add": "أضف",
  "No reminders yet": "ما عندك تذكيرات للحين",
  "Track quizzes, midterms, assignments, and deadlines for this course so nothing slips through.":
    "تابع الكويزات والاختبارات والواجبات والمواعيد لهذي المادة عشان ما يفوتك شي.",
  "Add your first reminder": "أضف أول تذكير لك",
  "Mark as done": "علّمه منجز",
  "Mark as not done": "رجّعه غير منجز",
  "Edit reminder": "تعديل التذكير",
  "New reminder": "تذكير جديد",
  "Quizzes, midterms, assignments, deadlines — anything you need to remember for this course.":
    "كويزات، اختبارات، واجبات، مواعيد — أي شي تبي تتذكّره لهذي المادة.",
  "Type": "النوع",
  "e.g. Quiz 2 — Chapters 3–4": "مثال: كويز ٢ — الفصول ٣–٤",
  "Date": "التاريخ",
  "Time": "الوقت",
  "Notes": "ملاحظات",
  "e.g. Closed book, bring calculator": "مثال: كتاب مغلق، جيب الآلة الحاسبة",
  "Save changes": "احفظ التعديلات",
  "Add reminder": "أضف تذكير",
  "Give the reminder a title.": "اكتب عنوان للتذكير.",

  // ---- Course page: sections ----
  "Documents": "المستندات",
  "Past Exams": "الاختبارات السابقة",
  "Tutorials": "التمارين",
  "Audio Recordings": "التسجيلات الصوتية",
  "Practice Exam": "اختبار تجريبي",
  "Flashcards": "البطاقات",
  "Summary": "الملخّص",
  "AI Tutor": "المعلّم الذكي",
  "Intelligence Summary": "ملخّص التحليل",
  "Make Summary →": "سوِّ ملخّص ←",
  "Generate Exam →": "ولّد اختبار ←",
  "Study Flashcards →": "ذاكر بالبطاقات ←",
  "Ask the Tutor →": "اسأل المعلّم ←",

  // Exam-readiness bar
  "This course is": "هذي المادة",
  "exam-ready": "جاهزة للاختبار",
  "— documents and past exams analyzed.": "— حلّلت المستندات والاختبارات السابقة.",
  "Upload lecture documents to start building practice exams.":
    "ارفع مستندات المحاضرات عشان نبدأ نجهّز اختبارات تجريبية.",
  "Add a past exam so generated exams match its format.":
    "أضف اختبار سابق عشان الاختبارات المولّدة تجي بنفس صيغته.",
  "Ready to generate practice exams.": "جاهز نولّد اختبارات تجريبية.",

  // Empty states
  "No recordings yet": "ما فيه تسجيلات لحين",
  "No documents yet": "ما فيه مستندات لحين",
  "+ Upload your first recording": "+ ارفع أول تسجيل لك",
  "Upload professor lecture recordings. The AI will transcribe them and extract exam hints.":
    "ارفع تسجيلات محاضرات الدكتور، ومُدرّس بيفرّغها ويطلّع لك تلميحات الاختبار.",

  // ---- Upload modals — Mudaris persona ----
  // Documents
  "Upload document": "ارفع مستند",
  "Upload documents": "ارفع مستندات",
  "Mudaris will read your document, analyze it, and pull out the key topics, definitions, and formulas.":
    "مُدرّس بيقرأ مستندك، يحلّله، ويطلّع لك أهم المواضيع والتعاريف والمعادلات.",
  // Past exams
  "Upload past exam": "ارفع اختبار سابق",
  "Upload past exams": "ارفع اختبارات سابقة",
  "Mudaris will study the past exam to learn its format, question types, and how marks are distributed.":
    "مُدرّس بيدرس الاختبار السابق عشان يتعلّم صيغته وأنواع أسئلته وكيف تتوزّع الدرجات.",
  // Tutorials
  "Upload tutorial": "ارفع تمرين",
  "Upload tutorials": "ارفع تمارين",
  "Mudaris will look at the tutorial problems and use their ideas to build exam-style questions.":
    "مُدرّس بيطّلع على مسائل التمرين ويستخدم فكرتها عشان يبني أسئلة على نمط الاختبار.",
  // Audio (already partly persona)
  "Upload lecture recordings": "ارفع تسجيلات المحاضرات",
  "Audio or video. We'll transcribe each one, summarize what the professor covered, and extract exam hints.":
    "صوت أو فيديو. مُدرّس بيفرّغ كل واحد، يلخّص اللي شرحه الدكتور، ويطلّع تلميحات الاختبار.",

  // Upload — shared UI
  "Upload files": "ارفع ملفات",
  "Paste video URLs": "الصق روابط فيديو",
  "Drop files or click to browse": "أفلت الملفات أو اضغط للاختيار",
  "Drop recordings or click to browse": "أفلت التسجيلات أو اضغط للاختيار",
  "Drop your recordings here": "أفلت تسجيلاتك هنا",
  "Fetch & Analyze": "اجلب وحلّل",
  "URLs detected · processed one at a time.": "روابط — تتحلّل وحدة وحدة.",
  "We fetch each video, extract the audio to MP3, and transcribe it.":
    "مُدرّس بيجلب كل فيديو، يطلّع الصوت MP3، ويفرّغه.",
  "select multiple": "تقدر تختار أكثر من ملف",
  "Recordings are analyzed one at a time — about 1–3 minutes each.":
    "التسجيلات تتحلّل وحدة وحدة — تقريبًا ١–٣ دقايق لكل وحدة.",
  "All recordings analyzed!": "تم تحليل كل التسجيلات!",
  "Analyzing your recordings…": "مُدرّس يحلّل تسجيلاتك…",
  "One recording at a time — please keep this open.":
    "وحدة وحدة — لا تسكّر هذي النافذة.",
  "Video URLs": "روابط الفيديو",
  "(one per line)": "(رابط في كل سطر)",
  "done": "خلصت",
  "failed": "فشل",
  "queued": "بالطابور",
  "Queued": "بالطابور",
  "Analyzing…": "يحلّل…",

  // ---- Status labels ----
  "Analyzed": "تم التحليل",
  "Transcribing…": "يفرّغ…",
  "Processing": "قيد المعالجة",
  "Failed": "فشل",
  "Pending": "بالانتظار",
  "Empty": "فاضي",
  "retry": "أعد المحاولة",
  "Queued…": "بالطابور…",
  "Downloading…": "يُنزّل…",
  "Converting to MP3…": "يحوّل لـ MP3…",
  // Item meta labels (counts) — the words only; topic names stay as-is
  "topics": "مواضيع",
  "chapters": "فصول",
  "questions": "أسئلة",
  "problems": "مسائل",
  "exam hints": "تلميحات اختبار",

  // ---- Multi-upload UI (documents / past exams / tutorials) ----
  "Upload & Analyze": "ارفع وحلّل",
  "Drop your files here": "أفلت ملفاتك هنا",
  "Files are analyzed one at a time — about 15–30 seconds each.":
    "الملفات تتحلّل وحدة وحدة — تقريبًا ١٥–٣٠ ثانية لكل وحدة.",
  "Tutorials add problem ideas only — analyzed one at a time, ~15–30s each.":
    "التمارين تضيف أفكار المسائل بس — تتحلّل وحدة وحدة، تقريبًا ١٥–٣٠ ثانية.",
  "Mudaris is analyzing…": "مُدرّس يحلّل…",
  "Finished with some issues": "خلص بس فيه أخطاء",
  "All files analyzed!": "تحلّلت كل الملفات!",
  "Now": "الحين",
  "in progress…": "جاري…",
  "Done — closing…": "خلص — بنسكّر…",
  "One file at a time — please keep this open.":
    "وحدة وحدة — لا تسكّر هذي النافذة.",

  // Step labels — documents
  "Uploading document": "يرفع المستند",
  "Extracting text": "يستخرج النص",
  "Analyzing concepts & definitions": "يحلّل المفاهيم والتعاريف",
  "Identifying formulas & key terms": "يحدّد المعادلات والمصطلحات",
  "Mapping chapters & topics": "يربط الفصول والمواضيع",
  // Step labels — past exams
  "Uploading exam": "يرفع الاختبار",
  "Reading exam pages (text + images)": "يقرأ صفحات الاختبار (نص + صور)",
  "Identifying question types": "يحدّد أنواع الأسئلة",
  "Weighting topics & difficulty": "يوزّن المواضيع والصعوبة",
  "Building grading blueprint": "يبني مخطط التصحيح",
  // Step labels — tutorials
  "Uploading tutorial": "يرفع التمرين",
  "Reading problems (text + images)": "يقرأ المسائل (نص + صور)",
  "Identifying topics covered": "يحدّد المواضيع المغطّاة",
  "Capturing worked-problem ideas": "يلتقط أفكار المسائل المحلولة",
  "Linking ideas to the exam generator": "يربط الأفكار بمولّد الاختبار",

  // ---- Course page: study-tool cards ----
  "AI Coach": "المعلّم الذكي",
  "Chat with a coach grounded in your documents, recordings, and past exams.":
    "دردش مع معلّم يعتمد على مستنداتك وتسجيلاتك واختباراتك السابقة.",
  "Ask the Coach": "اسأل المعلّم",
  "An AI exam from your documents, matched to your past exams.":
    "اختبار ذكي من مستنداتك، مطابق لاختباراتك السابقة.",
  "Generate Exam": "ولّد اختبار",
  "Study cards weighted by past exams and lecture emphasis.":
    "بطاقات موزونة حسب الاختبارات السابقة وتركيز المحاضرات.",
  "Make Flashcards": "سوِّ بطاقات",
  "A structured study summary, focused on what your exams test.":
    "ملخّص منظّم يركّز على اللي تختبر فيه.",
  "Make Summary": "سوِّ ملخّص",
  "Audio": "الصوتيات",
  "Practice problems. The exam generator reuses their ideas (with different numbers) — no marks or format weighting.":
    "مسائل تدريبية. مولّد الاختبار يعيد استخدام أفكارها (بأرقام مختلفة) — بدون احتساب درجات أو صيغة.",

  // Course page: preview headings
  "Top Exam Topics": "أبرز مواضيع الاختبار",
  "Practice Problems · likely to reappear with new numbers":
    "مسائل تدريبية · غالبًا ترجع بأرقام جديدة",
  "Exam Hints": "تلميحات الاختبار",

  // Course page: empty states
  "No past exams yet": "ما فيه اختبارات سابقة لحين",
  "No tutorials yet": "ما فيه تمارين لحين",
  "Upload lecture PDFs, slides, or Word docs. The AI will extract topics, definitions, and formulas.":
    "ارفع ملفات المحاضرات PDF أو شرائح أو وورد، ومُدرّس بيطلّع المواضيع والتعاريف والمعادلات.",
  "Upload old exam PDFs. The AI will analyze topic weights, question patterns, and difficulty distribution.":
    "ارفع ملفات اختبارات قديمة، ومُدرّس بيحلّل أوزان المواضيع وأنماط الأسئلة وتوزيع الصعوبة.",
  "Upload tutorial / exercise sheets. The AI learns how topics are applied so generated exams mirror those problem ideas.":
    "ارفع أوراق تمارين، ومُدرّس يتعلّم كيف تُطبّق المواضيع عشان الاختبارات تجي على نفس أفكار المسائل.",
  "Upload your first document": "ارفع أول مستند لك",
  "Upload your first past exam": "ارفع أول اختبار سابق",
  "Upload your first tutorial": "ارفع أول تمرين لك",
  "Upload your first recording": "ارفع أول تسجيل لك",

  // ---- Weekly schedule ----
  "This week": "هذا الأسبوع",
  "Sunday to Thursday lecture calendar.": "جدول المحاضرات من الأحد إلى الخميس.",
  "Add lecture": "أضف محاضرة",
  "Edit lecture": "تعديل المحاضرة",
  "Lecture": "محاضرة",
  "Sun": "أحد",
  "Mon": "إثنين",
  "Tue": "ثلاثاء",
  "Wed": "أربعاء",
  "Thu": "خميس",

  // ---- Landing page ----
  "AI · Built for Saudi Students": "ذكاء اصطناعي · مصمَّم لطلاب السعودية",
  "Your lectures,": "محاضراتك،",
  "finally": "أخيرًا",
  "unforgotten.": "ما تنّساها.",
  "Mudaris turns your lecture documents, recordings, and past exams — in Arabic, English, or both — into structured summaries, full practice exams, smart flashcards, and an AI coach that actually knows your material.":
    "مُدرّس يحوّل مستندات محاضراتك وتسجيلاتك واختباراتك السابقة — بالعربي أو الإنجليزي أو الاثنين — إلى ملخّصات منظّمة، واختبارات تجريبية كاملة، وبطاقات ذكية، ومعلّم ذكي يعرف مادتك فعلاً.",
  "Go to Dashboard": "روح للوحة",
  "Get started — it's free": "ابدأ — مجانًا",
  "How it works": "كيف يشتغل",
  "Summary · Generated": "ملخّص · تم توليده",
  "Neural Networks": "الشبكات العصبية",
  "Key concept: backpropagation adjusts weights by computing gradients from the output layer backward through the network…":
    "فكرة أساسية: الانتشار العكسي يعدّل الأوزان بحساب التدرّجات من طبقة الإخراج رجوعًا عبر الشبكة…",
  "Practice Exam · Midterm · 24 questions": "اختبار تجريبي · نصفي · ٢٤ سؤال",
  "What is the role of an activation function?": "وش دور دالة التفعيل؟",
  "A) To initialize weights": "أ) تهيئة الأوزان",
  "B) To introduce non-linearity ✓": "ب) إضافة اللاخطية ✓",
  "C) To reduce overfitting": "ج) تقليل فرط التطابق",
  "Flashcard · 3 of 24": "بطاقة · ٣ من ٢٤",
  "CNN": "الشبكة الالتفافية (CNN)",
  "Convolutional Neural Network — a deep learning architecture specialized for processing grid-like data such as images.":
    "الشبكة العصبية الالتفافية — معمارية تعلّم عميق متخصّصة في معالجة البيانات الشبكية مثل الصور.",
  "Hours saved per term": "ساعات توفّرها كل فصل",
  "Avg processing time": "متوسط وقت المعالجة",
  "Bilingual support": "دعم لغتين",
  "Exam confidence ↑": "ثقة بالاختبار ↑",
  "Capabilities": "الإمكانيات",
  "One recording. Everything you need.": "تسجيل واحد. كل اللي تحتاجه.",
  "Bilingual Transcription": "تفريغ بلغتين",
  "Drop in lecture recordings — Arabic, English, or the natural mix. Whisper transcribes them and the AI surfaces exam hints, emphasized concepts, and chapter breakdowns.":
    "ارفع تسجيلات المحاضرات — عربي أو إنجليزي أو خليط طبيعي. يفرّغها ويطلّع لك تلميحات الاختبار والمفاهيم اللي ركّز عليها وتقسيم الفصول.",
  "Structured Summaries": "ملخّصات منظّمة",
  "Your chapters become key concepts, definitions, and formulas — with each section tagged high / medium / low likelihood for the exam, based on your past papers.":
    "فصولك تصير مفاهيم وتعاريف ومعادلات — وكل قسم معلّم باحتمال عالي / متوسط / منخفض للاختبار، حسب اختباراتك السابقة.",
  "Generate full Quiz, Midterm, or Final practice papers that match the format of your real past exams. Download the PDF, or answer in-app and get auto-graded with explanations.":
    "ولّد اختبارات كويز أو نصفي أو نهائي كاملة تطابق صيغة اختباراتك الحقيقية السابقة. نزّل الـPDF، أو جاوب داخل التطبيق وشوف نموذج الإجابة.",
  "Smart Flashcards": "بطاقات ذكية",
  "Cards auto-built from your documents — weighted toward the topics your past exams emphasize, so you study what's actually likely to show up.":
    "بطاقات تُبنى تلقائيًا من مستنداتك — موزونة نحو المواضيع اللي تركّز عليها اختباراتك السابقة، عشان تذاكر اللي فعلاً غالب يجي.",
  "AI Chat Coach": "معلّم ذكي بالمحادثة",
  "Pick which chapters, recordings, and past exams to ground the conversation in, then ask anything — explanations, quick quizzes, exam tips — in Arabic or English.":
    "اختر الفصول والتسجيلات والاختبارات السابقة اللي يعتمد عليها، وبعدها اسأل أي شي — شرح، كويز سريع, نصايح للاختبار — بالعربي أو الإنجليزي.",
  "Past-Exam Intelligence": "تحليل الاختبارات السابقة",
  "Upload old exams once. Mudaris extracts topic weights, question patterns, and difficulty — and uses them to shape every summary, flashcard, exam, and coach reply.":
    "ارفع الاختبارات القديمة مرة وحدة. مُدرّس يطلّع أوزان المواضيع وأنماط الأسئلة والصعوبة — ويستخدمها في كل ملخّص وبطاقة واختبار ورد من المعلّم.",
  "Stop re-listening. Start mastering.": "بس إعادة سماع. ابدأ تتقن.",
  "Open Dashboard": "افتح اللوحة",
  "Get Started Free": "ابدأ مجانًا",
  "Mudaris © 2026 · Built with ♥ in Riyadh": "مُدرّس © ٢٠٢٦ · صُنع بحب في الرياض",

  // ---- Generic ----
  "Loading…": "جاري التحميل…",
  "Saving…": "جاري الحفظ…",
  "title": "العنوان",
  "Title": "العنوان",
  "optional": "اختياري",
};
