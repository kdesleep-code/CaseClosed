from __future__ import annotations

import sqlite3

from caseclosed.services import usb_backup


def test_encrypted_usb_backup_restores_database_and_files(tmp_path, monkeypatch) -> None:
    project = tmp_path / "project"
    data = project / "data"
    storage = data / "storage"
    storage.mkdir(parents=True)
    database = data / "caseclosed.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE sample (value TEXT NOT NULL)")
        connection.execute("INSERT INTO sample VALUES ('before')")
    (storage / "document.txt").write_text("original", encoding="utf-8")
    (project / "certs").mkdir(parents=True)
    (project / "certs/server.pfx").write_bytes(b"certificate")
    (project / "extensions/user-extensions").mkdir(parents=True)
    (project / "extensions/user-extensions/example.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(usb_backup, "PROJECT_ROOT", project)
    monkeypatch.setattr(usb_backup, "database_path", lambda: database)
    monkeypatch.setattr(usb_backup, "drafts_path", lambda: data / "caseclosed.drafts.sqlite3")
    monkeypatch.setattr(usb_backup, "storage_path", lambda: storage)
    mount = tmp_path / "usb"
    mount.mkdir()
    status = tmp_path / "backup-status.json"

    metadata = usb_backup.create_backup(mount, "usb-test", "correct horse battery", status)
    archive = mount / usb_backup.BACKUP_DIRECTORY_NAME / metadata["filename"]
    assert archive.read_bytes()[: len(usb_backup.MAGIC)] == usb_backup.MAGIC

    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE sample SET value = 'after'")
    (storage / "document.txt").write_text("changed", encoding="utf-8")
    usb_backup.restore_backup(archive, "correct horse battery", tmp_path / "restore-status.json")

    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT value FROM sample").fetchone() == ("before",)
    assert (storage / "document.txt").read_text(encoding="utf-8") == "original"


def test_usb_backup_rejects_wrong_passphrase(tmp_path, monkeypatch) -> None:
    project = tmp_path / "project"
    data = project / "data"
    (data / "storage").mkdir(parents=True)
    database = data / "caseclosed.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE sample (value TEXT)")
    monkeypatch.setattr(usb_backup, "PROJECT_ROOT", project)
    monkeypatch.setattr(usb_backup, "database_path", lambda: database)
    monkeypatch.setattr(usb_backup, "drafts_path", lambda: data / "drafts.sqlite3")
    monkeypatch.setattr(usb_backup, "storage_path", lambda: data / "storage")
    mount = tmp_path / "usb"
    mount.mkdir()
    metadata = usb_backup.create_backup(mount, "usb-test", "correct horse battery", tmp_path / "status.json")
    archive = mount / usb_backup.BACKUP_DIRECTORY_NAME / metadata["filename"]

    try:
        usb_backup.restore_backup(archive, "this password is wrong", tmp_path / "restore.json")
    except usb_backup.BackupError as error:
        assert "Incorrect passphrase" in str(error)
    else:
        raise AssertionError("Wrong passphrase was accepted")
