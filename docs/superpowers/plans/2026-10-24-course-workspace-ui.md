# Course Workspace UI Implementation Plan

> **For agentic workers:** Use subagent-driven-development for independent screen families, with root integration and a whole-branch review. Steps use checkbox tracking.

**Goal:** Implement the approved fresh course-centered UI across Mudaris while preserving its existing functionality.

**Architecture:** Introduce a shared visual shell and semantic styling, then migrate independent screen/component families without changing backend contracts. Keep existing feature orchestration, lifecycle checks, source identities and mutations; add a presentation-only Overview/Materials split at the course root.

**Tech Stack:** Existing Next.js 15 / React 19 / TypeScript / Tailwind / Firebase client. Local inline SVG icons; no new runtime state or animation dependency.

**Spec:** `docs/superpowers/specs/2026-10-24-course-workspace-ui-design.md`

## Global constraints

- Branch `codex/ui-redesign`; preserve backend, prompts, schemas, API contracts, limits and defaults.
- Follow new cool gray/white/periwinkle palette, black controls, Manrope/Alexandria, 72px compact rail and labeled course tabs.
- Preserve all 15 routes, old source/output query links, exact-revision citations, explicit source selection semantics and gates.
- English/Arabic, RTL/LTR, light/dark, 360px+, accessible keyboard/focus/reduced motion.
- No fabricated analytics, generation progress, grading, playback or new cloud features.
- Agents own disjoint files; root integrates. Do not install dependencies, edit secrets, run paid generation, deploy, merge or alter user data.

## Review focus

1. Old `?doc`, `?audio`, `?section=documents` links must reveal Materials and retain the target.
2. Foundation gating and saved-output access must survive layout and tab changes.
3. Preference hydration must preserve saved language/theme/sidebar choices, including effect replay.
4. Mobile/RTL navigation must retain every existing destination and exact citation viewing.
5. Busy uploads and late async responses must retain ownership/cancellation and retry behavior.

## Shared file/API contract

- Root creates `src/components/Icon.tsx`: `Icon({ name: IconName, size?: number, className?: string })`; named paths include home, grid, folder, history, bookmark, calendar, settings, logout, menu, close, plus, upload, file, exam, cards, summary, chat, layers, arrow-left, arrow-right, chevron-down, chevron-left, chevron-right, check, check-circle, alert, lock, moon, sun, globe, more, edit, trash, download, external, clock, refresh, loader, user, sparkles.
- Root creates `src/components/AppShell.tsx`: default component props `{ children: ReactNode; courses?: Course[]; course?: Course | null; courseId?: string; activeTab?: 'overview' | 'materials' | 'exam' | 'flashcards' | 'summary' | 'tutor'; fullWidth?: boolean }`. Renders the shared Navbar/Sidebar, course tabs and layout. Pages retain their main element with `className="workspace-main"`; dialogs can remain siblings outside the shell.
- Root creates `CourseNavigation.tsx` with `{courseId, activeTab}`; URL-compatible navigation.
- Root owns globals.css/Tailwind/layout/providers, Navbar/Sidebar, CourseFoundationGate, dashboard root and course root, new journey, navigation/hydration tests.
- Study agent owns all `/course/[id]/{exam,flashcards,summary,tutor}` pages including exam detail, plus any new study-only presentation components.
- Materials agent owns existing shared components other than Navbar, Sidebar, CourseFoundationGate, and new root components; includes uploads/viewers/citations/reorder/schedule/reminders/activity/bookmark/create/edit.
- Entry agent owns home, signin/signup/forgot-password/settings, dashboard/recent/bookmarked, legacy processing and translations.ts. Other agents send new translation keys for integration.

## Task 1: Shared visual foundation and navigation (root)

Files: globals.css, tailwind.config.ts, app/layout.tsx, lib/{theme,i18n,sidebar}.tsx; new Icon/AppShell/CourseNavigation; Navbar/Sidebar.

- [x] Add behavior tests for compatible course-tab destinations and saved preference adoption under StrictMode. Run to verify missing behavior first.
- [x] Implement new tokens/fonts, semantic UI classes, named SVG icons and shared shell. Keep semantic Tailwind aliases for unchanged feature markup during migration.
- [x] Adopt pre-paint preference state; persist through explicit setters. Unconfigured sidebar is compact, explicit saved settings win.
- [x] Implement accessible responsive navigation, correct active states and course switching. Preserve account actions.
- [x] Run focused tests and TypeScript; inspect actual shell at desktop/mobile/RTL.

