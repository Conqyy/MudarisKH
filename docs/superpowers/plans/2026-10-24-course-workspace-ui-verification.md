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

## Course loading after an interrupted supporting-material deletion

Opening CS1322 failed with the generic account/course/conversation-change message. Correlated backend logs isolated GET /api/tutorials/{course_id} returning 409 while other course lists succeeded. Read-only metadata checks found one valid incomplete tutorial and another retained tutorial marked deleting with a deletion tombstone. Projecting the latter through its strict status reader raised DataConflict and failed the entire course load.

A shared API collection-projection helper now omits deleting or concurrently unavailable supporting entries, while preserving valid incomplete materials. Historical-exam, tutorial, and audio/notes lists share this behavior. The helper catches only DataConflict and rechecks course/account access before returning a partial list; unexpected errors still fail normally. Direct reads/actions, generation guards, and low-level queries used for deletion cleanup remain unchanged. No stored record or file was deleted or repaired.

The original tutorials regression returned 409 before the fix. Verified 54 supporting API tests plus 93 historical/foundation API/storage tests (147 total), whitespace checks, and independent source review. FastAPI TestClient required escalation because the Windows sandbox blocked its internal socket pair. Restarted the backend, retried the owner's existing CS1322 page, and confirmed the tutorials request returns 200. The real page shows Operating Systems, ten documents, one valid tutorial, confirmed lectures, and all four study links; the conflict message is absent. No generation, upload, account change, or deletion was submitted.

## Tutorial analysis recovery (2026-10-25)

Saved analysis checkpoints showed incomplete or invalid model responses, topic references that did not identify the extracted requirements exactly, independent inventories disagreeing about the source, and malformed lecture references during alignment. Uploads had been accepted. A later live read found that the affected uploads were no longer present; no deleted records or originals were restored or retried.

Extraction now supplies validation feedback on its bounded repair attempt, records content-free completion diagnostics, and increases its output allowance only after confirmed truncation. Exact topic/item requirement links are checked before accepting an inventory. Older owned checkpoints with this newly detected reference failure reread both inventories from the earliest affected window while preserving spent calls; unrelated invalid proofs still reject the checkpoint.

Disagreeing independent inventories can receive a bounded audit against the original current/previous source evidence. Both inventories remain unchanged. The audit must account for every obligation, preserve item/requirement relationships and one-to-one mappings, and cite current-window evidence. Genuine omissions, question/context disagreements, and unreadable content remain incomplete. Repeated proofs are encoded losslessly to keep complete requests within bounds. Pending audit responses and source-bound certificates are persisted and validated on recovery.

Alignment validates the entire returned judgment group before accepting evidence and permits one contract repair against the same originals. Transport errors and valid uncertain/rejected judgments do not trigger that repair. Failed validation stays unverified and retryable instead of becoming not_found through an earlier accepted search ledger. The UI now displays a localized actionable incomplete-analysis reason; page progress reflects verified extraction rather than merely prepared source pages.

Verification: 600 supporting-material backend tests passed in a hash-checked source/test copy outside OneDrive, using a dummy credential and localhost-only provider URL. Initial runs inside the checkout encountered intermittent Windows os.replace file locks in existing local-database fixtures; their isolated cases passed, and the complete outside-OneDrive run passed. No production storage behavior was changed for those test-environment locks. All 284 frontend tests, lint, TypeScript, production build, whitespace checks, and independent recovery/evidence review passed. Regression cases include truncated responses, wrong exact references, legacy checkpoint recovery, actual generated PDF input, closed audit obligations, current-source evidence, pending-response replay, and call budgets.

Restarted frontend/backend and verified the signed-in CS1322 course loads, its tutorial endpoint returns 200, ten lectures remain confirmed, and the empty tutorial section offers Upload. The browser console had no errors. The owner stated that the AI model is disabled and will be replaced with a free model. Model configuration was left unchanged and no live AI calls were initiated. A real tutorial analysis with the replacement model remains unverified; the current PDF pipeline supplies page images and therefore needs image-input support.

## Analysis reliability follow-through (2026-10-30)

Live checks with the owner's configured `nvidia/nemotron-3.5-super-vl:free` model exposed failures beyond provider availability. Successful responses changed copied whitespace, confused lecture-navigation images with the supporting original, and sometimes returned empty cover-page classifications for exercises. A saved response attributed a Virtual Memory lecture heading to the tutorial's Process Concept page. Incomplete extraction also reached alignment with an unresolved shared-context reference and failed with a generic KeyError.

