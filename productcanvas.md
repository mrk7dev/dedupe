# Product Canvas — dedupe

Living requirements doc for the Synology duplicate-file and comparison tool. Update this as we reconsider scope — treat it as the source of truth over any single conversation.

## One-liner

A self-hosted tool that scans Synology DiskStation shared folders and reports duplicate files — by content, and by visual similarity for images — so files can be safely reviewed and reclaimed.

## Problem

Files accumulate across the NAS (backups, syncs, saved photos) with duplicates scattered across folders. Need visibility into what's duplicated and how much space is recoverable, without risking data loss in the process.

## User

Single user, self-hosted for personal use. Runs a Synology DS923+ (AMD Ryzen R1600, 2C/4T, 32GB RAM). Comfortable with Docker and the CLI.

## Fixed constraints

These were decided earlier and shouldn't be re-litigated casually — flag it explicitly if a new feature would require breaking one:

- Runs as a Docker container on the DiskStation itself, via Container Manager.
- x86_64 only (matches the DS923+ CPU — no need for multi-arch builds).
- Python 3.12 stack; SQLite for the index.
- Frontend is a React + Vite SPA, built to static files at Docker build time — FastAPI serves them and exposes a pure JSON API. No persistent Node process at runtime, so the 2C/4T CPU budget stays intact. Implemented: `Dockerfile` has a `node:22-slim` build stage producing `frontend/dist`, copied into the final image and served by FastAPI at `/` via `StaticFiles` (`app/api.py`, gated on `STATIC_DIR`). The old Jinja single-volume dashboard moved to `/legacy` to free up `/` for the SPA — still functional, not removed.
- Source volumes are mounted **read-only** — the app must never modify or delete originals.
- "Remove" always means *move to a staging folder*, never a hard delete.
- CPU budget stays conservative — 2C/4T total, shared with DSM and other packages.
- One deliberate, scoped exception to the read-only rule: comparison mode's target path is writable, additive-only. See "Volume/Folder Comparison Mode" below.

## Original requirements — status

| Requirement | Status | Notes |
|---|---|---|
| Identify duplicates by file content | Done | Staged size → partial hash → full hash (blake2b) |
| Identify duplicates by filename | Not implemented | Originally scoped as a secondary/supporting signal only, never built as an actual detection mode or surfaced in the UI |
| Identify duplicates by timestamp | Not implemented | Same as above — discussed as weak evidence on its own, deliberately not used as a primary signal |
| Generate a report | Done | Static HTML (visual, size-category filters) + CSV, plus a live web dashboard |
| Near-duplicate detection (image similarity) | Done | Added beyond the original ask once 32GB RAM made pHash + BK-tree matching practical |

## What's built (feature inventory)

- Filesystem scanner with incremental rescanning (skips unchanged files by size+mtime)
- Exact-duplicate detection via staged hashing pipeline
- Perceptual near-duplicate detection for images (pHash, BK-tree grouping, HEIC support)
- SQLite index with scan history
- Web dashboard: trigger scans, browse exact/similar groups, stage files for removal
- Static HTML report: summary cards, size-category bar charts, filterable group lists
- CSV export
- CLI: `scan`, `report`, `serve`
- Docker packaging (Dockerfile + docker-compose.yml)

## Volume/Folder Comparison Mode

Compare two arbitrary folder trees — **source** and **target**, which may be two folders on the *same* drive, not necessarily separate volumes — purely by content, so folder structure and naming differences between the two sides don't matter. This is a new capability alongside single-volume dedup, not a replacement for it.

