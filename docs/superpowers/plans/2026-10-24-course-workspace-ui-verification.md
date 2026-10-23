# Course workspace UI verification

Date: 24 October 2026
Branch: `codex/ui-redesign`

## Delivered scope

- Replaced the previous visual system with cool gray layers, white surfaces, periwinkle depth, black active controls, Manrope/Alexandria typography, and a shared responsive workspace shell.
- Rebuilt the dashboard and course entry around real course data and a lecture preparation / confirmation / study journey. Materials have a dedicated tab; existing document, recording, and saved-output links retain their destinations.
- Migrated study configuration and readers, tutor, uploads, evidence previews, planning controls, activity, account forms, settings, and the public homepage.
- Kept backend code, API helpers, Firestore helpers, domain hooks, dependencies, schemas, prompts, and generation contracts unchanged. Preference providers now adopt saved choices on mount and persist only explicit changes.

## Automated checks

All checks passed on the final source:

| Check | Result |
| --- | --- |
| `npm test` | 228 tests passed, 18 files |
| `npm run lint` | Exit 0, no diagnostics |
| `npx tsc --noEmit --incremental false` | Exit 0, no diagnostics |
| `$env:NEXT_BUILD_DIR='.next-ui-verify'; npm run build` | Exit 0, all existing application routes built |
| `git diff --check` | Clean |

The test suite retains coverage for foundation gates, exact source identities, supporting-source selection, async ownership and stale responses, upload retries, account operations, saved output readers, navigation, and activity. New coverage includes preference hydration, course query compatibility, material accessibility, flashcard academic text, mobile exam pane focus, and Arabic tutor labels with unchanged submitted starter prompts.

Windows sandbox restrictions required the production build to run with approved filesystem access. Tests used a process-local temporary directory inside ignored `.tmp/ui-audit-vitest`. Generated verification build include paths were removed from the tracked TypeScript configuration.

## Browser review

Reviewed locally in Chrome with the existing authenticated session and real course documents:

- Desktop workspace, dashboard, course journey, Materials, exam setup, flashcard setup, summary setup, and tutor.
- Public homepage, sign-in, signup, password reset, settings, recent activity, and the bookmarks empty state.
- Course creation and lecture scheduling forms opened and closed without submitting changes.
- Document upload dialog opened and closed without selecting or uploading files.
- Document reader with all source notices preserved in a disclosure; a guide citation opened the corresponding original source preview.
- Tutor source dialog and navigation drawer: opening, Escape dismissal, and focus return.
- Phone widths 360 and 390; tablet widths 768 and 1024; desktop width 1440. Checked page width against viewport width on representative layouts.
- Arabic RTL and dark mode, including the mobile drawer, tabs, tutor, and sources. Returned to the original English/light/expanded preferences after review.
- Final console review and representative screenshots captured locally for the owner's review.

Independent review found and closed three issues: hidden flashcard academic accessible names, offscreen active course navigation on mobile, and answer reveal not selecting/focusing the correct mobile document pane. The later row-layout and source-notices changes received an additional clean review.

## Practical limits

- No paid AI generation, real file submission, grading, account mutations, destructive actions, deployment, or merge was performed during visual QA. Those workflows have automated coverage; real generated output was not created for this review.
- The current course has no saved generated outputs. An older Recent exam link refers to a removed item and correctly displayed the existing missing-item/retry state.
- Responsive review used browser viewport overrides, not physical phone hardware.
- The local development preview remains available at `http://localhost:3000`. Merge and production delivery await the owner's visual review.
