"""Unit tests for safe file replacement."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import main


class CopyTests(unittest.TestCase):
    """Exercise file replacement behavior without touching network shares."""

    def test_dry_run_lists_each_source_and_exact_target_path(self):
        """Preview each source and destination without copying files."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_dir = root / "source"
            target_dir = root / "target"
            source_dir.mkdir()
            source = source_dir / "map.dat"
            source.write_bytes(b"test data")
            with patch.object(main, "SIZE_BASELINES", {}):
                result = main.copy_job(
                    main.CopyJob("map", (source,), target_dir, "none"), dry_run=True
                )
            self.assertEqual(result.status, "DRY-RUN")
            self.assertIn(str(source), result.detail)
            self.assertIn(str(target_dir / "map.dat"), result.detail)
            self.assertFalse((target_dir / "map.dat").exists())

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