**Status: fully wired, no mock data left.** Backend (`app/browse.py`, `app/compare.py`, `app/compare_copy.py`) implements all six endpoints, tested in `tests/test_compare.py`. Frontend (`ComparePage.tsx`, `frontend/src/api.ts`) calls all of them for real: folder picking, starting a comparison, polling status through counting/scanning/hashing/ready, fetching results, selecting files, copying, and polling copy status — no `mockData.ts` left in the repo. Verified with a full live run in-browser against a real test filesystem: correct matched/source-only/target-only counts, correct selected-size total, real per-file copy that landed at the right relative paths under target, source left untouched, and the results view refreshing afterward to show the newly-matched files. The single-volume dashboard (`/legacy`) and the frontend build/serve pipeline (Dockerfile → FastAPI `StaticFiles`) are also done — see the constraints section above and the Decision log.

**Matching:** same staged hashing pipeline as today (size → partial hash → full hash). Content-only for v1 — no perceptual/near-dup matching (see Backlog).

**Results — three categories:**
- Matched: identical content exists on both sides.
- Source-only: exists on source, missing from target.
- Target-only: exists on target, not on source.

**UI is interactive, not a static report — React + Vite SPA:**
- Folder selection is a **modal dialog** (`FolderPickerModal`), triggered by a "Select folder…" button per side — not an always-open inline tree. Both source and target browse the *same* shared filesystem tree (one mock filesystem stands in for `/api/browse`), since either side can be any folder on the NAS. Internal volumes and external/USB drives are visually distinguished (labeled "volume" vs "external drive") so mounted drives are identifiable, not just internal storage.
- Progress: count total files under the selected roots first, then show live progress as they're indexed/hashed (e.g. "1,204 / 8,530"). Currently simulated client-side; will be polled via `@tanstack/react-query` against `/compare/{id}/status` once the backend exists.
- Results are browsable **two ways at once**, side by side: a flat, filterable table (`@tanstack/react-table` + `@tanstack/react-virtual`, stays responsive at real NAS scale) and a `SourceTreeView` folder tree rebuilt from the same results, with a "Show only missing files" toggle that prunes folders down to only the ones containing gaps — folders with nothing missing just don't appear, they're not merely hidden.
- Tree navigation: "Expand all" / "Collapse all" controls (via react-arborist's `TreeApi`), plus independent collapse/expand for each whole panel (source tree and results table each collapse down to just their header, independently of one another).
- Table columns: Path and Name are separate, independently resizable columns (drag handles on Path/Name/Size/Status), not one combined path string.
- Selection: checkboxes to select/deselect individual files from the missing-from-target view — selection state lives client-side in the SPA. The copy button shows both the **count and total size** of what's selected (e.g. "Copy 3 selected (7.7 MB) to target").
- Action: explicit "Copy selected to target" button — nothing copies without this being clicked. While copying, the button area is replaced by a **progress bar** (file-count based, e.g. "Copying 16 / 20"); currently simulated, will reflect real per-file copy progress once the backend exists.

**Copy behavior (target write rules):**
- Additive only — creates new files on target, never modifies or deletes anything already there.
- Requires explicit confirmation via the select-then-copy flow; no automatic copying.
- Naming conflict (same filename at the destination, but different content since it wasn't matched): auto-rename the incoming copy, existing target file is never touched.

**Write safety (resolved, implemented):** the target root needs write access, enforced at the application level via a `WRITABLE_ROOTS` env-var allowlist (`app/config.py`) — a compare run's target root must resolve inside one of these or `POST /compare/{id}/copy` refuses with a `PermissionError`, independent of what the underlying Docker mount permits. Each individual copy destination is additionally re-checked to resolve inside the target root before writing (`app/compare_copy.py`), so path tricks (e.g. `..` segments) can't escape it. The docker-compose target mount is not `:ro`, since it needs to receive copies — see `docker-compose.yml`.

## Open questions / up for reconsideration

*(This is the working section — add items here as they come up in planning conversations.)*

- Filename-based and timestamp-based duplicate detection were in the original ask but never built — still undecided whether that's wanted.
- Should target-only files (present on target, not source) get any action in the UI, or stay purely informational?
- Comparison mode is getting a real interactive UI (tree browser, live progress, selection). Should single-volume dedup mode eventually get upgraded to match, instead of its current env-var-driven config?

## Backlog / candidate features

*(Ideas not yet committed to — move to "in scope" once decided.)*

- Extend perceptual/near-duplicate (image) matching to comparison mode — deliberately excluded from v1 to keep the first pass focused on exact-content matching.
- Bring comparison mode's interactive UI pattern (tree browser, live progress, selectable results) back to single-volume dedup mode for consistency.

## Non-goals

*(Explicitly out of scope, and why — prevents relitigating settled calls.)*

-

## Decision log

*(Append-only. Newest at the bottom. Capture what was decided and why, not just what.)*

- Chose Docker-on-DiskStation over running from an external machine — avoids network-bound scanning, simplest deployment path for a single-user setup.
- Chose Python over Go for the implementation — with 32GB RAM, per-worker memory overhead (the original reason to favor Go) stopped being a real constraint; Python's ecosystem (Pillow/imagehash for perceptual matching) won out.
- Added perceptual/near-duplicate image matching as a distinct feature (not just exact hashing) — RAM headroom made it practical, and it addresses a real case (re-encoded/resized photos) that exact hashing misses entirely.
- "Remove" is implemented as stage-to-folder, never delete — matches the project's safety default of reversible actions only.
- Added Volume/Folder Comparison Mode as a new, separate feature alongside single-volume dedup — compares two folder trees (which may live on the same drive) purely by content, ignoring path/structure differences.
- Comparison mode's UI is designed to be interactive (tree browser + live progress + selectable results), not a static report — a deliberate departure from how single-volume mode works today.
- Comparison mode's resolution action is "copy missing source files to target," not staging/removal — additive-only writes, explicit per-batch confirmation via selection, and auto-rename (never overwrite) on filename conflicts.
- Perceptual/near-duplicate matching is out of scope for comparison mode v1 — exact content hashing only, to keep the first pass focused.
- Chose React + Vite over htmx for the frontend, dropping the earlier "keep dependencies light" preference — the tree browser and a large, filterable, checkbox-selectable file list are exactly the stateful UI problems React's ecosystem (`react-arborist`, TanStack Table/Virtual/Query) already solves well, where htmx would mean hand-rolling client-side selection state and virtualization. Built to static files at Docker build time, not run as a persistent Node server, so the NAS's 2C/4T budget isn't affected at runtime. This also means FastAPI moves from server-rendered Jinja templates to a pure JSON API — the existing single-volume dashboard will eventually need to move to the same SPA (see Open Questions).
- Folder selection is a modal dialog browsing one shared filesystem (both source and target pick from the same tree), not two separate fixed inline trees — matches the requirement that source/target can be different folders on the same drive, and scales better once there are several mount points to show.
- Comparison results get a dedicated folder-tree view (`SourceTreeView`) in addition to the flat table, with a missing-only filter that prunes whole folders, not just rows — lets you spatially browse *where* the gaps are, which a flat list alone doesn't convey.
- Both the source-tree panel and the results panel collapse independently — screen space matters once both are showing real content side by side.
- The copy action surfaces total selected size (not just count) and shows a progress bar while running instead of completing instantly — closer to what an actual multi-file copy over the network will look and feel like, and gives a natural place to show real per-file progress once the backend exists.
- Built the comparison-mode backend: `app/browse.py` (lazy, `BROWSE_ROOTS`-scoped directory listing), `app/compare.py` (staged size → partial-hash → full-hash matching across source/target, reusing `app/hashing.py`, with incremental progress written to a new `compare_runs` table), `app/compare_copy.py` (additive-only copy of selected `source_only` files, enforced against a `WRITABLE_ROOTS` allowlist with a second path-escape check per file, auto-rename on filename conflict, logged to `copy_actions`). New tables: `compare_runs`, `compare_files`, `copy_actions` (`app/db.py`). Six new endpoints on `app/api.py`. Verified with `tests/test_compare.py` plus a live end-to-end run against a real filesystem via `uvicorn` + `curl`.
- Per-file copy failures (permissions, disk full, a file vanishing mid-run) are caught and logged on that file's `copy_actions` row rather than aborting the whole batch — a path-safety violation (write attempted outside the target root) is the one thing that still aborts, since that's a bug rather than an expected I/O failure.
- `GET /api/browse` lists one directory level at a time (`?path=`) instead of returning a full tree like the frontend mock did — matches how a NAS-scale filesystem should be browsed (lazy, on expand) rather than walking everything up front.
- Wired `FolderPickerModal` to the real `GET /api/browse` (`frontend/src/api.ts`), replacing the static `filesystemRoots` mock (deleted from `mockData.ts`). Added `hasChildren` to each browse entry (`app/browse.py`, one extra bounded `scandir` per entry) so the tree can show an accurate expand arrow without a round trip per node — without it, every unexpanded folder looks like a leaf since react-arborist infers leaf status from the `children` array, and we don't know a folder's contents until we've fetched them. Verified live in-browser: real mount/kind labels, multi-level lazy expand, and leaf vs. expandable folders all matched a real test filesystem, with the selected path correctly captured on confirm.
- Closed a gap where the "Frontend built to static files, FastAPI serves them" constraint was aspirational but not actually implemented — the Dockerfile never built the frontend, so deploying the existing image would have served only the old Jinja dashboard, not the SPA this session had been testing in-browser. Added a `node:22-slim` build stage to `Dockerfile`, copied `frontend/dist` into the final image, and mounted it in `app/api.py` via `StaticFiles` at `/`, gated on a new `STATIC_DIR` env var (unset in local dev, where the Vite dev server runs separately). The old dashboard route moved from `/` to `/legacy` so it doesn't collide with the SPA mount, and `base.html`'s nav was updated accordingly — it's still fully functional, just no longer at the root path. Verified locally (without Docker itself, which isn't available in this dev environment) by running the built `frontend/dist` through `STATIC_DIR` against `uvicorn` directly: `/` serves the SPA, `/assets/*` serves its JS/CSS, `/legacy` still serves the old dashboard, and none of the JSON API routes (`/api/browse`, `/compare/*`, `/duplicates`, etc.) were swallowed by the static mount.
- Finished wiring comparison mode's scan and copy pipeline to the real backend, replacing the last of the simulated `setInterval`/`generateMockResults()` code in `ComparePage.tsx`. `frontend/src/api.ts` gained `startCompare`/`getCompareStatus`/`getCompareResults`/`startCopy`/`getCopyStatus`; `ComparePage.tsx` now polls status every 500ms through counting → scanning → hashing → ready (and copy status the same way), refetching results after both a completed comparison and a completed copy so the UI reflects server truth rather than optimistically patched local state. Added `vite.config.ts` proxy for `/compare` (only `/api` was proxied before, so `/compare/*` calls 404'd against the dev server). `mockData.ts` is deleted — nothing in the frontend uses fabricated data anymore.
- Fixed a StrictMode bug found while verifying the above: the polling loops' stop-guard (`stoppedRef`) was set to `true` in a `useEffect` cleanup but never reset to `false` on (re-)mount. React's dev-only StrictMode double-invokes effects once at startup (mount → cleanup → mount) specifically to catch this class of bug, which left every poll loop permanently wedged before the user ever clicked anything — the comparison would start, hit "Counting files…", and never move again. Fixed by setting the ref `false` at the top of the effect, not just `true` in its cleanup. Caught by actually running the full flow in-browser rather than trusting `tsc`/build success — this class of bug is invisible to type-checking.
- Full comparison + copy pipeline verified end-to-end against a real filesystem via the actual UI (not curl): correct matched/source-only/target-only counts, correct selected-size total on the copy button, real files landing at the right relative paths under target after copy, source left untouched, and the results table + source tree both refreshing to reflect the new state afterward.
