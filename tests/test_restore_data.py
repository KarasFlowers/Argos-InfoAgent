import sqlite3
import zipfile
from contextlib import closing

import pytest

from scripts.backup_data import create_backup
from scripts.restore_data import inspect_backup, restore_backup


def _create_source_data(data_dir):
    sqlite_dir = data_dir / "sqlite"
    chroma_dir = data_dir / "chroma" / "collection"
    sqlite_dir.mkdir(parents=True)
    chroma_dir.mkdir(parents=True)
    with closing(sqlite3.connect(sqlite_dir / "argos.db")) as conn:
        conn.execute("CREATE TABLE item (id INTEGER PRIMARY KEY, name TEXT NOT NULL)")
        conn.execute("INSERT INTO item (name) VALUES ('restored')")
        conn.commit()
    (chroma_dir / "index.bin").write_bytes(b"vector-index")


def test_restore_backup_restores_sqlite_and_chroma(tmp_path):
    source_data = tmp_path / "source-data"
    target_data = tmp_path / "target-data"
    _create_source_data(source_data)
    archive = create_backup(data_dir=source_data, output_dir=tmp_path / "backups", timestamp="20260626-130000")

    restored = restore_backup(archive, data_dir=target_data)

    assert target_data / "sqlite" / "argos.db" in restored
    assert target_data / "chroma" in restored
    with sqlite3.connect(target_data / "sqlite" / "argos.db") as conn:
        assert conn.execute("SELECT name FROM item").fetchone() == ("restored",)
    assert (target_data / "chroma" / "collection" / "index.bin").read_bytes() == b"vector-index"


def test_restore_backup_refuses_to_overwrite_without_force(tmp_path):
    source_data = tmp_path / "source-data"
    target_data = tmp_path / "target-data"
    _create_source_data(source_data)
    _create_source_data(target_data)
    archive = create_backup(data_dir=source_data, output_dir=tmp_path / "backups", timestamp="20260626-130001")

    with pytest.raises(FileExistsError):
        restore_backup(archive, data_dir=target_data)


def test_restore_backup_force_overwrites_existing_data(tmp_path):
    source_data = tmp_path / "source-data"
    target_data = tmp_path / "target-data"
    _create_source_data(source_data)
    _create_source_data(target_data)
    (target_data / "chroma" / "old.bin").write_bytes(b"old")
    archive = create_backup(data_dir=source_data, output_dir=tmp_path / "backups", timestamp="20260626-130002")

    restore_backup(archive, data_dir=target_data, force=True)

    assert not (target_data / "chroma" / "old.bin").exists()
    assert (target_data / "chroma" / "collection" / "index.bin").exists()


def test_restore_backup_rejects_unsafe_archive_paths(tmp_path):
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as zip_file:
        zip_file.writestr("../evil.txt", "bad")

    with pytest.raises(ValueError, match="Unsafe archive path"):
        restore_backup(archive, data_dir=tmp_path / "target")


def test_inspect_backup_reports_targets_without_writing(tmp_path):
    source_data = tmp_path / "source-data"
    target_data = tmp_path / "target-data"
    _create_source_data(source_data)
    archive = create_backup(data_dir=source_data, output_dir=tmp_path / "backups", timestamp="20260626-130003")

    targets = inspect_backup(archive, data_dir=target_data)

    assert targets == [target_data / "sqlite" / "argos.db", target_data / "chroma"]
    assert not target_data.exists()


def test_inspect_backup_rejects_unsafe_archive_paths(tmp_path):
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as zip_file:
        zip_file.writestr("../evil.txt", "bad")

    with pytest.raises(ValueError, match="Unsafe archive path"):
        inspect_backup(archive, data_dir=tmp_path / "target")
