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

## Glass and motion revision

The owner supplied a closer reference screenshot and explicitly requested circular side panels with liquid glass, plus every issue from the motion review. The revision adds a floating capsule navigation rail with circular controls, a rounded translucent shell, glass edges and static highlights, and a more compact connected journey. Glass blur is limited to chrome and overlays; document text stays on mostly opaque surfaces, with a solid-surface fallback when backdrop blur is unavailable.

The shared overlay hook now keeps the real dialog mounted through its pointer exit. It animates transform/opacity at 200ms for drawers/dialogs and 180ms/125ms for menu opening/closing, using the existing strong ease-out token and a drawer easing token. Keyboard dismissal remains immediate. Reduced motion uses opacity without spatial movement. Reopening an account menu during its exit cancels the obsolete close and resumes from its current presentation. Touch and mouse presses receive 100ms press / 160ms release feedback; hover remains gated to fine pointers.

Upload completion callbacks and operation timing remain immediate. Manual busy-state guards are checked before animation and before committing dismissal. Focus trapping and return focus remain in effect until the actual close. No backend, domain hook, API helper, dependency, or generation contract changed.

Final automated checks: 236 tests across 19 files, full lint, TypeScript, production build, and whitespace checks passed. Eight overlay lifecycle regressions cover pointer exits, immediate keyboard actions, rapid toggle reversal, busy-state changes, cleanup, and reduced motion. Independent source review approved the corrected implementation.

Live Chrome review covered the account menu, document drawer, focus restoration, mobile navigation, compact/expanded tablet navigation, 360/390/768/1440 widths, Arabic RTL, dark mode, and tutor fullscreen. Desktop and Arabic mobile screenshots are saved as local review artifacts. Browser viewport overrides and original preferences were restored after review. Real-device gesture testing and paid generation were not performed.

## Desktop sidebar toggle follow-up

The owner's desktop collapse/expand request now has a 240ms layout transition using the existing drawer easing. Layout switches once; only the decorative glass scales, while navigation controls and workspace translate without stretching readable content. Expanding labels fade in. Rapid reversals capture the current on-screen geometry before cancelling the previous effect. Keyboard and initial preference hydration remain immediate; reduced motion uses a 200ms opacity change.

Temporary transforms are cleared before outside pointer/keyboard actions, resize, direction changes, or unmount. Workspaces containing a dialog are excluded from layout transforms. The mobile drawer retains its existing motion/focus ownership, and scrolling lives in a dedicated content layer so the glass animation is not clipped by the target width.

Verified 247 tests across 20 files, full lint, TypeScript, production build, whitespace checks, and independent source review. Eleven new lifecycle tests cover LTR/RTL, both directions, reversals, hydration, keyboard, reduced motion, cancellation contexts, dialogs, and mobile/unmount behavior. Live browser checks captured active transform interpolation in both directions and RTL, immediate keyboard toggling, and working mobile drawer dismissal. An isolated browser tab was used to preserve the owner's active course page and original preferences.

## Warm palette and expanded navigation refinement

The owner's warm brown/orange request replaces cool decorative tokens with warm stone surfaces, espresso selected controls, burnt-orange accents, and a warm charcoal/apricot dark theme. Existing semantic status colors and saved course colors remain unchanged. Accent text has at least 4.60:1 contrast on the tested solid accent surfaces; selected control text exceeds 7.9:1 in both themes.

Expanded navigation and the mobile drawer now use full rows with transparent icon slots and plain course monograms. Only the compact desktop rail uses circular glass controls. The icon slots retain the same 46px geometry in both desktop states to avoid snapping during the existing animation. Review also found and corrected a logical-edge calculation that briefly translated RTL rows horizontally as their width changed. Two regressions reproduced the issue before the fix and now pass.

Verified 249 tests across 20 files, full lint, TypeScript, production build, whitespace checks, and independent CSS/motion review. Live Chrome checks covered both themes, English/Arabic, desktop collapse/expand, a 1024px expanded layout, and a 390px Arabic navigation drawer with Escape dismissal. No horizontal page overflow occurred in those checks. Screenshots were captured locally; browser viewport and the original Arabic/light/expanded preferences were restored. The original active course tab was preserved.

## Beige and light-blue, light-only revision

The owner replaced the warm-orange direction with a beige base and light-blue accents and explicitly removed dark mode. Pale-blue selected controls use dark-blue text, while the glass shell keeps a beige tint. Accent text has 5.82:1 contrast on pale-blue depth surfaces and selected controls have 7.71:1 text contrast. Sidebar shapes and motion are unchanged.