## Task 2: Course Overview/Materials and dashboard (root)

Files: app/dashboard/page.tsx, app/course/[id]/page.tsx, CourseFoundationGate; new CourseJourney; tests/frontend/course-workspace.test.tsx.

- [x] Add tests for Materials query/deep-link precedence and journey state/optional support semantics; observe failures.
- [x] Keep course loader/mutation/polling ownership; split presentation with URL navigation. Reveal all required sections/actions for old links.
- [x] Build real foundation/confirmation/study journey with optional supporting branch; retain every gate, retry and explicit confirm.
- [x] Recompose dashboard courses, actual counts, reminders and schedule. Keep course/error/stat loading independent and archive/restore/delete behavior.
- [x] Run course-foundation/dashboard/past-exam-type tests and inspect real course data.

## Task 3: Study configuration and readers (study agent)

Files: exam setup/detail, flashcards, summary, tutor; optional study-only components.

- [x] Read spec sections 5.4–5.8 and existing tests before markup edits.
- [x] Migrate each route to AppShell with current course, courseId and activeTab; preserve fullscreen tutor handling.
- [x] Rebuild source/configuration/library/reader hierarchy, remove old decorative typography/colors, and use Icon/new semantic classes.
- [x] Preserve category behavior, selection blockers, saved IDs, async guards, PDF/export, per-side/turn citations, chat drafts, reveal/upload/compare and retries.
- [x] Replace fake progress presentation with honest busy states; distinguish saved-item opening.
- [x] Run direct-foundation/past-exam-types/async-flow tests and TypeScript. Add meaningful test only if introducing new behavior boundary such as zero-card result feedback.

## Task 4: Shared material, evidence and planning UI (materials agent)

Files: existing shared components except root-owned components; optional shared presentation helpers.

- [x] Read related tests/spec before markup edits; do not change domain requests.
- [x] Restyle upload/create/edit dialogs, accessible browse controls, progress/results and type controls; retain busy lifecycle.
- [x] Rework responsive material actions, viewers, warning disclosures, exact citation previews and supporting reports; consistent focus/RTL semantics.
- [x] Rework timetable/reminders/activity and bookmark controls with named SVGs/new visual roles; keep all mutations and validation.
- [x] Preserve current labels/roles required by functionality; update tests only when accessible presentation intentionally changes and behavior remains covered.
- [x] Run source/supporting/citation/async/navigation tests and TypeScript; review keyboard and narrow layouts.

## Task 5: Public, identity, activity and account screens (entry agent)

Files: home/auth/settings/activity/legacy routes, translations.ts.

- [x] Restyle homepage around lecture-first flow and a distinctive course-workspace preview. Keep account-aware CTA; illustrative preview clearly illustrative.
- [x] Build coherent auth form shell, existing two-step optional signup, password reset and provider states.
- [x] Migrate settings/activity/legacy routes to shared visual language/AppShell where appropriate; preserve forms/deletion/account state.
- [x] Replace old fonts/decor/emoji UI and add Arabic translations for new copy. Merge other agents' requested keys without changing content language.
- [x] Run navigation/profile/account/activity tests and TypeScript; review responsive and RTL form layouts.

## Task 6: Integrate, verify and locally review (root + independent reviewer)

- [x] Review each agent's diff for spec compliance and behavior preservation; resolve shared interfaces and missing translations.
- [x] Run `npm test`, `npm run lint`, `npx tsc --noEmit --incremental false`, and `NEXT_BUILD_DIR=.next-ui-verify npm run build` (PowerShell environment syntax). Use process-local TEMP/TMP in ignored `.tmp/ui-audit-vitest` for the known sandbox rename issue.
- [x] Review all layout families in browser, including actual authenticated course, source viewer, study configuration, settings, public/auth, phone widths, RTL/dark, and console. Do not interrupt ongoing user work or submit paid/destructive actions.
- [x] Have an independent agent inspect the whole diff for behavior/UI regressions. Fix actionable findings, rerun relevant checks.
- [x] Capture representative local result screenshots, document actual verification and remaining limits, commit completed branch changes. Keep merge/deployment pending the owner's visual review.

## Execution record

- User approved the written design and directly requested implementation with frontend-design and emil-design-eng. Execute this plan in the current session using parallel agents and root integration; no further routine confirmation is needed.
- Use the existing requested branch/current checkout; no additional worktree or dependency installation is necessary. Recheck a running upload before browser interaction and avoid destructive/cloud operations.
