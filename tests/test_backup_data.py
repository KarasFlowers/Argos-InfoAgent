import json
import sqlite3
import zipfile

from scripts.backup_data import create_backup


def test_create_backup_includes_sqlite_snapshot_and_chroma_files(tmp_path):
    data_dir = tmp_path / "data"
    sqlite_dir = data_dir / "sqlite"
    chroma_dir = data_dir / "chroma" / "collection"
    sqlite_dir.mkdir(parents=True)
    chroma_dir.mkdir(parents=True)

    db_path = sqlite_dir / "argos.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE item (id INTEGER PRIMARY KEY, name TEXT NOT NULL)")
        conn.execute("INSERT INTO item (name) VALUES ('hello')")
        conn.commit()
    (chroma_dir / "index.bin").write_bytes(b"vector-index")

    archive_path = create_backup(
        data_dir=data_dir,
        output_dir=tmp_path / "backups",
        timestamp="20260626-120000",
    )

    assert archive_path.name == "argos-backup-20260626-120000.zip"
    with zipfile.ZipFile(archive_path) as archive:
        names = set(archive.namelist())
        assert "sqlite/argos.db" in names
        assert "chroma/collection/index.bin" in names
        manifest_text = archive.read("MANIFEST.json").decode("utf-8")
        manifest = json.loads(manifest_text)
        assert str(tmp_path) not in manifest_text
        assert "data_dir" not in manifest
        assert "source" not in manifest["sqlite"]
        assert "source" not in manifest["chroma"]
        assert manifest["format"] == "argos-backup-v1"
        assert manifest["sqlite"]["path"] == "sqlite/argos.db"
        assert manifest["chroma"]["path"] == "chroma/"
        assert manifest["sqlite"]["included"] is True
        assert manifest["chroma"]["included"] is True
        assert manifest["chroma"]["file_count"] == 1

        extracted_db = tmp_path / "restored.db"
        extracted_db.write_bytes(archive.read("sqlite/argos.db"))

    with sqlite3.connect(extracted_db) as conn:
        assert conn.execute("SELECT name FROM item").fetchone() == ("hello",)


def test_create_backup_can_skip_chroma(tmp_path):
    data_dir = tmp_path / "data"
    sqlite_dir = data_dir / "sqlite"
    chroma_dir = data_dir / "chroma"
    sqlite_dir.mkdir(parents=True)
    chroma_dir.mkdir(parents=True)

    with sqlite3.connect(sqlite_dir / "argos.db") as conn:
        conn.execute("CREATE TABLE item (id INTEGER PRIMARY KEY)")
    (chroma_dir / "index.bin").write_bytes(b"vector-index")

    archive_path = create_backup(
        data_dir=data_dir,
        output_dir=tmp_path / "backups",
        include_chroma=False,
        timestamp="20260626-120001",
    )

    with zipfile.ZipFile(archive_path) as archive:
        names = set(archive.namelist())
        assert "sqlite/argos.db" in names
        assert "chroma/index.bin" not in names
        manifest = json.loads(archive.read("MANIFEST.json"))
        assert manifest["chroma"]["included"] is False
        assert manifest["chroma"]["file_count"] == 0


def test_create_backup_skips_chroma_symlinks(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    sqlite_dir = data_dir / "sqlite"
    chroma_dir = data_dir / "chroma"
    sqlite_dir.mkdir(parents=True)
    chroma_dir.mkdir(parents=True)
    symlink_path = chroma_dir / "external-secret.txt"
    symlink_path.write_text("do-not-back-up", encoding="utf-8")

    with sqlite3.connect(sqlite_dir / "argos.db") as conn:
        conn.execute("CREATE TABLE item (id INTEGER PRIMARY KEY)")

    path_type = type(symlink_path)
    original_is_symlink = path_type.is_symlink

    def fake_is_symlink(path):
        if path == symlink_path:
            return True
        return original_is_symlink(path)

    monkeypatch.setattr(path_type, "is_symlink", fake_is_symlink)

    archive_path = create_backup(
        data_dir=data_dir,
        output_dir=tmp_path / "backups",
        timestamp="20260626-120003",
    )

    with zipfile.ZipFile(archive_path) as archive:
        names = set(archive.namelist())
        manifest = json.loads(archive.read("MANIFEST.json"))

    assert "chroma/external-secret.txt" not in names
    assert manifest["chroma"]["file_count"] == 0


def test_create_backup_does_not_overwrite_same_timestamp_archive(tmp_path):
    data_dir = tmp_path / "data"
    sqlite_dir = data_dir / "sqlite"
    sqlite_dir.mkdir(parents=True)
    with sqlite3.connect(sqlite_dir / "argos.db") as conn:
        conn.execute("CREATE TABLE item (id INTEGER PRIMARY KEY)")

    first = create_backup(data_dir=data_dir, output_dir=tmp_path / "backups", timestamp="20260626-120002")
    first.write_bytes(b"existing-backup")

    second = create_backup(data_dir=data_dir, output_dir=tmp_path / "backups", timestamp="20260626-120002")

    assert first.name == "argos-backup-20260626-120002.zip"
    assert second.name == "argos-backup-20260626-120002-1.zip"
    assert first.read_bytes() == b"existing-backup"
