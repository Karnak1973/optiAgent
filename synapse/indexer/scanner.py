from dataclasses import dataclass
from pathlib import Path
import hashlib
import json
import fnmatch
import os

@dataclass
class FileEntry:
    path: Path
    relative_path: str
    language: str | None
    size: int
    content_hash: str
    is_changed: bool = False

LANGUAGE_MAP = {
    '.py': 'python',
    '.js': 'javascript', 
    '.jsx': 'javascript',
    '.ts': 'typescript',
    '.tsx': 'typescript',
    '.go': 'go',
    '.rs': 'rust',
    '.java': 'java',
    '.rb': 'ruby',
    '.md': 'markdown',
    '.json': 'json',
    '.yaml': 'yaml',
    '.yml': 'yaml',
    '.toml': 'toml',
}

DEFAULT_IGNORES = [
    '.git', '__pycache__', 'node_modules', '.venv', 'venv',
    '.env', 'dist', 'build', '.tox', '.mypy_cache', '.pytest_cache',
    '.synapse', '*.pyc', '*.pyo', '*.so', '*.dylib', '*.egg-info',
]

class FileScanner:
    def __init__(self, root: Path, ignore_patterns: list[str] | None = None):
        self.root = root
        self.ignore_patterns = DEFAULT_IGNORES.copy()
        if ignore_patterns:
            self.ignore_patterns.extend(ignore_patterns)
        self._load_gitignore()
        self.cache_dir = self.root / '.synapse'
        self.cache_file = self.cache_dir / 'scan_cache.json'
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _load_gitignore(self):
        gitignore_path = self.root / '.gitignore'
        if gitignore_path.exists():
            with open(gitignore_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#'):
                        self.ignore_patterns.append(line)

    def scan(self) -> list[FileEntry]:
        entries = []
        for root_dir, dirs, files in os.walk(self.root):
            dirs[:] = [d for d in dirs if not self._is_ignored(Path(root_dir) / d)]
            
            for file in files:
                file_path = Path(root_dir) / file
                if self._is_ignored(file_path):
                    continue
                try:
                    rel_path = file_path.relative_to(self.root).as_posix()
                    lang = self._detect_language(file_path)
                    size = file_path.stat().st_size
                    content_hash = self._compute_hash(file_path)
                    entries.append(FileEntry(
                        path=file_path,
                        relative_path=rel_path,
                        language=lang,
                        size=size,
                        content_hash=content_hash,
                        is_changed=True
                    ))
                except Exception:
                    pass
        self._save_cache(entries)
        return entries

    def incremental_scan(self) -> tuple[list[FileEntry], list[FileEntry], list[str]]:
        old_cache = self._load_cache()
        current_entries = self.scan()
        
        new_files = []
        changed_files = []
        current_paths = set()
        
        for entry in current_entries:
            current_paths.add(entry.relative_path)
            if entry.relative_path not in old_cache:
                new_files.append(entry)
            elif old_cache[entry.relative_path] != entry.content_hash:
                entry.is_changed = True
                changed_files.append(entry)
            else:
                entry.is_changed = False
                
        deleted_files = [path for path in old_cache if path not in current_paths]
        return new_files, changed_files, deleted_files

    def _compute_hash(self, path: Path) -> str:
        sha256_hash = hashlib.sha256()
        with open(path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()

    def _detect_language(self, path: Path) -> str | None:
        return LANGUAGE_MAP.get(path.suffix.lower())

    def _is_ignored(self, path: Path) -> bool:
        try:
            rel_path = path.relative_to(self.root).as_posix()
        except ValueError:
            return False
            
        for pattern in self.ignore_patterns:
            if fnmatch.fnmatch(rel_path, pattern) or fnmatch.fnmatch(path.name, pattern) or rel_path.startswith(pattern + '/'):
                return True
        return False

    def _load_cache(self) -> dict[str, str]:
        if self.cache_file.exists():
            try:
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def _save_cache(self, entries: list[FileEntry]):
        cache = {entry.relative_path: entry.content_hash for entry in entries}
        with open(self.cache_file, 'w', encoding='utf-8') as f:
            json.dump(cache, f, indent=2)
