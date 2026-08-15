from pathlib import Path

import typer
import uvicorn

from . import config, db, reports, scanner

app = typer.Typer(help="Duplicate file finder/reporter for Synology DiskStation volumes.")


@app.command()
def scan(
    root: list[str] = typer.Option(
        None, "--root", help="Path to scan; repeatable. Defaults to SCAN_ROOTS env var."
    ),
):
    """Walk the configured (or given) roots and update the duplicate index."""
    roots = root or [str(r) for r in config.SCAN_ROOTS]
    typer.echo(f"Scanning: {', '.join(roots)}")
    scan_id = scanner.run_scan(roots)
    with db.connection() as conn:
        row = conn.execute("SELECT * FROM scans WHERE id = ?", (scan_id,)).fetchone()
    typer.echo(f"Scan {scan_id}: {row['status']} — {row['files_seen']} files")


@app.command()
def report(
    out: Path = typer.Option(Path("report.html"), help="Output path (.html or .csv)."),
):
    """Generate a duplicate report from the current index (run `scan` first)."""
    if out.suffix == ".csv":
        reports.generate_csv_report(out)
    else:
        reports.generate_html_report(out)
    typer.echo(f"Wrote {out}")


@app.command()
def serve(
    host: str = typer.Option("0.0.0.0", help="Bind address."),
    port: int = typer.Option(8080, help="Bind port."),
):
    """Run the web UI."""
    db.init_db()
    uvicorn.run("app.api:app", host=host, port=port)


if __name__ == "__main__":
    app()