Removed the theme toggle, context/API, dark-only styles and translations. Root HTML always starts with the light theme and no longer reads the retired saved theme key. Existing language and sidebar preferences still hydrate and persist. Regressions verify an old saved dark preference cannot reactivate dark styling and no theme switch is exposed.

Verified 251 tests across 20 files, full lint, TypeScript, production build, whitespace checks, and independent source review. Live Chrome checks covered the 1024px English expanded sidebar and 390px Arabic layout with no horizontal page overflow or theme toggle. Saved a local screenshot of the beige/blue design, then restored the original Arabic/expanded navigation preferences and browser viewport. No backend or study workflow changed.

## Integrated sidebar and inset page frame

The owner's new website screenshot replaces the floating sidebar capsule with a continuous beige outer frame. Desktop navigation now starts at the top with its own brand and stays sticky beside a large rounded page panel; that panel contains both the header and page content. Light-blue accents, compact circular controls, expanded rows, and light-only styling remain. The mobile navigation retains its fixed drawer and focus ownership.

Sidebar layout motion now targets the full page panel, including its header, with the existing workspace fallback. It preserves RTL anchoring, rapid reversals, reduced motion, immediate keyboard actions, and fixed-dialog guards. Four new regressions failed before the frame-aware motion fix. A further mobile focus regression caught the hidden desktop brand receiving focus; excluding that link from the mobile focus sequence now places focus on the visible close control.

Final verification: 256 tests across 20 files, full lint, TypeScript, production build, whitespace checks, and independent shell/motion review passed. Live Chrome review covered 1440px expanded/collapsed desktop, 768px expanded header fit, 390px Arabic drawer opening/Escape/focus restoration, and tutor fullscreen occupying exactly 390 by 844 pixels. No horizontal page overflow occurred in the checked layouts. A final screenshot is saved locally; the original Arabic/expanded preferences and browser viewport were restored, and the owner's active tab was preserved. No backend or study contract changed.

## Four material panels in the course overview

The owner's marked screenshot replaces the overview's Reminders and Intelligence Summary widgets with Documents, Past Exams, Tutorials, and Audio Recordings in a two-by-two grid beneath the study journey. Existing material sections now render in both course views; overview panels retain their upload headers while long lists scroll inside equal-height bodies. Narrow layouts use one column. The Materials view keeps its sequential layout, foundation gate, and category navigation.

All original material callbacks, source viewers, preparation/analysis retries, exam classification, ordering, renaming, deletion, and lecture-confirmation gates remain. Empty exam groups are omitted only from overview panels. Stored reminders were not deleted, and no material analysis or backend behavior changed. Two new regressions failed before implementation and now cover the four overview sections, absence of old widgets, and upload locks before/after confirmation.

Verified 258 tests across 20 files, full lint, TypeScript, production build, whitespace checks, and independent source review. Live Chrome checks confirmed two equal columns at 1440px, four bounded scroll panels, no old overview widgets, one-column Arabic layout at 390px, and 44px material action controls without horizontal overflow. A document opened from the bottom of the scrollable document list in a viewport-sized fixed viewer and closed with Escape. The Materials view retained all four sequential sections. Supporting report dialogs had source/test coverage; the real course has no supporting materials for a live report check. Saved a local screenshot of all four panels, restored the viewport, and preserved the owner's active tab and preferences.

## Compact material cards with hover expansion

The owner requested overview-only rectangles that expand on hover and push the other rectangles to reveal their details. Each overview card now shows its category, item count, icon, and short localized description. Fine-pointer hover reveals the existing actions and material content in a measured accordion; grid rows grow in normal flow rather than overlaying or scaling readable content. The next row moves down, while the neighboring card remains compact. The sequential Materials view stays fully expanded.

The state-indication/spatial-consistency transition uses the existing ease-out token with height and opacity at 200ms. Height is the deliberate accordion exception to compositor-only motion. CSS transitions retarget on interruption. Hover is restricted to fine pointers; a button supports touch/click and immediate keyboard expansion. Reduced motion changes height immediately and keeps only a gentle opacity transition. Collapsed details are inert and hidden from the accessibility tree.

Focus inside details retains expansion. External uploads/viewers keep the opener card expanded through focus return; explicit header/Escape dismissal closes it afterward. Supporting dialogs and consumed editor Escape events retain their own keyboard behavior. Regressions caught and fixed reduced-motion CSS overriding instant keyboard actions and Escape also collapsing a card when cancelling a rename.

