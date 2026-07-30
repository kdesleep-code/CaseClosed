from __future__ import annotations

import base64
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import struct
import subprocess
import tarfile
import time
from uuid import uuid4

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from caseclosed.db.runtime import jst_iso
from caseclosed.settings import get_database_url, get_mail_drafts_database_path, get_storage_root

PROJECT_ROOT = Path(__file__).resolve().parents[4]
STATUS_DIRECTORY = PROJECT_ROOT / ".tmp/usb-backup-operations"
BACKUP_DIRECTORY_NAME = "CaseClosed Backups"
BACKUP_EXTENSION = ".ccbackup"
MAGIC = b"CASECLSD-BACKUP\0"
FORMAT_VERSION = 1
MINIMUM_PASSPHRASE_LENGTH = 12


class BackupError(RuntimeError):
    pass


def absolute_path(path: Path) -> Path:
    return path if path.is_absolute() else (PROJECT_ROOT / path).resolve()


def database_path() -> Path:
    url = get_database_url()
    if not url.startswith("sqlite:///"):
        raise BackupError("USB backup currently supports SQLite only.")
    return absolute_path(Path(url.removeprefix("sqlite:///")))


def drafts_path() -> Path:
    return absolute_path(get_mail_drafts_database_path())


def storage_path() -> Path:
    return absolute_path(get_storage_root())


