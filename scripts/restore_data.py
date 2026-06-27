"""Restore an Argos backup archive created by scripts/backup_data.py."""

from __future__ import annotations

import argparse
import shutil
import tempfile
import zipfile
from pathlib import Path

DEFAULT_DATA_DIR = Path("data")


def _safe_extract(archive: zipfile.ZipFile, target_dir: Path) -> None:
    target_root = target_dir.resolve()
    for member in archive.infolist():
        destination = (target_dir / member.filename).resolve()
        if destination != target_root and target_root not in destination.parents:
            raise ValueError(f"Unsafe archive path: {member.filename}")
    archive.extractall(target_dir)


def _has_files(path: Path) -> bool:
    return path.exists() and any(path.rglob("*"))


def inspect_backup(
    archive_path: Path,
    *,
    data_dir: Path = DEFAULT_DATA_DIR,
    include_chroma: bool = True,
) -> list[Path]:
    """Return the target paths that would be restored, validating archive safety."""
    if not archive_path.exists():
        raise FileNotFoundError(f"Backup archive not found: {archive_path}")

    targets: list[Path] = []
    with tempfile.TemporaryDirectory(prefix="argos-restore-inspect-") as temp_name:
        temp_dir = Path(temp_name)
        with zipfile.ZipFile(archive_path) as archive:
            _safe_extract(archive, temp_dir)

        if (temp_dir / "sqlite" / "argos.db").exists():
            targets.append(data_dir / "sqlite" / "argos.db")
        if include_chroma and (temp_dir / "chroma").exists():
            targets.append(data_dir / "chroma")

    if not targets:
        raise ValueError("Backup archive did not contain sqlite/argos.db or chroma/ data.")
    return targets


def restore_backup(
    archive_path: Path,
    *,
    data_dir: Path = DEFAULT_DATA_DIR,
    force: bool = False,
    include_chroma: bool = True,
) -> list[Path]:
    if not archive_path.exists():
        raise FileNotFoundError(f"Backup archive not found: {archive_path}")

    restored: list[Path] = []
    with tempfile.TemporaryDirectory(prefix="argos-restore-") as temp_name:
        temp_dir = Path(temp_name)
        with zipfile.ZipFile(archive_path) as archive:
            _safe_extract(archive, temp_dir)

        sqlite_source = temp_dir / "sqlite" / "argos.db"
        sqlite_target = data_dir / "sqlite" / "argos.db"
        if sqlite_source.exists():
            if sqlite_target.exists() and not force:
                raise FileExistsError(f"{sqlite_target} already exists; pass --force to overwrite it.")
            sqlite_target.parent.mkdir(parents=True, exist_ok=True)
            for suffix in ("", "-wal", "-shm"):
                candidate = sqlite_target.parent / f"{sqlite_target.name}{suffix}"
                if candidate.exists():
                    candidate.unlink()
            shutil.copy2(sqlite_source, sqlite_target)
            restored.append(sqlite_target)

        chroma_source = temp_dir / "chroma"
        chroma_target = data_dir / "chroma"
        if include_chroma and chroma_source.exists():
            if _has_files(chroma_target) and not force:
                raise FileExistsError(f"{chroma_target} already has files; pass --force to overwrite it.")
            if chroma_target.exists():
                shutil.rmtree(chroma_target)
            shutil.copytree(chroma_source, chroma_target)
            restored.append(chroma_target)

    if not restored:
        raise ValueError("Backup archive did not contain sqlite/argos.db or chroma/ data.")
    return restored


def main() -> int:
    parser = argparse.ArgumentParser(description="Restore an Argos backup archive.")
    parser.add_argument("archive", type=Path, help="Backup zip created by scripts/backup_data.py.")
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR, help="Target Argos data directory.")
    parser.add_argument("--force", action="store_true", help="Overwrite existing SQLite/Chroma data.")
    parser.add_argument("--no-chroma", action="store_true", help="Restore only sqlite/argos.db.")
    parser.add_argument(
        "--dry-run", action="store_true", help="Validate archive and print target paths without writing."
    )
    args = parser.parse_args()

    include_chroma = not args.no_chroma
    if args.dry_run:
        paths = inspect_backup(args.archive, data_dir=args.data_dir, include_chroma=include_chroma)
    else:
        paths = restore_backup(
            args.archive,
            data_dir=args.data_dir,
            force=args.force,
            include_chroma=include_chroma,
        )
    for path in paths:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
