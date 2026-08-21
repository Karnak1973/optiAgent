import ast
import re
from dataclasses import dataclass
from synapse.graph.model import CodeChunk, SymbolKind


@dataclass
class ImportInfo:
    source_file: str
    imported_module: str
    imported_names: list[str]
    is_relative: bool
    alias: str | None = None


class ScopeResolver:
    def resolve_imports(self, file_path: str, content: str, language: str) -> list[ImportInfo]:
        """Extract import statements from source code."""
        imports: list[ImportInfo] = []
        if not content.strip():
            return imports

        if language == "python":
            try:
                tree = ast.parse(content)
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            imports.append(
                                ImportInfo(
                                    source_file=file_path,
                                    imported_module=alias.name,
                                    imported_names=[alias.name],
                                    is_relative=False,
                                    alias=alias.asname,
                                )
                            )
                    elif isinstance(node, ast.ImportFrom):
                        mod = node.module or ""
                        names = [alias.name for alias in node.names]
                        imports.append(
                            ImportInfo(
                                source_file=file_path,
                                imported_module=mod,
                                imported_names=names,
                                is_relative=(node.level > 0),
                                alias=None,
                            )
                        )
            except SyntaxError:
                # Fallback to regex if syntax error (e.g. partial edits)
                for match in re.finditer(r"^(?:from\s+([.\w]+)\s+import\s+([*\w,\s()]+)|import\s+([\w,\s.]+))", content, re.MULTILINE):
                    if match.group(1):
                        mod = match.group(1)
                        names = [n.strip() for n in match.group(2).replace("(", "").replace(")", "").split(",") if n.strip()]
                        imports.append(
                            ImportInfo(
                                source_file=file_path,
                                imported_module=mod,
                                imported_names=names,
                                is_relative=mod.startswith("."),
                            )
                        )
                    elif match.group(3):
                        for mod in match.group(3).split(","):
                            mod_name = mod.strip().split(" as ")[0].strip()
                            if mod_name:
                                imports.append(
                                    ImportInfo(
                                        source_file=file_path,
                                        imported_module=mod_name,
                                        imported_names=[mod_name],
                                        is_relative=False,
                                    )
                                )

        elif language in ["javascript", "typescript"]:
            # ES6 imports
            for match in re.finditer(r"import\s+(?:(?:\{([^}]+)\})|(\w+)|\*\s+as\s+(\w+))\s+from\s+['\"]([^'\"]+)['\"]", content):
                names = []
                if match.group(1):
                    names = [n.strip().split(" as ")[0].strip() for n in match.group(1).split(",") if n.strip()]
                elif match.group(2):
                    names = [match.group(2).strip()]
                elif match.group(3):
                    names = [match.group(3).strip()]
                mod = match.group(4)
                imports.append(
                    ImportInfo(
                        source_file=file_path,
                        imported_module=mod,
                        imported_names=names,
                        is_relative=mod.startswith("."),
                    )
                )

        return imports

    def resolve_references(self, chunks: list[CodeChunk], all_chunks: list[CodeChunk]) -> list[tuple[str, str]]:
        """Identify potential cross-chunk calls/references.
        Returns list of (source_chunk_name, target_chunk_name).
        """
        symbol_names = {c.name: c for c in all_chunks if c.name and c.name != "unknown"}
        references: list[tuple[str, str]] = []

        for chunk in chunks:
            if not chunk.full_body:
                continue
            for target_name, target_chunk in symbol_names.items():
                if chunk.name == target_name and chunk.file_path == target_chunk.file_path:
                    continue
                # Word boundary match for function/class calls
                pattern = r"\b" + re.escape(target_name) + r"\b"
                if re.search(pattern, chunk.full_body):
                    references.append((chunk.name, target_name))

        return references