Supporting extraction and alignment now use strict response schemas and content-derived span IDs. The application restores exact original quotes and coordinates; current-window, ownership, source-revision, target-nomination, and publication checks remain authoritative. Image captions identify each current source, previous context, and navigation-only lecture image with its original asset/reference. Citation markers explicitly do not define exercise boundaries. Complete original text/images are retained, and request bounds include captions and response schemas. The navigation bridge reserves actual packet overhead rather than reserving the outer request twice.

Whole-window exclusions require retained records and proofs covering all current non-whitespace text and original images. Real empty sources remain exempt. Legacy empty exclusions rewind both extraction passes from the earliest invalid window while retaining verified prefixes and spent calls. Numeric source order survives canonical checkpoint serialization beyond ten windows. Strict span-ID tests cover extraction, reconciliation, audit certificates, and replay of pending responses without duplicate calls.

Incomplete extraction now stops before alignment or report publication, preserving its exact checkpoint and specific sanitized retry reason. Current failed/incomplete progress cannot be replaced by a retained older report. Active status reads use persisted progress without downloading report artifacts. Verified source evidence is reused only inside one job and every cache hit retains the live ownership/claim/foundation fence; report publication validates originals independently.

Routine foundation status reads use validated publication metadata, while confirmation and protected actions still check original artifacts. A measured CS1322 status read on October 26 took 1.11 seconds with all ten lectures ready and no AI call; protected preparation of its 385 source units took 22.94 seconds. Supporting preparation reuses its fully hydrated foundation instead of downloading it twice within the same request. Focus refreshes are deduplicated. Focused lecture evidence and combined premises are independently verified before constructing an exhaustive search; unresolved absence claims still require full coverage. Full alignment plans use the remaining call budget, and validated blank-only batches are skipped without confusing excluded and selected scope.

The combined backend suite after those repairs passed 1,747 tests, with one skipped and six subtests. Frontend verification previously passed 292 tests, lint, TypeScript, and the production build. The labeled-image live retry retained the first real exercise and its complete Code 1 in givenData, then stopped safely after two invalid page-2 responses cited only previous-page evidence. The UI displayed a sanitized invalid-analysis reason, retained Retry analysis, and had no browser-console errors. This proves the crash prevention and first-page improvement, not complete real-model tutorial analysis.

Wire v4 constrains fresh claims to select at least one exact current-window proof in the transport schema and rejects links to undeclared shared-context records immediately, before accepting a checkpoint window. Canonical stored proof arrays remain unchanged, and pending v1/v2/v3 responses still replay through their original decoders. The combined suite passed 1,773 tests, with one skipped and six subtests (125.62 seconds). On November 1, all 139 backend Python source/test files matched that tested snapshot byte-for-byte.

The real v4 retry used eight model responses and ended incomplete with independent-source disagreement, zero of three source units verified, and no new report publication. Inspection showed erroneous cover classifications, code lines represented as questions/subparts, and repeated previous-page content. The exact first-page render was checked visually: it clearly contains Question 1 and its complete C program. The rendered input is correct; a structural schema alone does not establish semantic extraction quality.

### Controlled model diagnostics (2026-11-01)

Read-only first-page experiments used the same saved original, current free model, exact provider schema, temperature zero, and no application configuration changes. Source-only input still produced 22 code-line items; intact raw text plus a separate citation table produced 24. The baseline produced one question but split its code into 20 givenData entries, which would increase later context-dependency work. Therefore neither input simplification justified a production change.

Reasoning-on experiments also failed: default reasoning produced six incorrectly grouped records, while low effort produced three records with invalid topic links. They consumed 8,420 and 10,279 reasoning tokens respectively and did not retain a complete givenData block. Restoring the adapted model-visible JSON example produced 24 and 26 incorrectly grouped records in two trials, both with undeclared shared-context links. None of these speculative changes were applied.

One zero-price comparison request to the catalog's other image/structured-output-capable free model (`dots-studio/dots-3-note-preview:free`) returned an empty uncertain inventory and failed validation. The configured model remains unchanged. A compact semantic-extraction prototype is being evaluated independently of saved jobs; it must prove correct exercise grouping and exact original recovery before adoption.

### Exact source selection for native tutorials (2026-11-01)

