"""
Tests for LogStore (src/backend/log_store.py) and its integration with
SimulationRunner's reset() behavior.

Covers exactly the two required cases:
- NORMAL: logs persist continuously across a reset (no data loss, no
  gap/reset in the id sequence), and survive even a brand-new process
  (simulating a full backend restart).
- FAILURE: if the underlying SQLite file can't be opened at all, every
  LogStore operation degrades to a safe no-op instead of raising —
  a logging failure must never be able to crash the simulation.
"""

import sys
import os
import tempfile
import shutil

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.backend.log_store import LogStore
from src.backend.runner import SimulationRunner


@pytest.fixture
def temp_db_path():
    """A throwaway SQLite file path, cleaned up after the test."""
    tmp_dir = tempfile.mkdtemp()
    path = os.path.join(tmp_dir, "test_logs.sqlite3")
    yield path
    shutil.rmtree(tmp_dir, ignore_errors=True)


class TestLogStoreNormalCase:
    def test_insert_and_read_back(self, temp_db_path):
        store = LogStore(db_path=temp_db_path)
        assert store.is_available()

        sid = store.start_session()
        store.insert(sid, tick=1, message="hello")
        store.insert(sid, tick=2, message="world")

        rows = store.get_all()
        assert len(rows) == 2
        assert rows[0]["message"] == "hello"
        assert rows[1]["message"] == "world"

    def test_log_ids_continuous_across_session_boundary(self, temp_db_path):
        """New session (e.g. from a reset) must NOT reset or gap the
        underlying log id sequence — that's the whole point of the fix."""
        store = LogStore(db_path=temp_db_path)

        sid1 = store.start_session()
        store.insert(sid1, 1, "before reset")
        last_id_before = store.last_id()

        sid2 = store.start_session()  # simulates a reset
        assert sid2 != sid1
        store.insert(sid2, 0, "after reset")
        last_id_after = store.last_id()

        assert last_id_after == last_id_before + 1

    def test_history_survives_new_process_instance(self, temp_db_path):
        """Simulates a full backend restart: a brand-new LogStore pointed
        at the same file must see everything the old one wrote."""
        store1 = LogStore(db_path=temp_db_path)
        sid = store1.start_session()
        store1.insert(sid, 1, "written before restart")

        # Fresh instance, same underlying file — simulates process restart
        store2 = LogStore(db_path=temp_db_path)
        rows = store2.get_all()
        assert any(r["message"] == "written before restart" for r in rows)

    def test_runner_reset_does_not_clear_visible_logs(self, temp_db_path):
        """The actual behavior change: /reset must not wipe the live log
        panel anymore — it should keep prior entries and just add a
        reset marker."""
        runner = SimulationRunner()
        runner.log_store = LogStore(db_path=temp_db_path)  # isolate from real data/logs.sqlite3
        runner.session_id = runner.log_store.start_session()

        runner.add_log("message before reset")
        assert "message before reset" in runner.logs

        runner.reset()

        assert "message before reset" in runner.logs, (
            "reset() must not clear prior log entries from the visible panel"
        )
        assert any("reset" in m.lower() for m in runner.logs), (
            "reset() should add a visible marker so the boundary is still clear"
        )

    def test_runner_reset_persists_full_history_to_db(self, temp_db_path):
        runner = SimulationRunner()
        runner.log_store = LogStore(db_path=temp_db_path)
        runner.session_id = runner.log_store.start_session()

        runner.add_log("entry one")
        runner.reset()
        runner.add_log("entry two")

        history = runner.log_store.get_all()
        messages = [r["message"] for r in history]
        assert "entry one" in messages
        assert "entry two" in messages
        assert any("reset" in m.lower() for m in messages)


class TestLogStoreFailureCase:
    def test_unavailable_db_reports_unavailable(self):
        # Pointing the "db file" at a path that's actually a directory
        # reliably fails to open, regardless of user permissions (even
        # root can't open a directory as a sqlite file).
        broken_dir = tempfile.mkdtemp()
        try:
            store = LogStore(db_path=broken_dir)
            assert store.is_available() is False
        finally:
            shutil.rmtree(broken_dir, ignore_errors=True)

    def test_unavailable_db_operations_never_raise(self):
        broken_dir = tempfile.mkdtemp()
        try:
            store = LogStore(db_path=broken_dir)

            # None of these should raise, even though the DB is unusable.
            sid = store.start_session()
            store.insert(sid, 1, "should not crash")
            result = store.get_all()
            last = store.last_id()

            assert result == []
            assert last == 0
        finally:
            shutil.rmtree(broken_dir, ignore_errors=True)

    def test_runner_survives_broken_log_store(self):
        """End-to-end: even if persistence is completely broken, the
        simulation and its in-memory log panel must keep working."""
        broken_dir = tempfile.mkdtemp()
        try:
            runner = SimulationRunner()
            runner.log_store = LogStore(db_path=broken_dir)
            runner.session_id = runner.log_store.start_session()

            # Should not raise despite the broken store
            runner.add_log("test message")
            runner.sim.step()
            runner.reset()

            assert "test message" in runner.logs
        finally:
            shutil.rmtree(broken_dir, ignore_errors=True)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])