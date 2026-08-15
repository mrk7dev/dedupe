import csv
from datetime import datetime, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from . import db
from .formatting import human_bytes
from .grouping import (
    categorize_by_size,
    exact_duplicate_groups,
    near_duplicate_groups,
    reclaimable_bytes,
    size_bucket,
)

TEMPLATES_DIR = Path(__file__).parent / "templates"


def _env() -> Environment:
    env = Environment(loader=FileSystemLoader(TEMPLATES_DIR), autoescape=select_autoescape())
    env.filters["human_bytes"] = human_bytes
    return env


def generate_html_report(output_path: Path) -> Path:
    with db.connection() as conn:
        exact = exact_duplicate_groups(conn)
        similar = near_duplicate_groups(conn)

    exact_categories = categorize_by_size(exact)
    similar_categories = categorize_by_size(similar, bucket_key=lambda g: max(f.size for f in g.files))

    template = _env().get_template("report.html")
    html = template.render(
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        exact_groups=exact,
        similar_groups=similar,
        exact_categories=exact_categories,
        similar_categories=similar_categories,
        exact_file_count=sum(len(g.files) for g in exact),
        exact_extra_count=sum(len(g.files) - 1 for g in exact),
        similar_file_count=sum(len(g.files) for g in similar),
        exact_reclaimable=reclaimable_bytes(exact),
        similar_reclaimable=reclaimable_bytes(similar),
    )
    output_path.write_text(html)
    return output_path


def generate_csv_report(output_path: Path) -> Path:
    with db.connection() as conn:
        exact = exact_duplicate_groups(conn)

    with output_path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["group_id", "size_category", "path", "size_bytes", "mtime"])
        for i, group in enumerate(exact, start=1):
            category = size_bucket(group.files[0].size)
            for file in group.files:
                writer.writerow([i, category, file.path, file.size, file.mtime])
    return output_path
