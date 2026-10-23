"""Unit tests for safe file replacement."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import main


class CopyTests(unittest.TestCase):
    """Exercise file replacement behavior without touching network shares."""

    def test_dry_run_keeps_status_short_and_logs_each_path(self):
        """Keep the returned summary short while preserving per-file INFO logs."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_dir = root / "source"
            target_dir = root / "target"
            source_dir.mkdir()
            source = source_dir / "map.dat"
            source.write_bytes(b"test data")
            with (
                patch.object(main, "SIZE_BASELINES", {}),
                self.assertLogs("aari_generalized_map", level="INFO") as captured,
            ):
                result = main.copy_job(
                    main.CopyJob("map", (source,), target_dir, "none"), dry_run=True
                )
            self.assertEqual(result.status, "DRY-RUN")
            self.assertEqual(result.detail, f"1 файл(ов) → {target_dir}")
            self.assertFalse((target_dir / "map.dat").exists())
            log_output = "\n".join(captured.output)
            self.assertIn("INFO:aari_generalized_map:DRY_RUN_COPY", log_output)
            self.assertIn(str(source), log_output)
            self.assertIn(str(target_dir / "map.dat"), log_output)

    def test_existing_file_is_replaced_without_backup(self):
        """A changed target is replaced, and no backup copy is created."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_dir = root / "source"
            target_dir = root / "target"
            source_dir.mkdir()
            target_dir.mkdir()
            source = source_dir / "map.dat"
            target = target_dir / "map.dat"
            source.write_bytes(b"new data")
            target.write_bytes(b"old data")
            with patch.object(main, "SIZE_BASELINES", {}):
                result = main.copy_job(
                    main.CopyJob("map", (source,), target_dir, "none"), dry_run=False
                )
            self.assertEqual(result.status, "OK")
            self.assertEqual(target.read_bytes(), b"new data")
            self.assertEqual(list(root.glob("**/*backup*")), [])


if __name__ == "__main__":
    unittest.main()