The owner explicitly authorized three requests sending saved Tutorial 1 to OpenRouter with the current free NVIDIA model. All three requests were consumed, with no retries beyond that allowance. Page 1 grouped its question/program correctly in 2.55 seconds; its seven proofs validated after locator-only typography/whitespace restoration. Page 2 grouped the continuation correctly in 1.77 seconds but dropped three literal C `\n` escape sequences and copied previous-page headings. Exact validation rejected it. This copying-based candidate was not adopted.

The third request instead selected the first and last physical lines of page 3's program. It returned one Question 2, one task, and one complete program range in 2.14 seconds (3,207 input and 128 output tokens). The application restored the complete original `[55,662)` slice, and all five proofs validated. The response also repeated its question sentence in headings; the production decoder explicitly rejects such overlap. This experiment verifies exact program recovery, not independent completeness or end-to-end saved analysis.

Native tutorial wire v5 now uses source-bound line selectors and optional exact subquotes, with every persisted body, label, choice, task, and data block restored from the original. Real printed subparts, shared contexts, academic headings, marks/formats and exact continuation identities remain represented. Complete native PDF pages are eligible; original images still accompany both independent passes. Scans, partial long-text windows and unsupported visual/structural content retain rich extraction. No model or application UI preference changed.

The API opts into the new transport. Pending v1–v4 responses retain their original decoder; returned v5 responses replay even if the rollout preference or request-size limit changes. An explicit rich fallback or oversized unsent native request rewinds both passes from the affected window, retains the checked prefix and spent calls, and persists the fallback. Neither pass receives the other pass's inventory. Canonical source, ownership, coverage, reconciliation and publication checks remain mandatory.

The first integrated snapshot passed 1,854 backend tests, with one skipped and six subtests (128.42 seconds). Independent review then identified a choices-only continuation edge: exact current choices now continue the prior question without changing its identity, metadata, or requirements; unsupported requirement-only fragments explicitly request rich extraction. The final isolated, hash-verified snapshot passed 1,858 tests, with one skipped and six subtests (127.88 seconds). The backend was restarted with the new code after confirming zero pending jobs. No additional live model requests or new saved report publication have occurred since the three-request allowance was exhausted; complete live course analysis remains unverified.

### Full-test diagnosis and bounded repair (2026-11-02)

The owner subsequently approved one full saved Tutorial 1 analysis against the confirmed CS1322 lectures with a new cumulative limit of 24 physical requests to the same free NVIDIA model. The initial execution stopped incomplete after three responses, with no current-job report published. Provider time totaled 10.14 seconds; the diagnostic runner took 201.28 seconds including repeated lecture preparation and persistence. Page 2 twice redeclared a known context handle and also duplicated its code caption in headings and given data. Offline replay proved both independent validation failures; exact program selection itself was intact. The original outcome and the durable request ledger are retained in ignored local test artifacts.

New native requests distinguish current context keys from known handles in their schema. Existing saved v5 keys still decode without migration. Bounded repair feedback now identifies both context collisions and heading overlaps and, when the existing request-size limit permits, includes the rejected response as explicitly untrusted output. Neither rejected claims nor repair feedback enter the independent pass. Validation still rejects the unchanged malformed response; the application does not strip claims or relax original-source checks. The focused source/extraction suite passed 167 tests.

Progress and recovery pointers now publish in the same fenced transaction that adopts their checkpoint. Spent calls remain durable before artifact storage; reservations, pre-upload claim checks, ownership, source/foundation checks and recovery behavior are preserved. This removes one transaction per checkpoint save. The focused storage/workflow suite passed 209 tests, and independent review found no material issue. The change does not remove the diagnostic runner's extra full lecture reads or establish an end-to-end speed claim.

The complete backend suite passed 1,892 tests, with one skipped and six subtests, in 122.82 seconds. All 145 Python source/test files were hash-verified in an isolated temporary copy; the suite used a dummy key and localhost-only provider URL. The request-cap runner's 17 offline guard checks also passed. Live continuation retains the same durable 24-request ledger, with the initial three requests already spent; this allowance was not reset.

The continuation consumed seven more requests (ten cumulative). Its first extraction pass completed all three pages, but the independent pass stopped at page 2. Both rejected responses retained the exact nonacademic caption `//Code (2)` at `[0,10)` as well as the complete program at `[0,339)` in given data; neither duplicated a current task, requirement, choice or label. The first native decoder's blanket heading-overlap rule rejected this redundant metadata before the independent audit could judge it. No report was published. Preparation took 25.05 seconds, the workflow 233.22 seconds, and the entire diagnostic run 320.48 seconds. Seven provider calls totaled 46.38 seconds. A runner cleanup PermissionError occurred after its outcome was saved; the persisted application result independently confirmed the incomplete state and zero pending jobs before backend restart.

