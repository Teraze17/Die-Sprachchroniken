import sqlite3
import tempfile
import unittest
from pathlib import Path

from engine import Engine
from sync_store import SyncError, SyncStore


class SyncStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.local = Engine(root / "windows" / "progress.sqlite3")
        self.cloud = Engine(root / "railway" / "progress.sqlite3")
        self.local_sync = SyncStore(self.local.db, self.local.path, "Windows")
        self.cloud_sync = SyncStore(self.cloud.db, self.cloud.path, "Railway")

    def tearDown(self):
        self.local.db.close()
        self.cloud.db.close()
        self.temp.cleanup()

    def test_round_trip_without_losing_progress(self):
        self.local.add_record("alice", "diary", "Ich lerne Deutsch.")
        out1, snap1 = self.local_sync.export()
        self.addCleanup(out1.unlink, missing_ok=True)
        preview1 = self.cloud_sync.preview(out1)
        self.assertEqual(preview1.overview.records, 1)
        backup1 = self.cloud_sync.restore(out1, preview1.target_hash)
        self.assertTrue(backup1.exists())
        self.assertEqual(self.cloud_sync.checkpoint().snapshot_id, snap1.snapshot_id)

        self.cloud.add_record("alice", "diary", "Heute bin ich unterwegs.")
        out2, snap2 = self.cloud_sync.export()
        self.addCleanup(out2.unlink, missing_ok=True)
        self.assertEqual(snap2.parent_id, snap1.snapshot_id)
        preview2 = self.local_sync.preview(out2)
        self.assertFalse(preview2.warnings)
        self.local_sync.restore(out2, preview2.target_hash)
        rows = self.local.db.execute("SELECT response FROM records ORDER BY created_at,rowid").fetchall()
        self.assertEqual([row[0] for row in rows], ["Ich lerne Deutsch.", "Heute bin ich unterwegs."])
        self.assertEqual(self.local_sync.checkpoint().snapshot_id, snap2.snapshot_id)

    def test_unsynced_local_changes_raise_warning(self):
        first, _ = self.local_sync.export()
        self.addCleanup(first.unlink, missing_ok=True)
        initial = self.cloud_sync.preview(first)
        self.cloud_sync.restore(first, initial.target_hash)
        self.local.add_record("alice", "diary", "Lokale Änderung.")
        self.cloud.add_record("alice", "diary", "Cloud Änderung.")
        second, _ = self.cloud_sync.export()
        self.addCleanup(second.unlink, missing_ok=True)
        preview = self.local_sync.preview(second)
        self.assertTrue(any("新紀錄" in w for w in preview.warnings))

    def test_preview_must_be_redone_if_destination_changes(self):
        self.local.add_record("alice", "diary", "Vom Laptop.")
        snapshot, _ = self.local_sync.export()
        self.addCleanup(snapshot.unlink, missing_ok=True)
        preview = self.cloud_sync.preview(snapshot)
        self.cloud.add_record("alice", "diary", "Nach der Vorschau.")
        with self.assertRaisesRegex(SyncError, "重新執行"):
            self.cloud_sync.restore(snapshot, preview.target_hash)
        self.assertEqual(self.cloud.db.execute("SELECT COUNT(*) FROM records").fetchone()[0], 1)

    def test_reject_tampered_sqlite(self):
        self.local.add_record("alice", "diary", "Original.")
        snapshot, _ = self.local_sync.export()
        self.addCleanup(snapshot.unlink, missing_ok=True)
        with sqlite3.connect(snapshot) as db:
            db.execute("UPDATE records SET response='Tampered!'")
        with self.assertRaisesRegex(SyncError, "摘要不一致"):
            self.cloud_sync.preview(snapshot)

    def test_reject_unrelated_database(self):
        alien = Path(self.temp.name) / "alien.sqlite3"
        with sqlite3.connect(alien) as db:
            db.execute("CREATE TABLE unrelated(x TEXT)")
        with self.assertRaisesRegex(SyncError, "必要資料表"):
            self.local_sync.preview(alien)

    def test_restore_keeps_destination_rollback_backup(self):
        self.local.add_record("alice", "diary", "Neue Quelle.")
        self.cloud.add_record("alice", "diary", "Alte Daten behalten.")
        snapshot, _ = self.local_sync.export()
        self.addCleanup(snapshot.unlink, missing_ok=True)
        preview = self.cloud_sync.preview(snapshot)
        backup = self.cloud_sync.restore(snapshot, preview.target_hash)
        with sqlite3.connect(backup) as previous:
            old = previous.execute("SELECT response FROM records").fetchone()[0]
        self.assertEqual(old, "Alte Daten behalten.")
        self.assertEqual(self.cloud.db.execute("SELECT response FROM records").fetchone()[0], "Neue Quelle.")


if __name__ == "__main__":
    unittest.main()