def write_status(path: Path, **values: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps({"updated_at": jst_iso(), **values}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def validate_passphrase(value: str) -> None:
    if len(value) < MINIMUM_PASSPHRASE_LENGTH:
        raise BackupError("Passphrase must be at least 12 characters.")


def sqlite_snapshot(source: Path, destination: Path) -> None:
    if not source.is_file():
        raise BackupError(f"SQLite database does not exist: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    source_db = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    destination_db = sqlite3.connect(destination)
    try:
        source_db.backup(destination_db)
        if destination_db.execute("PRAGMA integrity_check").fetchone() != ("ok",):
            raise BackupError("SQLite snapshot integrity check failed.")
    finally:
        destination_db.close()
        source_db.close()


def key(passphrase: str, salt: bytes) -> bytes:
    return Scrypt(salt=salt, length=32, n=2**15, r=8, p=1).derive(passphrase.encode())


def encrypt_file(source: Path, destination: Path, passphrase: str) -> str:
    salt, nonce = os.urandom(16), os.urandom(12)
    header = json.dumps(
        {"version": FORMAT_VERSION, "salt": base64.b64encode(salt).decode(), "nonce": base64.b64encode(nonce).decode()},
        separators=(",", ":"),
    ).encode()
    prefix = MAGIC + struct.pack(">I", len(header)) + header
    encryptor = Cipher(algorithms.AES(key(passphrase, salt)), modes.GCM(nonce)).encryptor()
    encryptor.authenticate_additional_data(prefix)
    digest = hashlib.sha256()
    with source.open("rb") as incoming, destination.open("wb") as outgoing:
        outgoing.write(prefix)
        digest.update(prefix)
        while chunk := incoming.read(1024 * 1024):
            encrypted = encryptor.update(chunk)
            outgoing.write(encrypted)
            digest.update(encrypted)
        final = encryptor.finalize()
        outgoing.write(final)
        outgoing.write(encryptor.tag)
        digest.update(final)
        digest.update(encryptor.tag)
        outgoing.flush()
        os.fsync(outgoing.fileno())
    return digest.hexdigest()


def decrypt_file(source: Path, destination: Path, passphrase: str) -> None:
    with source.open("rb") as incoming:
        magic, length_data = incoming.read(len(MAGIC)), incoming.read(4)
        if magic != MAGIC or len(length_data) != 4:
            raise BackupError("This is not a C@seClosed backup.")
        length = struct.unpack(">I", length_data)[0]
        header_data = incoming.read(length)
        prefix = magic + length_data + header_data
        try:
            header = json.loads(header_data)
            salt = base64.b64decode(header["salt"], validate=True)
            nonce = base64.b64decode(header["nonce"], validate=True)
        except Exception as error:
            raise BackupError("Backup header is invalid.") from error
        start = incoming.tell()
        incoming.seek(-16, os.SEEK_END)
        tag, end = incoming.read(16), incoming.tell() - 16
        incoming.seek(start)
        decryptor = Cipher(algorithms.AES(key(passphrase, salt)), modes.GCM(nonce, tag)).decryptor()
        decryptor.authenticate_additional_data(prefix)
        remaining = end - start
        try:
            with destination.open("wb") as outgoing:
                while remaining:
                    chunk = incoming.read(min(1024 * 1024, remaining))
                    remaining -= len(chunk)
                    outgoing.write(decryptor.update(chunk))
                outgoing.write(decryptor.finalize())
        except InvalidTag as error:
            destination.unlink(missing_ok=True)
            raise BackupError("Incorrect passphrase or damaged backup.") from error


def create_backup(mount_point: Path, device_id: str, passphrase: str, status_file: Path) -> dict[str, object]:
    validate_passphrase(passphrase)
    operation_id = status_file.stem
    backup_id = f"caseclosed-{time.strftime('%Y%m%d-%H%M%S')}-{uuid4().hex[:8]}"
    directory = mount_point / BACKUP_DIRECTORY_NAME
    directory.mkdir(parents=True, exist_ok=True)
    work = directory / f".{backup_id}.work"
    archive = directory / f".{backup_id}.tar.gz"
    encrypted = directory / f"{backup_id}{BACKUP_EXTENSION}.partial"
    final = directory / f"{backup_id}{BACKUP_EXTENSION}"
    includes: list[str] = []
    try:
        write_status(status_file, operation_id=operation_id, operation="backup", status="running", stage="snapshot_database")
        work.mkdir()
        sqlite_snapshot(database_path(), work / "caseclosed.sqlite3")
        if drafts_path().is_file():
            sqlite_snapshot(drafts_path(), work / "caseclosed.drafts.sqlite3")
        manifest = {"format_version": FORMAT_VERSION, "backup_id": backup_id, "created_at": jst_iso(), "excluded": [".env", "data/backups", "logs", ".tmp"]}
        (work / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        write_status(status_file, operation_id=operation_id, operation="backup", status="running", stage="writing_archive", backup_id=backup_id)
        with tarfile.open(archive, "w:gz") as tar:
            tar.add(work / "manifest.json", "manifest.json")
            tar.add(work / "caseclosed.sqlite3", "payload/database/caseclosed.sqlite3")
            includes.append("database")
            if (work / "caseclosed.drafts.sqlite3").is_file():
                tar.add(work / "caseclosed.drafts.sqlite3", "payload/database/caseclosed.drafts.sqlite3")
                includes.append("mail_drafts")
            for path, name, label in ((storage_path(), "payload/storage", "storage"), (PROJECT_ROOT / "certs", "payload/certs", "certificates"), (PROJECT_ROOT / "extensions/user-extensions", "payload/extensions/user-extensions", "user_extensions")):
                if path.exists():
                    tar.add(path, name)
                    includes.append(label)
        write_status(status_file, operation_id=operation_id, operation="backup", status="running", stage="encrypting", backup_id=backup_id)
        checksum = encrypt_file(archive, encrypted, passphrase)
        os.replace(encrypted, final)
        metadata = {"backup_id": backup_id, "filename": final.name, "created_at": manifest["created_at"], "byte_size": final.stat().st_size, "sha256_hex": checksum, "encrypted": True, "device_id": device_id, "includes": includes}
        (directory / f"{backup_id}.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        write_status(status_file, operation_id=operation_id, operation="backup", status="succeeded", stage="completed", backup=metadata)
        return metadata
    except Exception as error:
        write_status(status_file, operation_id=operation_id, operation="backup", status="failed", stage="failed", error_message=str(error))
        raise
    finally:
        shutil.rmtree(work, ignore_errors=True)
        archive.unlink(missing_ok=True)
        encrypted.unlink(missing_ok=True)


def safe_extract(archive: Path, destination: Path) -> dict[str, object]:
    allowed = ("manifest.json", "payload/database/", "payload/storage/", "payload/certs/", "payload/extensions/user-extensions/")
    with tarfile.open(archive, "r:gz") as tar:
        for member in tar.getmembers():
            if not any(
                member.name == prefix.rstrip("/") or member.name.startswith(prefix)
                for prefix in allowed
            ):
                raise BackupError(f"Unexpected backup path: {member.name}")
            if member.issym() or member.islnk() or member.isdev():
                raise BackupError(f"Unsafe backup entry: {member.name}")
            target = (destination / member.name).resolve()
            if destination.resolve() not in target.parents and target != destination.resolve():
                raise BackupError(f"Backup path escapes destination: {member.name}")
        tar.extractall(destination, filter="data")
    manifest = json.loads((destination / "manifest.json").read_text(encoding="utf-8"))
    restored_db = destination / "payload/database/caseclosed.sqlite3"
    connection = sqlite3.connect(restored_db)
    try:
        if connection.execute("PRAGMA integrity_check").fetchone() != ("ok",):
            raise BackupError("Restored SQLite integrity check failed.")
    finally:
        connection.close()
    return manifest


def replace_file(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.restore-{uuid4().hex}")
    shutil.copy2(source, temporary)
    os.replace(temporary, destination)


def replace_directory(source: Path | None, destination: Path) -> None:
    replacement = destination.with_name(f".{destination.name}.restore-{uuid4().hex}")
    previous = destination.with_name(f".{destination.name}.previous-{uuid4().hex}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, replacement) if source and source.exists() else replacement.mkdir()
    moved = False
    try:
        if destination.exists():
            os.replace(destination, previous)
            moved = True
        os.replace(replacement, destination)
    except Exception:
        shutil.rmtree(replacement, ignore_errors=True)
        if moved and not destination.exists():
            os.replace(previous, destination)
        raise
    shutil.rmtree(previous, ignore_errors=True)


def restore_backup(backup: Path, passphrase: str, status_file: Path) -> dict[str, object]:
    validate_passphrase(passphrase)
    operation_id = status_file.stem
    work = PROJECT_ROOT / ".tmp/usb-restore-work" / operation_id
    archive = work / "backup.tar.gz"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    try:
        write_status(status_file, operation_id=operation_id, operation="restore", status="running", stage="decrypting")
        decrypt_file(backup, archive, passphrase)
        write_status(status_file, operation_id=operation_id, operation="restore", status="running", stage="validating_backup")
        extracted = work / "extracted"
        extracted.mkdir()
        manifest = safe_extract(archive, extracted)
        payload = extracted / "payload"
        write_status(status_file, operation_id=operation_id, operation="restore", status="running", stage="replacing_data", backup_id=manifest.get("backup_id"))
        target_db = database_path()
        if target_db.is_file():
            sqlite_snapshot(target_db, target_db.parent / "backups" / f"caseclosed-before-usb-restore-{time.strftime('%Y%m%d-%H%M%S')}.sqlite3")
        replace_file(payload / "database/caseclosed.sqlite3", target_db)
        restored_drafts = payload / "database/caseclosed.drafts.sqlite3"
        if restored_drafts.is_file():
            replace_file(restored_drafts, drafts_path())
        replace_directory(payload / "storage" if (payload / "storage").exists() else None, storage_path())
        replace_directory(payload / "certs" if (payload / "certs").exists() else None, PROJECT_ROOT / "certs")
        extensions = payload / "extensions/user-extensions"
        replace_directory(extensions if extensions.exists() else None, PROJECT_ROOT / "extensions/user-extensions")
        write_status(status_file, operation_id=operation_id, operation="restore", status="succeeded", stage="restart_required", backup_id=manifest.get("backup_id"))
        return manifest
    except Exception as error:
        write_status(status_file, operation_id=operation_id, operation="restore", status="failed", stage="failed", error_message=str(error))
        raise
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    for command, arguments in {
        "create": ("mount-point", "device-id"),
        "restore": ("backup-path",),
    }.items():
        child = commands.add_parser(command)
        for argument in (*arguments, "passphrase-file", "status-file"):
            child.add_argument(f"--{argument}", required=True)
        if command == "restore":
            child.add_argument("--restart-script")
    args = parser.parse_args()
    passphrase_file = Path(args.passphrase_file)
    try:
        passphrase = passphrase_file.read_text(encoding="utf-8")
    finally:
        passphrase_file.unlink(missing_ok=True)
    try:
        if args.command == "create":
            create_backup(Path(args.mount_point), args.device_id, passphrase, Path(args.status_file))
        else:
            restore_backup(Path(args.backup_path), passphrase, Path(args.status_file))
            if args.restart_script:
                subprocess.Popen([args.restart_script], cwd=PROJECT_ROOT, start_new_session=True)
    except Exception:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