Verified 271 tests across 21 files, full lint, TypeScript, production build, whitespace checks, and independent interaction/motion review. Live Chrome review confirmed all four cards initially compact at about 124px, active height interpolation during hover, Documents expanding to about 533px, and the lower row moving by the corresponding 409px. Pointer exit collapsed it again. A document viewer opened from its details and returned focus to an expanded, non-inert opener; keyboard Escape collapsed immediately. The 390px Arabic layout retained one column, a 52px disclosure control, and no horizontal overflow. Touch gating, reversal, reduced motion, modal holds, and cleanup have automated coverage; no physical touch-device check was performed. Compact and expanded screenshots are saved locally. Browser viewport and original preferences were restored; no backend or material-processing contracts changed.

## Final, Midterm, and Quiz mini cards with taller rectangles

The owner requested three mini rectangles in the old Past Exams slot, ordered Final, Midterm, Quiz, and taller overview rectangles. Each exam mini now has its own count, type-filtered details, independent hover expansion, and category-specific upload opener. All six overview cards start at 200px on desktop and 180px on phones. The existing 200ms interaction, immediate keyboard behavior, focus holds, and reduced-motion treatment remain.

Uploads preselect the chosen mini's type while retaining the editable required selector and the existing request contract. Only the opener mini stays expanded for its upload. Unclassified older papers remain accessible through a count/link to the unchanged Materials classification view. Shared row/detail helpers preserve ordering, renaming, deletion, reports, foundation gates, and sequential Materials groups.

Verified 276 tests across 21 files, full lint, TypeScript, production build, whitespace checks, and independent source/CSS review. Seven regressions reproduced missing mini cards/default selection before implementation and now check category order/counts/isolation, upload defaults and actual edited payloads, opener-specific holds, and legacy access. Live Chrome verified all six 200px cards at 1440px and the real Final/Midterm/Quiz modal selections without submitting files. Narrow checks caught clipping at 1101px; the adjusted main-grid breakpoint, earlier mini stacking, and auto-fitting 44px controls fixed it. Expanded mini bodies had matching client/scroll widths at 1101px and 768px, and all six phone cards measured 180px at 390px without horizontal page overflow. Saved a local final screenshot, restored viewport/preferences, and preserved the owner's active tab. No backend or generation contracts changed.

## Language control moved into Settings

The owner requested removing the English/language button from the header and moving it into Settings. The shared public/workspace navbar no longer exposes a language toggle. Settings now has a Language section with a labeled English/العربية select that uses the existing LanguageProvider setter and saves immediately. Provider hydration, saved preferences, page direction, and account forms remain unchanged.

Four regressions failed before the implementation and now verify header absence/Settings access, saved-language adoption, English persistence across remounts, Arabic direction changes, and no account mutations. Verified 279 tests across 22 files, full lint, TypeScript, production build, and whitespace checks. Live Chrome selected English in Settings, reloaded to confirm it remained selected with LTR layout, then restored Arabic/RTL. A 390px check found no horizontal overflow and only the account control in the header. Saved a local Settings screenshot, restored the original language and viewport, and left the owner's active tab intact. No profile, email, password, or account changes were submitted.

## Past-exam upload interrupted by foundation revalidation

The owner reported that selecting Upload made the lecture confirmation appear unchecked and prevented uploading a past exam. The focus listener in useCourseFoundation starts a background GET when the native file chooser returns focus. Its temporary loading state made foundationReady false, which removed all active supporting upload dialogs, cleared selected files, and aborted any request in progress even when the known foundation remained confirmed.

The course page now distinguishes the known confirmed foundation from permission to start a new action while a check is pending. The confirmation indicator and already-open past-exam, tutorial, and audio upload dialogs retain their state during a background check. New supporting/study actions still wait for the response. A reported unready foundation, failed check, lecture mutation, account change, or course change still revokes readiness. The backend's upload-time foundation check and transactional revision guard remain unchanged. Pending checks show checking guidance instead of asking the owner to confirm the already-confirmed lectures again.

Four regressions cover focus before the file-change event, retained file/category and confirmation, unchanged ready responses, preserving an in-flight upload without abort/restart, and revocation after an actual changed/error result. The initial three regression cases failed against the original modal condition. Verified 283 tests across 22 files, full lint, TypeScript, production build, whitespace checks, and independent source/safety review. Live Chrome confirmed the course's ready foundation and opened the Midterm upload dialog with the correct category. Native chooser interaction then stopped because computer use could not confidently identify the active browser URL; post-fix native chooser verification was unavailable in this turn. No real exam file was selected or submitted; upload request/completion checks used synthetic files and mocked API responses.