The corrected overlap rule retains both exact records for a nonacademic caption wholly contained in every overlapping given-data range. Academic headings, task/label/requirement/choice overlaps, partial crossings and mismatched source locations retain their rejection rules. Decode and repair feedback share the same rule. Canonical validation, semantic reconciliation, and the disputed context continuation remain subject to their original checks. Independent offline review confirmed identical alignment targets with and without the additional caption and its exclusion from usable academic items. The actual rejected response now passes structural validation with all 339 program characters and the caption preserved; that alone is not proof of complete analysis. The final full suite passed 1,899 tests, with one skipped and six subtests, in 155.54 seconds.

The final continuation used twelve additional requests, bringing the durable total to 22 of the approved 24. Both independent passes accepted all three source windows, but final semantic reconciliation remained incomplete: page 1 and 2 audit certificates rejected the first inventory, and page 3's audit twice violated the first-obligation mapping contract. Offline inspection found false rejection reasons on pages 1 and 2: the audit claimed missing numbering already present verbatim and confused a separate nonacademic caption with the whole page's `readable/questions` classification. Page 3 also has a genuine missing printed-label field in the first inventory, so these audit mistakes do not justify forcing acceptance.

No current-job report was published, no lecture alignment ran, and verified coverage remains 0/3. Final preparation took 25.11 seconds, workflow 362.72 seconds, and the entire diagnostic run 445.48 seconds. The runner again reported a cleanup PermissionError after saving its outcome; an independent persisted-state read confirmed the result and zero pending jobs. No further requests were spent. The unchanged free model and cumulative cap were preserved. Backend and frontend were restored, and the signed-in CS1322 Materials page was checked live: ten lecture documents and Tutorial 1 remain present, with the honest incomplete-analysis state and retry control. Complete end-to-end tutorial analysis is still unresolved.

### Field verification implementation (2026-11-02)

The owner approved replacing brittle factual judgments with deterministic source facts and question-by-question comparison. `InventoryComparison` pairs source-bound obligations with one-to-one parent/requirement/topic ownership and exposes exact field values and literal-presence facts. Proven outer source whitespace is ignored only when disproving missing printed labels or requirement words; original strings, code, mathematics and proof coordinates remain unchanged.

New audit protocol 2 requires the exact task identity, field observation, typed finding, original evidence and independent source-completeness judgment. A contradicted missing-content claim is an invalid response requiring bounded repair, never automatic acceptance. Novel literal omissions cannot be disguised by citing already-retained text across the entire page; text-backed omissions require localized text evidence. The schema uses request-local field-value handles that restore canonical digests. Legacy wire 1–4 responses and certificates retain their validators. The API opts into the new audit.

The independent completeness check is mandatory even when both new inventories match. Failed/uncertain reviews retain valid source passes and accepted certificates. Definite first-pass defects rebuild the affected source suffix and its dependents; definite second-pass defects rebuild only that pass's affected suffix. Current source/ownership/task bindings, durable accounting, interruption replay and publication fences remain enforced. Explicit original English/Arabic question labels are restored from unambiguous line prefixes; overlong labels containing task wording reject, while unknown labels and existing continuation identities remain preserved.

Offline replay of the actual saved source rejected all three false missing-label/numbered-requirement claims, kept the nonacademic caption separate from page classification, and restored the exact `Question 2:` label while retaining its complete original program. All three complete audit requests fit the unchanged 24,000-character bound at 23,086, 18,123 and 18,882 characters, including schemas, policies and image captions.

The complete isolated suite passed 2,013 tests, one skipped and six subtests, in 177.90 seconds. All 151 Python files were hash-verified; live AI calls were disabled. Independent reviewers' material findings, including equality bypass and a second-pass retry loop, were fixed and covered. The new capped runner's 20 offline guard checks passed, including repeat lock acquisition with unbuffered I/O to avoid the earlier Windows read-ahead lock-position cleanup error.

No additional model requests were made during implementation. The prior allowance remains at 22/24. After code and offline validation were complete, the owner explicitly approved one new full Tutorial 1/confirmed-CS1322-lectures test with the unchanged free NVIDIA model, capped at 32 additional physical requests. Its separate durable ledger does not reset or overwrite the old allowance. The production workflow test is now running; complete live success remains unverified until its bound report is validated.
