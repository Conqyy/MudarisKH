# Mudaris course workspace UI redesign

- Date: 24 October 2026
- Branch: `codex/ui-redesign`
- Source baseline: `bcf3612497ecf3d9e8de213c4796a7beac04c23e`
- Status: approved by the owner and implemented on the redesign branch. Local visual review remains pending before merge or production delivery.

## 1. Agreed intent and scope

The owner wants a complete, fresh Mudaris interface with the same functionality, using [Customer Journey CRM Dashboard by Jack R. / RonDesignLab](https://dribbble.com/shots/24659454-Customer-Journey-CRM-Dashboard) as the visual and experience reference. The owner explicitly excludes influence from the current colors, typography, textures, and design language, and selected the **course workspace with a journey overview** approach.

Success means a professional, clean, information-rich study workspace with consistent navigation and controls across all 15 existing page routes. Existing academic workflows, data, generation behavior, permissions, language support, themes, and recovery paths remain intact. The redesign changes how those functions are presented and reached.

The reference supplies the composition and visual grammar: a slim icon rail, horizontal labeled navigation, a cool layered canvas, rounded modules, circular utility controls, dark active pills, restrained pastel depth, and a connected workflow. Its CRM-specific features and decorative browser/device frame are not Mudaris requirements. The public shot is a visual reference, not evidence of working interactions or responsive behavior; the behavior below is explicitly designed for Mudaris.

Design decisions developed here retain the Mudaris product name, provide a newly typeset wordmark, and apply the new system to landing/authentication pages as well as the authenticated workspace. No existing mascot or legacy design asset is required.

## 2. Functional boundary

### Included presentation changes

- Replace global visual tokens, fonts, icon treatment, surfaces, spacing, and motion.
- Introduce one shared authenticated shell and course navigation.
- Separate the existing course root into Overview and Materials views.
- Build consistent presentation primitives for actions, fields, dialogs, status, source selection, material lists, and feedback.
- Restyle all existing study configuration, reading, planning, activity, and account experiences.
- Normalize accessible names, focus behavior, mixed-language content direction, and preference adoption where required by the new presentation.
- Improve interface wording to describe existing operations accurately.

### Preserved product behavior

No changes to backend endpoints, request/response schemas, Firestore collections, source preparation or analysis, AI agents/prompts/models, academic scope rules, generation defaults/limits, authentication/ownership, versioned evidence, or deletion semantics. No data migration is required.

Do not add unsupported global search, notifications, collaboration, analytics, mastery tracking, automatic grading, recording playback, streamed tutor responses, or new generation jobs. Every rendered action must operate an existing feature or the navigation needed to expose it. Existing placeholder feedback navigation may be omitted rather than suggesting a working feedback form.

## 3. New visual system

### 3.1 Palette and material

The following values are proposed production tokens derived from the reference's visual character; they are not claimed to be exact sampled colors.

| Role | Light | Dark | Use |
| --- | --- | --- | --- |
| Canvas | `#F1F3F8` | `#11141C` | Main workspace field. |
| Surface | `#FFFFFF` | `#1A1F2B` | Main functional panels and reading surfaces. |
| Recessed surface | `#EAEEF6` | `#151A25` | Grouping and quiet control backgrounds. |
| Primary text | `#161923` | `#F2F4FA` | Titles, body text, values. |
| Secondary text | `#586174` | `#A8B2C5` | Supporting information with normal-text contrast. |
| Border | `#DCE1EC` | `#333D52` | Decorative separators and panel boundaries. |
| Control border | `#7B8599` | `#67758F` | Essential field/control boundaries; check against the actual surface. |
| Active/primary control | `#000000` | `#F2F4FA` | Selected pills and primary actions; contrasting text. |
| Periwinkle depth | `#E3E9FC` | `#252F50` | A restrained broad wash behind the journey and selected contextual groupings. |
| Interactive accent | `#435CC4` | `#B2C2FF` | Links, focus, selected-source indication. |

Status pairs use dark readable text on quiet fills: success `#196445` / `#E5F4EC`, warning `#825000` / `#FFF2D8`, danger `#AC303E` / `#FCECEF`, and information `#354DA8` / `#EAF0FF`. Dark-mode status text/fills are success `#93DDB7` / `#17372B`, warning `#F0CA83` / `#3B2F19`, danger `#FFAFB8` / `#3D222B`, and information `#B2C2FF` / `#253252`. Verify contrast in their actual states during implementation, including opacity and disabled controls.

Use solid or lightly tinted surfaces and restrained cool shadows. A single gentle cool-to-periwinkle workspace wash supplies depth; it does not appear independently inside every module. Normal panels do not require backdrop blur. Existing uploaded imagery and document evidence remain unaltered.

Persisted course colors remain unchanged in data. Present them through small identity markers rather than letting arbitrary stored colors determine panel fills or text contrast. New-course choices use a fresh six-color set: blue `#526BCB`, violet `#8267B9`, cyan `#278A9B`, green `#45806C`, amber `#B17B2A`, rose `#B46381`. These colors identify courses and carry no readiness meaning.

### 3.2 Typography and icons

- Latin interface: **Manrope**, regular/medium/semibold. Arabic interface: **Alexandria**, with equivalent semantic roles and appropriate line height. Use licensed font files and dependable sans-serif fallbacks.
- Page title: 30px/38px, semibold; compact-screen title: 26px/34px. Section title: 18px/26px, semibold. Body: 14–16px with 1.5–1.65 line height. Labels/metadata: 12–13px with readable contrast. Arabic body starts at 15px and uses extra vertical room where needed.
- Use one stable root text size; no viewport-wide root-size scaling that unexpectedly changes all geometry. Use tabular numerals for counts, times, and processing values.
- Interface text uses sentence case. Content headings retain their source language and hierarchy. Monospace is reserved for actual code in academic content.
- Use one consistent 1.5–1.75px stroke SVG icon family through a shared wrapper. Circles and rounded squares are control containers, not a reason to mix unrelated icon styles. Replace decorative emoji in product navigation/status with named icons.
- The wordmark uses the new interface type and a simple document-stack mark. It remains legible as “Mudaris”; logo exploration is outside this redesign.

### 3.3 Geometry

- Desktop compact rail: 72px; expanded labeled rail: 224px. Context header: 72px. Course tab row: approximately 48px, content-dependent rather than clipping labels.
- Workspace gutters: 24px; mobile: 16px. Module gaps: 16–24px. Main content ceiling: 1440px, centered within available workspace. Reading measures: normally 60–80 characters, with horizontally scrollable tables/code when needed.
- Major modules: 24px corners; standard panels/dialogs: 18px; control groups: 12px; pills and circular icon tools use their intrinsic shape. Avoid nesting identical large cards for every subsection.
- Standard control height: 44px. Compact row controls may have a smaller visible glyph/container but retain a 44px hit area without overlapping neighboring targets.
- Use subtle panel depth and fine dividers. Strong outlines/fills communicate selection, focus, failure, and primary actions.

### 3.4 Motion

Use motion to show a user's state change or explain spatial relationships. Repeated navigation, typing, source selection, and keyboard-initiated actions remain immediate.

| Interaction | Treatment |
| --- | --- |
| Pointer press | Up to 120ms, optional scale to 0.98 on appropriate standalone buttons. |
| Hover/color | 120–160ms, exact properties, movement only for hover-capable fine pointers. |
| Small popover | 140–180ms opacity/transform; origin at its trigger. |
| Dialog or evidence drawer | 180–240ms; exit equal or shorter; modal origin stays centered, drawer origin follows inline end. |
| Card reveal | At most 180ms subtle opacity/transform for pointer activation; keyboard activation is immediate. Front/back data and focus semantics remain distinct. |
| Processing | Indeterminate activity when no measured progress exists; actual server phase/count only when supplied. |

Use a consistent ease-out curve such as `cubic-bezier(0.23, 1, 0.32, 1)` for occasional entrances. Respect reduced motion with gentle opacity feedback and no positional/flip motion. No continuous decorative motion in the study workspace. Do not animate sidebar width or other layout dimensions on each toggle.

## 4. Information architecture and shell

### 4.1 Global navigation

The rail exposes Dashboard, Courses (a shortcut to the dashboard's course section), Recent, and Bookmarked. Settings and account/preferences remain at the bottom or in the named account menu. The compact rail includes accessible names and focus/hover tooltips; the expansion action reveals labels. Existing course switching remains available through the contextual course selector and the expanded navigation.

The context header shows the page or course identity, a breadcrumb/back destination where useful, and the applicable existing actions. Language, theme, and account are reachable at every authenticated viewport. Weekly schedule remains discoverable on Dashboard, with a named shortcut to its section. The reference's unused search, inbox, and bell controls are not copied.

Honor saved `mudaris_sidebar` values. On a device with no saved value, use the new compact rail as a presentation default; expanded/collapsed choices persist only through explicit user changes. This new unconfigured default is an intentional presentation choice, not a storage migration.

### 4.2 Course navigation and compatible URLs

Every course workspace has labeled destinations: **Overview, Materials, Exams, Flashcards, Summaries, Tutor**. “Exams” in the course navigation means generated practice exams; uploaded past papers live in Materials and remain clearly titled Past exams.

| Destination | URL behavior |
| --- | --- |
| Overview | `/course/[id]` |
| Materials | `/course/[id]?view=materials` (new presentation query only) |
| Exams | Existing `/course/[id]/exam` and saved child route |
| Flashcards | Existing `/course/[id]/flashcards`, including `?flashcards=ID` |
| Summaries | Existing `/course/[id]/summary`, including `?summary=ID` |
| Tutor | Existing `/course/[id]/tutor` |

Existing `?doc=ID`, `?audio=ID`, and `?section=documents` reveal Materials and the requested item/section after data loads. These legacy selectors take precedence over the default Overview presentation. Preserve supplied IDs and ordinary browser back/forward behavior. New tab navigation must not manufacture document/audio/saved-output activity events.

Views share course identity and existing ownership/readiness checks. A source/evidence overlay does not navigate away from the current reading position. Normal navigation between tool routes keeps current page lifecycle semantics; this project does not introduce cross-route draft or source-selection persistence. Overlay/view changes within a mounted tool must not accidentally clear its existing selections.

### 4.3 Desktop structure

```text
┌──────┬───────────────────────────────────────────────────────────┐
│      │ Course context                    Language  Theme Account │
│ Rail ├───────────────────────────────────────────────────────────┤
│      │ Overview  Materials  Exams  Flashcards  Summaries  Tutor   │
│      ├───────────────────────────────────────────────────────────┤
│      │ Title / status                              Main action   │
│      │                                                           │
│      │       Lecture foundation → Confirm → Study tools          │
│      │                              ↗ Optional support           │
│      │                                                           │
│      │ Reminders / recent items          Course information      │
└──────┴───────────────────────────────────────────────────────────┘
```

This is a hierarchy diagram, not a requirement to place every screen into the same card grid. Material management, tutoring, and long-form reading each use layouts suited to their tasks.

## 5. Screen designs

### 5.1 Dashboard

Show a compact welcome/context row, New course action, a quiet strip of the existing four counts, then courses as the main navigation surface. Use balanced course modules with title/code/instructor, small color identity, real counts, bookmark/open actions where already applicable, and an accessible actions menu for archive/delete. Archived courses remain a clearly separated reveal with restore.

The next region contains existing reminders and the Sunday–Thursday weekly timetable. On wider screens reminders can sit alongside the timetable; smaller screens stack them. A compact Recently opened module may surface existing device-local activity, labeled accurately rather than implying saved study position or mastery. It links to the existing Recent page and does not invent progress.

Courses remain usable while optional statistics load. Empty account, archived-only, course-fetch failure, statistics failure, mutation failure, and retries have distinct presentations. A failure in statistics must not make existing courses appear absent.

### 5.2 Course Overview and the journey

Header: course code/title/instructor, bookmark, Edit course, and the current deletion action in an accessible menu. Archive/restore remains available from dashboard course management. Provide a clear back-to-dashboard destination.

The distinctive module is a connected readiness journey:

1. **Lecture foundation:** document count and preparation/analysis status, with Upload, View documents, or relevant retry actions.
2. **Confirm lectures:** explicit confirmation of the exact completed revision; never automatically checked by the diagram.
3. **Study tools:** the four existing destinations, with authoritative eligibility and readable blocked guidance.

Supporting materials form an optional branch from confirmed lectures into study. They are not a required sequential step. “Ready to study” follows foundation readiness, not the presence of a past paper. There is no completion percentage for “all course knowledge” and no user-draggable workflow editor.

The journey summarizes `missing`, `processing`, `failed`, `confirmation_required`, and `ready`; loading/error remains locked with a useful retry path. Adding/deleting/retrying lecture documents invalidates the displayed confirmation normally. The node action opens the exact relevant Materials section, uploader, or existing retry flow.

Below the journey, retain course reminders and intelligence counts/available analysis signals. Surface only values actually provided by existing data. Do not use decorative accuracy, prediction-confidence, time-saved, or learning-progress metrics.

### 5.3 Materials

Use one coherent material library with four named groups: Lecture documents, Past exams, Tutorials, and Recordings & notes. On desktop, compact group navigation can accompany the material list; on mobile it becomes a named group selector or horizontally scrollable labeled tabs. Switching the view does not reset data or reinterpret material categories.

Each group has its own upload action and restrictions. Past exams retain Quizzes/Midterms/Finals plus Needs classification, the owner-selected upload type, and explicit legacy classification. Notes and URL intake remain available through the recording dialog's existing modes.

Keep the current frontend intake limits: lecture PDF/PPTX/DOCX at 100 MiB; past-exam PDF/supported images and tutorial PDF/PPTX/DOCX at 50 MiB; recording MP3/WAV/M4A/MP4/MOV at 300 MiB; typed notes at a 20-character minimum. Retain existing supported media-URL handling and the stated document bounds of 160 pages/slides and 600,000 extracted characters. Do not silently replace these UI limits with the backend's different upload caps.

Rows prioritize title and meaningful status. Show type/location/date details secondarily; keep open/report, rename, drag reorder, keyboard up/down, delete, preparation/reanalysis/retry, and relevant classification actions. Secondary operations may use a row menu, but keyboard reorder remains directly discoverable. Honor saved ordering/title overrides in every consumer. Preserve real queued/incomplete/failed/stale/legacy/missing states.

Upload dialogs use the new common shell and accessible file-browse/drop target. Preserve current file types, frontend size limits, required classification, duplicate handling, sequential submission, busy close restrictions, polling, retry identity, and completion/automatic-close conditions. Presentation must not claim a background supporting upload is already analyzed or imply it is safe to abandon a lecture batch that currently requires the dialog open.

### 5.4 Shared study configuration

Exam, flashcard, and summary pages share a recognizable configuration structure: tool title and saved-library access; source selection; tool-specific options; a clear generation action with applicable readiness/blocker feedback. This is a shared visual contract, not a replacement request abstraction that normalizes different tool semantics.

At wide sizes use a source column around 300–340px and a flexible options area. On narrow screens, source groups stack above options or open in a named source-selection overlay with a visible selection summary. Keep course, lecture count, supporting choices, and any past-exam category inspectable before generation. Do not add a persistence layer for selections.

Show readiness next to selected material. A selected item that becomes missing/stale/incomplete remains a visible blocker until refreshed or deselected. Preserve explicit-empty versus omitted selections, the lecture minimum for the three generators, and the tutor's confirmed-foundation fallback exception.

Exam and summary keep their default Final category and category-isolated requests; changing category clears historical choices/cancels old reads while preserving lecture choices. Flashcards/tutor retain their broader historical-material selection behavior.

Generation uses honest “Generating…” feedback without fabricated percentages or timers presented as server stages. Saved-item opening uses “Opening…” or a content skeleton. Existing errors retain their relevant source/gate information and retry paths.

### 5.5 Exams

Retain the existing type, 5–40 marks in increments of five (default 40), optional topics/instructions, supporting selections, generation, saved list, and deletion. Present saved items as practice exams with dates/types and actual available metadata. Do not describe an active grading/submission feature.

The saved exam reader has a focused document toolbar and generous PDF region. Preserve preview/download, solution upload/replace, explicit answer reveal, answer PDF download, citations, bookmarks, and independent loading/error/retry states. The exam's saved document ID remains the PDF/detail identity.

At wide widths, comparison uses the existing exam/solution and model-answer panes. On small screens expose named document tabs so each remains accessible without forcing two narrow PDFs. Preserve current transitions of which document is shown after solution attachment or answer reveal; the redesign does not silently reveal answers or generate AI repair on a detail read.

### 5.6 Flashcards

Keep 5–20 cards, default 15, saved decks, generation/deletion, front/back, topic/evidence, previous/next, Done/Exit, and bookmarks. The study view has one central readable card, count indicator, clearly named reveal/navigation actions, and visible citations for the current side only.

Use a restrained reveal rather than a prolonged flip. A zero-card response gets an honest empty-result message and a return to configuration rather than an empty screen; no new generation request occurs automatically. Saved sets still start at card one. Do not introduce remembered study position, grading, or mastery tracking.

### 5.7 Summaries

Retain custom instructions, sources, saved library, generation/delete, bookmark, PDF export and browser-print fallback. The reader uses a contents rail at wide sizes and a compact contents menu on mobile, with a readable central column. Overview, focus, sections, key points, and terms retain their respective source provenance.

Academic text, tables, formulas, and code can expand appropriately. Content is not forced into equal-height dashboard tiles. Preserve export busy/error feedback, blocked-popup guidance, and source-version failures.

### 5.8 Tutor

Preserve existing saved-chat history, new/open/delete, suggested prompts, source control, full response rendering, Markdown/citations, pending draft recovery, and fullscreen behavior. Desktop has a collapsible history region and central conversation. Sources open in a contextual panel rather than permanently compressing all content into three columns.

The composer displays a clear send affordance, busy/error state, and source summary. Enter sends; Shift+Enter inserts a newline. Escape exits fullscreen or the active dismissible overlay, with one predictable focus owner. Do not fake streaming or retain stale replies after a chat/course/account change.

On mobile, history and sources are explicit views/overlays with accessible return actions. Preserve the current foundation gate, including its effect on visible tutor history; lifting that gate would be a separate behavior decision.

### 5.9 Source viewers and reports

Documents, supporting reports, and citation previews share a consistent evidence shell but keep distinct content models. Desktop evidence opens at inline end in a bounded inspector, around 420–480px where reading space permits; narrow layouts use a full-width dialog. Long document reading can expand to a full reader. A newly opened overlay never substitutes current source content for a saved revision.

Document tabs preserve Lightweight analysis/legacy Analysis, PDF Content, and prepared Source units as applicable. Expose extraction warnings through a visible summary/disclosure so useful guide content is reachable, while retaining every warning and exact source link. Office files show their actual prepared units and preparation guidance.

Supporting reports retain saved stale reports, distinct extraction/alignment/coverage, paper grouping, requirements/shared context, finding categories, pagination and retry. No evidence classification is collapsed into a misleading binary covered/uncovered label. Citation original-file access, authenticated images/PDFs, genuine audio timestamps, student-note attribution, unavailable versions, and exact response-identity checks remain intact.

Audio reading remains analysis/transcript/report/PDF export; no unsupported playback UI is drawn. Keep bookmarks and all current analysis sections.

### 5.10 Calendar, reminders, activity, and settings

- **Calendar:** recurring Sunday–Thursday timetable, current time expansion and overlap validation, multi-day add with partial failure recovery, edit/delete. Preserve its horizontal scrolling where a legible grid cannot fit. Form fields have associated labels and explicit validation. Failure feedback remains visible without implying a successful delete.
- **Reminders:** existing title/type/date/time/notes/done, ordering/due labels, add/edit/delete/complete, and dashboard aggregation. Keep mutation conflicts and failed saves recoverable. No alarm or notification promises.
- **Recent/Bookmarked:** compact lists grouped by existing activity kinds, correct deep links, remove/clear/unstar actions, empty states, and device-local wording. These are not cloud libraries.
- **Settings:** independent Profile, Email, Password, and Account action sections; preserve provider-specific behavior, validation, verification-sent state, reauthentication and destructive confirmations. Danger actions are distinct and never grouped with an ordinary primary Save action.

### 5.11 Public entry and retired route

The homepage introduces the actual sequence: lecture materials, confirmed course foundation, then study outputs. Use the same cool visual system and a focused course-workspace preview built from clearly illustrative content. Prioritize a direct account-aware CTA, concise product explanation, four study tools, source-evidence benefits, and bilingual support. Avoid unsupported product claims or decorative activity statistics.

Sign-in, two-step signup, and password reset share a quiet branded entry shell with the same fields/providers/actions, validation, busy, error, and success states. Keep optional academic information optional. No new signup requirement or credential flow is introduced.

The retired `/lecture/[id]/processing` route remains an authenticated notice with a working Dashboard destination, restyled consistently.

## 6. Responsive, language, and accessibility rules

| Width | Behavior |
| --- | --- |
| 1280px and above | Compact/expanded rail, course tabs, full journey connections, suitable two-column dashboard/configuration layouts, optional bounded evidence inspector. |
| 768–1279px | Compact rail by default when unconfigured; labeled course navigation; reflow journey/configuration modules as required; evidence overlays content if a separate pane would make the reader too narrow. Honor explicit saved expansion without clipping the workspace. |
| Below 768px | Replace persistent rail with an accessible navigation drawer; keep course identity, account/preferences, and named tab navigation reachable. Use one main column, 16px gutters, full-width evidence/dialog layouts, and safe-area-aware fixed controls where present. |

Course tabs may scroll horizontally while showing complete labels; selection stays visible and keyboard reachable. The page itself must not overflow horizontally, except intentional calendar/table/code/PDF regions. Fit interactive states at 360px minimum viewport width.

Use logical inline/block layout properties throughout, including borders, sticky offsets, connectors, drawers, and spacing. Mirror navigation and journey direction in Arabic. Apply automatic direction to mixed academic content where appropriate; retain intentional LTR islands for code, URLs, and identifiers. Existing English fallback text remains understandable; all newly introduced interface strings receive Najdi Arabic translations.

Preserve `mudaris_lang`, `mudaris_theme`, and `mudaris_sidebar`. Pre-paint adoption must agree with provider initial state; hydration must not persist a default over a saved choice. Explicit controls persist changes. Keep original preference APIs unless a compatibility wrapper is necessary.

Use semantic links/buttons, named icon tools, selected/current navigation state, visible keyboard focus, associated form labels, and keyboard-operated browse/reorder. A shared dialog contract owns focus trap, Escape/backdrop rules, scroll locking, and return focus; busy upload restrictions take precedence. Nested evidence uses a single active focus owner. Status is communicated through text/icons as well as color. Target normal text at 4.5:1 and meaningful non-text indicators/control boundaries at 3:1.

## 7. Component and data architecture

Keep presentation modules focused and independent of backend persistence:

| Unit | Responsibility and input boundary |
| --- | --- |
| Semantic tokens / typography | Theme values, type roles, spacing, control/surface states. No data logic. |
| UI primitives | Button/IconButton, Field, StatusBadge, Tabs/navigation links, Menu, Dialog/Drawer, feedback and loading/empty states. Explicit behavior props; no domain fetches. |
| AppShell | Global rail/header, account/preferences, responsive navigation and content geometry. Consumes existing auth/preference/course data supplied through established ownership paths. |
| CourseWorkspaceHeader | Course identity, switcher, course actions and URL-based destinations. Does not independently widen material fetches or generate work. |
| CourseJourney | Maps authoritative foundation/support status to current labels and existing callbacks. No invented readiness state machine. |
| MaterialGroup / MaterialRow | Domain-aware presentation of existing items, status, ordering, actions and errors. Persistence remains in existing mutations. |
| SourceSelectionPanel | Shared presentation with explicit tool-specific inputs, selected IDs, category and blocker callbacks. Preserves differences between tools. |
| StudyLibrary / ReaderToolbar | Displays actual saved items and existing actions; does not manufacture progress or IDs. |
| EvidenceShell | Shared geometry/focus/scroll treatment around existing revision-validated lecture/support viewers. Does not merge citation identities. |

Continue using the current provider order, authenticated `apiFetch`, hooks, Firebase ownership paths, version checks, and cancellation protections. Extract visual wrappers before relocating data ownership. Avoid introducing a new global store/query library or backend facade merely for styling. An icon/font dependency can be considered in the implementation plan only if it reduces maintenance and remains accessible.

## 8. Preservation checklist

The implementation plan must map each existing action/state to its new destination and retain these contracts:

1. All existing routes/deep links and browser history work after the course-tab split.
2. Foundation gates and exact-revision confirmation apply to course actions and direct study routes. Optional support does not become mandatory. Saved exams/cards/summaries remain accessible under existing rules.
3. Original preparation and guide creation are distinct; supporting acceptance/completion and stale/legacy/missing states remain truthful. Polling, retries, report identities, and pagination remain intact.
4. `null`/omitted source lists mean all, `[]` means none, invalid IDs reject. Preserve the generator lecture minimum and tutor fallback exception.
5. Quiz/Midterm/Final classification and category isolation remain unchanged, including cancellation and preserved lecture selection when category changes.
6. Exact source revisions, original access, per-claim/per-side/per-message provenance, and publication checks remain intact. Saved citations never substitute replacements.
7. Late responses cannot cross account/course/item/chat boundaries; object URLs/controllers are cleaned up; unchanged readiness refreshes do not cancel ongoing work.
8. Reorder/title/reminder updates preserve conflict behavior; archive/restore and failed cascade deletion retain their existing data semantics.
9. Keep `mudaris.recent.${uid}`, `mudaris.bookmarks.${uid}`, existing activity kinds/IDs/hrefs/timestamps, 30-item recents cap, and `mudaris:activity` synchronization. No fake activity events or cloud-sync claim.
10. Preserve auth forms, provider-specific account actions, recent-auth checks, server deletion-before-local cleanup, and failed-operation recovery.
11. Preserve generation limits/defaults and all saved-item actions, answer reveal, solution attachment/comparison, PDF/export fallback, and source-version errors. No automatic new AI action when reading a result.
12. Keep calendar/reminders as separate data models; no new notification, progress-tracking, grading, playback, or collaboration capability.

## 9. Acceptance and verification

### Functional regression

Use the existing frontend suite (baseline previously observed: 14 files / 208 tests) and relevant navigation, foundation, upload, selection, citation, async, ordering, account, and report regressions. Add focused tests only for newly introduced behavior boundaries such as URL-to-Materials compatibility, navigation accessibility, and dialog ownership. Do not rewrite tests merely to match visual markup.

Run frontend lint, TypeScript checks, tests, and an isolated production build. Keep backend unchanged; if an implementation unexpectedly requires backend changes, stop and revise scope before editing it. Run any relevant backend regression checks if shared contracts are affected despite the intended frontend-only scope.

### Visual and interaction acceptance

- Review rendered screens at 360/390, 768, 1024, 1440, and 1920px where available; use at least a small laptop and a phone-width layout for every distinct layout family.
- Review English/light, English/dark, Arabic/light, and Arabic/dark, including reload preference adoption.
- Inspect all 15 routes and major dialogs/readers, using real existing data where safe and clearly labeled fixtures where necessary. No fabricated user analytics.
- Check empty/loading/error/locked/ready, partial upload failure, stale/missing support, legacy classification, long names, many materials, mixed-language content, and unavailable citations.
- Verify keyboard navigation, focus return, browse/drop targets, source selection, reorder, busy restrictions, reduced motion, and touch target behavior. Record any physical-device gap honestly.
- Compare the new shell, panel hierarchy, density, typography, active pills, circular controls, and restrained cool depth against the supplied reference. Judge individual study/readers on legibility as well as coherence.
- Inspect browser console errors. Live model generation or destructive account/data actions require appropriate configured test data and existing authorization; passing stubbed tests is not proof of a live AI round trip.

### Delivery boundary

This specification defines the entire redesign across shared foundations, course/dashboard, study tools/readers, and remaining screens. Sequencing does not remove any page from scope. The owner approved implementation with “do it”; the implementation plan records the execution workflow. Local visual review is required before merge or production delivery.
