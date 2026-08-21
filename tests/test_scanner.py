import pytest
from pathlib import Path
from synapse.indexer.scanner import FileScanner, FileEntry

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "sample_project"


class TestFileScanner:
    def test_scan_finds_python_files(self):
        scanner = FileScanner(FIXTURES_DIR)
        entries = scanner.scan()
        py_files = [e for e in entries if e.language == "python"]
        assert len(py_files) >= 5  # service, jwt_handler, models, connection, queries
    
    def test_scan_detects_language(self):
        scanner = FileScanner(FIXTURES_DIR)
        entries = scanner.scan()
        for entry in entries:
            if entry.path.suffix == ".py":
                assert entry.language == "python"
    
    def test_scan_computes_hash(self):
        scanner = FileScanner(FIXTURES_DIR)
        entries = scanner.scan()
        for entry in entries:
            assert len(entry.content_hash) == 64  # SHA-256 hex digest
    
    def test_ignores_pycache(self, tmp_path):
        # Create a structure with __pycache__
        (tmp_path / "main.py").write_text("x = 1")
        pycache = tmp_path / "__pycache__"
        pycache.mkdir()
        (pycache / "main.cpython-311.pyc").write_bytes(b"\x00")
        
        scanner = FileScanner(tmp_path)
        entries = scanner.scan()
        paths = [str(e.path) for e in entries]
        assert not any("__pycache__" in p for p in paths)
