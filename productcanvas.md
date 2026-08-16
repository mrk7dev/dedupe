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
- The app must never modify or delete original data. Enforced per-volume, not as a blanket Docker-level rule: each mounted volume is deliberately `:ro` or read-write in `docker-compose.yml` (a one-time choice per physical volume/drive), and the app never writes outside a currently-discovered browse root, nor to a root that isn't OS-writable — see "Write safety" under Volume/Folder Comparison Mode.
- "Remove" always means *move to a staging folder*, never a hard delete.
- CPU budget stays conservative — 2C/4T total, shared with DSM and other packages. Enforced via `WORKERS`, not a Docker `cpus:` limit — this DS923+'s DSM kernel has no CPU CFS bandwidth cgroup controller, so `docker compose`'s `deploy.resources.limits.cpus` fails outright ("NanoCPUs can not be set..."). `docker-compose.yml` only sets a memory limit; CPU stays bounded by keeping `WORKERS` modest.
- Comparison mode's target path is writable, additive-only, whichever volume it happens to live on. See "Volume/Folder Comparison Mode" below.

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

**Status: fully wired, no mock data left — but not yet verified on the real NAS.** Backend (`app/browse.py`, `app/compare.py`, `app/compare_copy.py`) implements all six endpoints, tested in `tests/test_compare.py`, `test_browse.py`, `test_config.py`, `test_api.py`. Frontend (`ComparePage.tsx`, `frontend/src/api.ts`) calls all of them for real: folder picking, starting a comparison, polling status through counting/scanning/hashing/ready, fetching results, selecting files, copying, and polling copy status — no `mockData.ts` left in the repo. Verified with a full live run in-browser against a real test filesystem, and separately against a locally-simulated whole-volume mount setup (using `chmod` to stand in for a real Docker `:ro` mount, since Docker itself isn't available in this dev environment): correct matched/source-only/target-only counts, correct selected-size total, real per-file copy that landed at the right relative paths under target, source left untouched, a read-only-mounted target correctly refused, and the results view refreshing afterward. **Pending:** an actual `docker compose up` on the DS923+ itself with the new whole-volume mount model hasn't happened yet — see Open Questions for what's still unconfirmed on real hardware, and note the NAS currently can't even `git pull` the latest code (DNS resolution failing for github.com — diagnosis was in progress, unresolved). The single-volume dashboard (`/legacy`) and the frontend build/serve pipeline (Dockerfile → FastAPI `StaticFiles`) are code-complete — see the constraints section above and the Decision log.

**Matching:** same staged hashing pipeline as today (size → partial hash → full hash). Content-only for v1 — no perceptual/near-dup matching (see Backlog). Hash results now persist across runs *and* survive interruption via a new `hash_cache` table (`app/db.py`), keyed by absolute path with the same `size`+`mtime` fingerprint-invalidation strategy the legacy scanner's `files` table already uses, generalized to tolerate partial/incremental writes. Writes flush every 50 hashed files during a run (piggybacking on the existing progress-update checkpoint), not just at completion — verified live that a hard `kill -9` mid-run still leaves everything up to the last checkpoint durably committed, and a retry afterward only rehashes what wasn't already cached.

**Results — three categories:**
- Matched: identical content exists on both sides.
- Source-only: exists on source, missing from target.
- Target-only: exists on target, not on source.

**UI is interactive, not a static report — React + Vite SPA:**
- Folder selection is a **modal dialog** (`FolderPickerModal`), triggered by a "Select folder…" button per side — not an always-open inline tree. Both source and target browse the *same* shared filesystem tree via the real `GET /api/browse`, since either side can be any folder on the NAS. Internal volumes and external/USB drives are visually distinguished (labeled "volume" vs "external drive") so mounted drives are identifiable, not just internal storage. Which top-level mounts appear here is auto-discovered server-side (see "Write safety" below) — no frontend change needed to expose a newly-mounted volume.
- Progress: count total files under the selected roots first, then show live progress as they're indexed/hashed (e.g. "1,204 / 8,530"), polled from the real `GET /compare/{id}/status` every 500ms through counting → scanning → hashing → ready.
- Results are browsable **two ways at once**, side by side: a flat, filterable table (`@tanstack/react-table` + `@tanstack/react-virtual`, stays responsive at real NAS scale) and a `SourceTreeView` folder tree rebuilt from the same results, with a "Show only missing files" toggle that prunes folders down to only the ones containing gaps — folders with nothing missing just don't appear, they're not merely hidden.
- Tree navigation: "Expand all" / "Collapse all" controls (via react-arborist's `TreeApi`), plus independent collapse/expand for each whole panel (source tree and results table each collapse down to just their header, independently of one another).
- Table columns: Path and Name are separate, independently resizable columns (drag handles on Path/Name/Size/Status), not one combined path string.
- Selection: checkboxes to select/deselect individual files from the missing-from-target view — selection state lives client-side in the SPA. The copy button shows both the **count and total size** of what's selected (e.g. "Copy 3 selected (7.7 MB) to target").
- Action: explicit "Copy selected to target" button — nothing copies without this being clicked. While copying, the button area is replaced by a **progress bar** (file-count based, e.g. "Copying 16 / 20"), reflecting real per-file copy progress polled from `GET /compare/{id}/copy/status`.

**Copy behavior (target write rules):**
- Additive only — creates new files on target, never modifies or deletes anything already there.
- Requires explicit confirmation via the select-then-copy flow; no automatic copying.
- Naming conflict (same filename at the destination, but different content since it wasn't matched): auto-rename the incoming copy, existing target file is never touched.

**Write safety (resolved, implemented):** browse roots (`GET /api/browse`, and by extension which folders are selectable at all) are auto-discovered from whichever `/volumeN` / `/volumeUSBn` mounts actually exist in the container (`app/config.py`'s `discover_browse_roots`) — no env var needed for the common case; `BROWSE_ROOTS` now only *adds* non-standard mount names on top, it no longer replaces the discovered list. Whether a compare run's target root may be copied to is gated by two checks in `app/compare_copy.py`'s `_assert_writable`: it must resolve inside a discovered browse root (`browse.is_under_browse_roots`, shared with `POST /compare/start`'s own validation of both roots), and it must be `os.access(..., os.W_OK)` — i.e. actually OS-writable. There's no separate writable allowlist to keep in sync: whichever volumes are mounted read-write in `docker-compose.yml` (a deliberate, one-time, per-volume choice) are automatically the valid copy targets, nothing more. Each individual copy destination is additionally re-checked to resolve inside the target root before writing, so path tricks (e.g. `..` segments) can't escape it.

## Open questions / up for reconsideration

*(This is the working section — add items here as they come up in planning conversations.)*

- Filename-based and timestamp-based duplicate detection were in the original ask but never built — still undecided whether that's wanted.
- Should target-only files (present on target, not source) get any action in the UI, or stay purely informational?
- Comparison mode is getting a real interactive UI (tree browser, live progress, selection). Should single-volume dedup mode eventually get upgraded to match, instead of its current env-var-driven config? Related: `SCAN_ROOTS` stays a separate static env var from the new whole-volume `BROWSE_ROOTS` auto-discovery — single-volume mode's "stage" (move-to-remove) feature needs write access to wherever `SCAN_ROOTS` points, so whichever volume it's on needs to be mounted read-write (not `:ro`) for staging to actually work; this is on the user to choose per their real mount setup, not something the app enforces or defaults for them.
- Live (no-restart) visibility for a drive attached *after* `docker compose up` isn't supported — Docker only sees mounts present at container start. `bind-propagation: rslave` on the relevant compose mount is a possible future improvement if this turns out to matter in practice; not done, since restart-to-see-a-new-drive was judged acceptable for now.
- `hash_cache` grows unbounded with no eviction — a stale row for a deleted/moved/renamed file just sits unused forever. Deferred; a future idea is a periodic sweep deleting rows whose `path` hasn't appeared in any `compare_files` row for N runs/days.
- mtime-granularity false-hit risk: `BROWSE_ROOTS` includes FUSE-mounted volumes like the Synology `/volumeUSB*` exFAT share debugged earlier this session — a filesystem that doesn't reliably preserve sub-second mtime precision across remounts is a real (not hypothetical) false-cache-hit vector, inherited from the same tradeoff the legacy scanner already accepts, but worth flagging since it's now live on a mount type known to be more exposed to it.

## Pending (blocking real deployment, as of this writing)

- **NAS can't reach GitHub.** `git pull` on the DS923+ fails with `Could not resolve host: github.com`, even though `nslookup github.com` from the same shell succeeds — points at the OS resolver path (`getaddrinfo`/NSS, used by git/curl) breaking separately from raw DNS queries (used by `nslookup`). Diagnosis was in progress (`getent hosts github.com`, `curl -v https://github.com`, `env | grep -i proxy` requested) but the output was never shared — possibly related to the earlier IPv6-disable-and-reboot done to fix a separate Docker Hub connectivity issue, not confirmed. Until this resolves, the NAS is still running whatever code was last pulled — the whole-volume mount redesign hasn't reached it yet.
- **Whole-volume mount redesign (`discover_browse_roots`, `os.access`-based writability, `docker-compose.yml`'s new mount model) is implemented, tested, and verified only in this dev environment** — via local `uvicorn` runs against a `chmod`-simulated `:ro` mount, since Docker isn't available here. Never yet run through an actual `docker compose up` on the DS923+. Once the NAS can pull again, still need to confirm on real hardware: Container Manager accepts a whole-`/volume1`-style bind mount without permission surprises; the real DSM path shape for a mounted USB drive (likely `/volumeUSB1/usbshare1`, one level deeper than the bare `/volumeUSB1` the auto-discovery candidate list currently checks — may need the compose file's `BROWSE_ROOTS` override or a candidate-list adjustment); a drive attached after `docker compose up` does need a restart to appear, as expected.
- **The user's real `docker-compose.yml` on the NAS needs re-editing, not just re-pulling.** The mount structure changed completely (host-path-aliased `/data/photos`-style mounts → 1:1 whole-volume mounts with a per-volume `:ro`/read-write choice) — the version in git is a template with placeholder volume assignments (`/volume1:ro`, `/volume2` writable) that needs adapting to the user's actual volumes/drives and which one(s) should be copy targets.
- **The dot-prefixed `.dedupe` folder recommendation for `/config`/`/staging`** (keeps the app's own DB/staging folder out of the browse picker) isn't reflected in whatever the user's real host folder is currently named — needs a matching rename on the NAS, or the compose mount path adjusted back to the old name, whichever the user prefers. Not yet actioned either way.

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
- Removed the `cpus:` limit from `docker-compose.yml`'s `deploy.resources.limits` — this DS923+'s DSM kernel doesn't have the CPU CFS bandwidth cgroup controller enabled, so Docker refused to start the container at all ("NanoCPUs can not be set, as your kernel does not support CPU CFS scheduler..."). Found on an actual deploy attempt on the real NAS, not something a local Mac/Colima build would have caught (Colima's Lima VM kernel does support it). CPU stays bounded via `WORKERS` instead; only the memory limit is still enforced through Docker.
- Retired `BROWSE_ROOTS`/`WRITABLE_ROOTS` as manually-synced env vars kept in lockstep with narrow, purpose-specific `docker-compose.yml` bind mounts (`/data/photos`, `/data/compare-target`, etc.) — every new folder required editing both the mount list and the matching env var. Replaced with: whole top-level Synology volumes mounted 1:1 (host path == container path), each individually `:ro` or read-write per volume, chosen once when the volume is added; `BROWSE_ROOTS` auto-discovered at runtime from Synology's stable `/volumeN`/`/volumeUSBn` naming convention (`app/config.py`'s `discover_browse_roots`); `WRITABLE_ROOTS` dropped entirely in favor of checking the real `os.access(..., os.W_OK)` permission at copy time. Explicit design choice, confirmed with the user: mount permission alone gates whether a volume is a valid comparison-mode copy target — no separate allowlist on top, even though that means mounting a volume read-write for any other reason also makes it copyable to.
- Along the way, closed two gaps found while implementing this: `POST /compare/start` never validated `source_root`/`target_root` were under a browse root at all (only the folder-picker's own `GET /api/browse` enforced that) — now shares the same `browse.is_under_browse_roots` check, made public for this reason. And `app/browse.py` had zero test coverage before this change (`tests/test_browse.py` added).
- Found and fixed a real ordering bug while verifying the new writability check live (not caught by the existing test suite, since it only exercised `compare_copy.copy_selected` directly, synchronously): `_assert_writable` was called *before* `copy_phase` was ever set to `'running'`, so when it raised, `POST /compare/{id}/copy`'s background task failed silently — the run's `copy_phase` stayed `null` forever instead of reporting `'error'`, which would leave the frontend's status-polling loop hanging indefinitely on a refused copy. Fixed by moving the writability check to run after `copy_phase` is set, inside the same try/except that already handles per-run failures.
