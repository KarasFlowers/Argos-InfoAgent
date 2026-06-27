"""Create an Argos data backup archive.

The backup includes a consistent SQLite snapshot created through SQLite's
backup API and, by default, the Chroma vector store directory.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import tempfile
import zipfile
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

DEFAULT_DATA_DIR = Path("data")
DEFAULT_OUTPUT_DIR = Path("backups")


def _timestamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%d-%H%M%S")


def _backup_sqlite(source_db: Path, target_db: Path) -> bool:
    if not source_db.exists():
        return False
    target_db.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(source_db)) as source, closing(sqlite3.connect(target_db)) as target:
        source.backup(target)
    return True


def _write_dir_to_zip(archive: zipfile.ZipFile, source_dir: Path, archive_root: str) -> int:
    if not source_dir.exists():
        return 0
    count = 0
    for path in sorted(source_dir.rglob("*")):
        if path.is_symlink():
            continue
        if path.is_file():
            archive.write(path, Path(archive_root) / path.relative_to(source_dir))
            count += 1
    return count


def _unique_archive_path(output_dir: Path, timestamp: str) -> Path:
    archive_path = output_dir / f"argos-backup-{timestamp}.zip"
    if not archive_path.exists():
        return archive_path
    index = 1
    while True:
        candidate = output_dir / f"argos-backup-{timestamp}-{index}.zip"
        if not candidate.exists():
            return candidate
        index += 1


def create_backup(
    *,
    data_dir: Path = DEFAULT_DATA_DIR,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    include_chroma: bool = True,
    timestamp: str | None = None,
) -> Path:
    timestamp = timestamp or _timestamp()
    output_dir.mkdir(parents=True, exist_ok=True)
    archive_path = _unique_archive_path(output_dir, timestamp)

    sqlite_db = data_dir / "sqlite" / "argos.db"
    chroma_dir = data_dir / "chroma"

    with tempfile.TemporaryDirectory(prefix="argos-backup-") as temp_name:
        temp_dir = Path(temp_name)
        sqlite_snapshot = temp_dir / "sqlite" / "argos.db"
        sqlite_included = _backup_sqlite(sqlite_db, sqlite_snapshot)

        manifest = {
            "format": "argos-backup-v1",
            "created_at": datetime.now(UTC).isoformat(),
            "sqlite": {
                "path": "sqlite/argos.db",
                "included": sqlite_included,
            },
            "chroma": {
                "path": "chroma/",
                "included": include_chroma and chroma_dir.exists(),
            },
        }

        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            if sqlite_included:
                archive.write(sqlite_snapshot, "sqlite/argos.db")
            chroma_count = _write_dir_to_zip(archive, chroma_dir, "chroma") if include_chroma else 0
            manifest["chroma"]["file_count"] = chroma_count
            archive.writestr("MANIFEST.json", json.dumps(manifest, ensure_ascii=False, indent=2))

    return archive_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a zip backup of Argos SQLite and Chroma data.")
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR, help="Argos data directory.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="Directory for backup archives.")
    parser.add_argument("--no-chroma", action="store_true", help="Skip data/chroma in the backup archive.")
    args = parser.parse_args()

    archive_path = create_backup(
        data_dir=args.data_dir,
        output_dir=args.output_dir,
        include_chroma=not args.no_chroma,
    )
    print(archive_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
