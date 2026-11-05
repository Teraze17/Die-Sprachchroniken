"""Manual, owner-approved SQLite snapshot exchange for Windows and Railway.

Export uses SQLite's online backup API; restore keeps a durable local rollback
copy and verifies the incoming database before touching the live connection.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
import uuid
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


PROJECT_MARKER = "EJ_SPRACHCHRONIKEN"
MAX_BACKUP_BYTES = 15 * 1024 * 1024
REQUIRED_COLUMNS = {
    "users": {"user_id", "xp", "gold", "chapter"},
    "records": {"id", "user_id", "response", "created_at"},
    "vocab": {"id", "user_id", "term"},
    "questions": {"id", "skill", "prompt"},
    "attempts": {"id", "user_id", "question_id"},
    "activity_log": {"id", "user_id", "kind", "created_at"},
    "quests": {"id", "user_id", "status"},
    "sync_checkpoint": {
        "slot", "project", "snapshot_id", "parent_id", "content_hash", "created_at", "origin"
    },
}


class SyncError(ValueError):
    """User-facing validation / version conflict error."""


@dataclass(frozen=True)
class Checkpoint:
    snapshot_id: str
    parent_id: str | None
    content_hash: str
    created_at: str
    origin: str


@dataclass(frozen=True)
class Overview:
    users: int
    xp: int
    records: int
    vocab: int
    attempts: int
    activities: int


@dataclass(frozen=True)
class Preview:
    checkpoint: Checkpoint
    overview: Overview
    warnings: tuple[str, ...]
    target_hash: str
    target_overview: Overview


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _file_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _normalise(value):
    return {"blob": value.hex()} if isinstance(value, bytes) else value


def content_hash(db: sqlite3.Connection) -> str:
    """Hash logical rows, excluding only snapshot bookkeeping.

    A hash of raw SQLite file bytes is unreliable because journal pages and
    vacuuming can change bytes without changing any actual learning records.
    """
    digest = hashlib.sha256()
    tables = sorted(row[0] for row in db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ) if row[0] != "sync_checkpoint")
    for table in tables:
        digest.update(json.dumps(["table", table], ensure_ascii=False).encode("utf-8"))
        columns = [row[1] for row in db.execute(f"PRAGMA table_info({_quote(table)})")]
        digest.update(json.dumps(columns, ensure_ascii=False).encode("utf-8"))
        try:
            rows = db.execute(f"SELECT * FROM {_quote(table)} ORDER BY rowid")
            for row in rows:
                digest.update(json.dumps([_normalise(value) for value in row],
                    ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
                digest.update(b"\n")
        except sqlite3.DatabaseError as exc:
            raise SyncError(f"無法計算資料表 {table} 的內容摘要。") from exc
    return digest.hexdigest()


def overview(db: sqlite3.Connection) -> Overview:
    def scalar(sql: str) -> int:
        return int(db.execute(sql).fetchone()[0] or 0)

    return Overview(
        users=scalar("SELECT COUNT(*) FROM users"),
        xp=scalar("SELECT SUM(xp) FROM users"),
        records=scalar("SELECT COUNT(*) FROM records"),
        vocab=scalar("SELECT COUNT(*) FROM vocab"),
        attempts=scalar("SELECT COUNT(*) FROM attempts"),
        activities=scalar("SELECT COUNT(*) FROM activity_log"),
    )


def _checkpoint(db: sqlite3.Connection) -> Checkpoint | None:
    row = db.execute("SELECT project,snapshot_id,parent_id,content_hash,created_at,origin "
        "FROM sync_checkpoint WHERE slot=1").fetchone()
    if row is None:
        return None
    if row[0] != PROJECT_MARKER:
        raise SyncError("備份資料庫不屬於 Sprachchroniken。")
    return Checkpoint(row[1], row[2], row[3], row[4], row[5])


def _validate(db: sqlite3.Connection) -> Checkpoint:
    # Restrict schema introspection to data created by this application.
    try:
        if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise SyncError("SQLite 完整性檢查失敗，無法匯入。")
        actual_tables = {row[0] for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        for name, expected in REQUIRED_COLUMNS.items():
            if name not in actual_tables:
                raise SyncError(f"備份缺少必要資料表：{name}。請先更新匯出端至 V1.6。")
            actual_cols = {row[1] for row in db.execute(f"PRAGMA table_info({_quote(name)})")}
            if not expected <= actual_cols:
                raise SyncError(f"資料表 {name} 欄位不相容。")
        if db.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='trigger'").fetchone()[0]:
            raise SyncError("備份包含未預期的資料庫 Trigger，已拒絕匯入。")
        stamp = _checkpoint(db)
        if stamp is None:
            raise SyncError("備份缺少同步版本資訊。請使用 V1.6 的 /de sync export 產生檔案。")
        if stamp.content_hash != content_hash(db):
            raise SyncError("備份資料與版本摘要不一致，請重新匯出。")
        return stamp
    except sqlite3.DatabaseError as exc:
        raise SyncError("不是有效的 Sprachchroniken SQLite 備份檔。") from exc


def _read_connection(path: Path) -> sqlite3.Connection:
    db = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        db.execute("PRAGMA trusted_schema=OFF")
        db.execute("PRAGMA query_only=ON")
    except Exception:
        db.close()
        raise
    return db


class SyncStore:
    def __init__(self, db: sqlite3.Connection, database_path: Path | str, origin: str):
        self.db = db
        self.database_path = Path(database_path)
        self.origin = (origin or "Unknown").strip()[:48]
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS sync_checkpoint(
                slot INTEGER PRIMARY KEY CHECK(slot=1),
                project TEXT NOT NULL,
                snapshot_id TEXT NOT NULL,
                parent_id TEXT,
                content_hash TEXT NOT NULL,
                created_at TEXT NOT NULL,
                origin TEXT NOT NULL
            )
        """)
        self.db.commit()

    def checkpoint(self) -> Checkpoint | None:
        return _checkpoint(self.db)

    def summary(self) -> Overview:
        return overview(self.db)

    def current_hash(self) -> str:
        return content_hash(self.db)

    def export(self) -> tuple[Path, Checkpoint]:
        self.db.commit()
        parent = self.checkpoint()
        stamp = Checkpoint(
            snapshot_id=uuid.uuid4().hex,
            parent_id=parent.snapshot_id if parent else None,
            content_hash=self.current_hash(),
            created_at=_utc_stamp(),
            origin=self.origin,
        )
        with self.db:
            self.db.execute("""
                INSERT INTO sync_checkpoint(slot,project,snapshot_id,parent_id,content_hash,created_at,origin)
                VALUES(1,?,?,?,?,?,?)
                ON CONFLICT(slot) DO UPDATE SET
                    project=excluded.project, snapshot_id=excluded.snapshot_id,
                    parent_id=excluded.parent_id,content_hash=excluded.content_hash,
                    created_at=excluded.created_at,origin=excluded.origin
            """, (PROJECT_MARKER, stamp.snapshot_id, stamp.parent_id,
                  stamp.content_hash, stamp.created_at, stamp.origin))
        fd, name = tempfile.mkstemp(prefix="sprachchroniken_export_", suffix=".sqlite3")
        os.close(fd)
        path = Path(name)
        try:
            with closing(sqlite3.connect(path)) as target:
                self.db.backup(target)
                target.commit()
            with closing(_read_connection(path)) as snapshot:
                _validate(snapshot)
            return path, stamp
        except Exception:
            path.unlink(missing_ok=True)
            raise

    def preview(self, path: Path | str) -> Preview:
        path = Path(path)
        if not path.is_file() or not 0 < path.stat().st_size <= MAX_BACKUP_BYTES:
            raise SyncError("備份檔必須存在，且不得超過 15 MB。")
        try:
            with closing(_read_connection(path)) as source:
                incoming = _validate(source)
                source_overview = overview(source)
        except sqlite3.DatabaseError as exc:
            raise SyncError("無法讀取 SQLite 備份。") from exc

        current = self.checkpoint()
        now_hash = self.current_hash()
        warnings: list[str] = []
        if now_hash == incoming.content_hash:
            warnings.append("兩邊的學習資料內容相同；可以不用覆蓋。")
        elif current is None:
            warnings.append("此裝置尚未同步過；匯入會完整取代目前本機資料。")
        elif now_hash != current.content_hash:
            warnings.append("⚠️ 此裝置在上次匯出／匯入後又有新紀錄，覆蓋將捨棄這些修改。")
        elif incoming.parent_id != current.snapshot_id:
            warnings.append("⚠️ 來源不是目前資料庫的直接下一版本，可能是舊備份或另一條進度分支。")
        if current and incoming.created_at < current.created_at:
            warnings.append("⚠️ 來源檔案的匯出時間早於本機上次同步（也請注意兩裝置的時鐘差異）。")
        return Preview(incoming, source_overview, tuple(warnings), now_hash, overview(self.db))

    def restore(self, path: Path | str, expected_target_hash: str) -> Path:
        """Replace live DB after preview, retaining a durable rollback file."""
        self.db.commit()
        if self.current_hash() != expected_target_hash:
            raise SyncError("預覽後本機已有資料變動。請重新執行 /de sync import，避免覆蓋新進度。")
        path = Path(path)
        self.preview(path)  # Recheck the uploaded file before any live modification.
        backup_dir = self.database_path.parent / "sync_backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup = backup_dir / f"before_import_{_file_stamp()}_{uuid.uuid4().hex[:8]}.sqlite3"
        try:
            with closing(sqlite3.connect(backup)) as target:
                self.db.backup(target)
                target.commit()
        except Exception as exc:
            backup.unlink(missing_ok=True)
            raise SyncError("無法備份目前資料庫，已取消匯入。") from exc

        try:
            with closing(_read_connection(path)) as source:
                source.backup(self.db)
            self.db.commit()
            if self.db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise SyncError("匯入後資料庫完整性檢查失敗。")
            if self.current_hash() != self.checkpoint().content_hash:
                raise SyncError("匯入後版本摘要不一致。")
        except Exception as exc:
            try:
                with closing(_read_connection(backup)) as original:
                    original.backup(self.db)
                self.db.commit()
            except Exception as rollback_exc:
                raise SyncError(f"匯入失敗且自動復原未完成！請停止 Bot 並手動恢復：{backup}") from rollback_exc
            raise SyncError(f"匯入失敗，已自動恢復原本資料。備份：{backup.name}") from exc
        return backup
