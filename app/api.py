from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from . import actions, browse, compare, compare_copy, config, db, grouping, scanner

app = FastAPI(title="dedupe")
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

_scan_running = False
_compare_running: int | None = None
_copy_running: int | None = None


def _run_scan_background() -> None:
    global _scan_running
    _scan_running = True
    try:
        scanner.run_scan()
    finally:
        _scan_running = False


@app.on_event("startup")
def _startup() -> None:
    db.init_db()


@app.get("/legacy", response_class=HTMLResponse)
def dashboard(request: Request):
    with db.connection() as conn:
        latest = conn.execute("SELECT * FROM scans ORDER BY id DESC LIMIT 1").fetchone()
        exact = grouping.exact_duplicate_groups(conn)
        similar = grouping.near_duplicate_groups(conn)
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "latest_scan": latest,
            "scan_running": _scan_running,
            "exact_count": len(exact),
            "similar_count": len(similar),
            "reclaimable_gb": grouping.reclaimable_bytes(exact) / (1024**3),
            "roots": [str(r) for r in config.SCAN_ROOTS],
        },
    )


@app.post("/scan")
def start_scan(background_tasks: BackgroundTasks):
    if not _scan_running:
        background_tasks.add_task(_run_scan_background)
    return RedirectResponse("/", status_code=303)


@app.get("/scan/status")
def scan_status():
    with db.connection() as conn:
        latest = conn.execute("SELECT * FROM scans ORDER BY id DESC LIMIT 1").fetchone()
    return {"running": _scan_running, "scan": dict(latest) if latest else None}


@app.get("/duplicates", response_class=HTMLResponse)
def duplicates(request: Request):
    with db.connection() as conn:
        groups = grouping.exact_duplicate_groups(conn)
    return templates.TemplateResponse(request, "duplicates.html", {"groups": groups})


@app.get("/similar", response_class=HTMLResponse)
def similar(request: Request):
    with db.connection() as conn:
        groups = grouping.near_duplicate_groups(conn)
    return templates.TemplateResponse(request, "similar.html", {"groups": groups})


@app.post("/stage/{file_id}")
def stage(file_id: int, return_to: str = Form("/duplicates")):
    with db.connection() as conn:
        try:
            actions.stage_file(conn, file_id)
        except FileNotFoundError:
            raise HTTPException(404, "file not found")
        except OSError as exc:
            raise HTTPException(500, str(exc))
    return RedirectResponse(return_to, status_code=303)


# --- Volume/Folder Comparison Mode ---


class CompareStartRequest(BaseModel):
    source_root: str
    target_root: str


class CopyRequest(BaseModel):
    file_ids: list[int]


@app.get("/api/browse")
def api_browse(path: str | None = None):
    try:
        entries = browse.list_children(path)
    except PermissionError as exc:
        raise HTTPException(403, str(exc))
    except NotADirectoryError as exc:
        raise HTTPException(400, f"not a directory: {exc}")
    except OSError as exc:
        raise HTTPException(500, str(exc))
    return {
        "path": path,
        "entries": [
            {"path": e.path, "name": e.name, "kind": e.kind, "hasChildren": e.has_children} for e in entries
        ],
    }


def _run_compare_background(run_id: int, source_root: str, target_root: str) -> None:
    global _compare_running
    try:
        compare.run_compare(run_id, source_root, target_root)
    finally:
        _compare_running = None


@app.post("/compare/start")
def start_compare(body: CompareStartRequest, background_tasks: BackgroundTasks):
    global _compare_running
    if _compare_running is not None:
        raise HTTPException(409, "a comparison is already running")

    source = Path(body.source_root)
    target = Path(body.target_root)
    if not source.is_dir():
        raise HTTPException(400, f"source root does not exist: {source}")
    if not target.is_dir():
        raise HTTPException(400, f"target root does not exist: {target}")

    run_id = compare.create_run(str(source), str(target))
    _compare_running = run_id
    background_tasks.add_task(_run_compare_background, run_id, str(source), str(target))
    return {"run_id": run_id}


@app.get("/compare/{run_id}/status")
def compare_status(run_id: int):
    with db.connection() as conn:
        row = conn.execute("SELECT * FROM compare_runs WHERE id = ?", (run_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "no such compare run")
    return {
        "phase": row["phase"],
        "filesTotal": row["files_total"],
        "filesDone": row["files_done"],
        "error": row["error"],
    }


@app.get("/compare/{run_id}/results")
def compare_results(run_id: int):
    with db.connection() as conn:
        run = conn.execute("SELECT id FROM compare_runs WHERE id = ?", (run_id,)).fetchone()
        if run is None:
            raise HTTPException(404, "no such compare run")
        files = compare.get_results(conn, run_id)
    return {"files": files}


def _run_copy_background(run_id: int, file_ids: list[int]) -> None:
    global _copy_running
    try:
        compare_copy.copy_selected(run_id, file_ids)
    finally:
        _copy_running = None


@app.post("/compare/{run_id}/copy")
def start_copy(run_id: int, body: CopyRequest, background_tasks: BackgroundTasks):
    global _copy_running
    if _copy_running is not None:
        raise HTTPException(409, "a copy is already running")
    if not body.file_ids:
        raise HTTPException(400, "file_ids is empty")

    with db.connection() as conn:
        run = conn.execute("SELECT id FROM compare_runs WHERE id = ?", (run_id,)).fetchone()
    if run is None:
        raise HTTPException(404, "no such compare run")

    _copy_running = run_id
    background_tasks.add_task(_run_copy_background, run_id, body.file_ids)
    return {"status": "started", "count": len(body.file_ids)}


@app.get("/compare/{run_id}/copy/status")
def copy_status(run_id: int):
    with db.connection() as conn:
        row = conn.execute(
            "SELECT copy_phase, copy_total, copy_done, copy_error FROM compare_runs WHERE id = ?", (run_id,)
        ).fetchone()
    if row is None:
        raise HTTPException(404, "no such compare run")
    return {
        "phase": row["copy_phase"],
        "total": row["copy_total"],
        "done": row["copy_done"],
        "error": row["copy_error"],
    }


# Serves the built React SPA (frontend/dist, baked into the image at Docker
# build time). Mounted last so it only catches paths no route above matched
# — e.g. "/", "/assets/*". Unset locally, where the frontend runs via
# `npm run dev` against this API instead.
if config.STATIC_DIR is not None and config.STATIC_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(config.STATIC_DIR), html=True), name="frontend")
