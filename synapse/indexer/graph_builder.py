from pathlib import Path
from typing import Any
import rich.progress as progress

from synapse.graph.cpg import CodePropertyGraph
from synapse.graph.model import (
    CodeChunk,
    EdgeKind,
    GraphEdge,
    GraphNode,
    NodeKind,
    SymbolKind,
)
from synapse.graph.store import GraphStore
from .parser import ASTParser
from .scanner import FileScanner
from .scope_resolver import ScopeResolver


class GraphBuilder:
    def __init__(self, root: Path, db_path: Path | None = None):
        self.root = root.resolve()
        if db_path is None:
            synapse_dir = self.root / ".synapse"
            synapse_dir.mkdir(parents=True, exist_ok=True)
            self.db_path = synapse_dir / "graph.db"
        else:
            self.db_path = db_path

        self.scanner = FileScanner(self.root)
        self.parser = ASTParser()
        self.resolver = ScopeResolver()

    def build(self) -> CodePropertyGraph:
        """Full build pipeline:
        1. Scan files
        2. Create and clear store
        3. Parse each file into chunks & add nodes
        4. Resolve imports -> IMPORTS edges
        5. Resolve references -> CALLS/REFERENCES edges
        6. Return populated CPG
        """
        store = GraphStore(self.db_path)
        store.clear()
        cpg = CodePropertyGraph(store)

        files = self.scanner.scan()
        file_node_map: dict[str, int] = {}  # rel_path -> node_id
        chunk_node_map: dict[str, list[int]] = {}  # symbol_name -> [node_ids]
        all_chunks: list[CodeChunk] = []
        file_contents: dict[str, str] = {}

        # 1. Create File nodes & parse chunks
        with progress.Progress() as p:
            task = p.add_task("[cyan]Scanning and parsing codebase...", total=len(files))
            for f in files:
                rel_path = f.relative_path
                file_node = GraphNode(
                    id=0,
                    kind=NodeKind.FILE,
                    name=rel_path,
                    file_path=str(f.path),
                    language=f.language,
                    metadata={"size": f.size, "content_hash": f.content_hash},
                )
                file_id = store.add_node(file_node)
                file_node_map[rel_path] = file_id

                if f.language:
                    try:
                        content = f.path.read_text(encoding="utf-8", errors="replace")
                        file_contents[rel_path] = content
                        chunks = self.parser.parse_file(rel_path, content, f.language)
                        all_chunks.extend(chunks)

                        for chunk in chunks:
                            node_kind = NodeKind.CHUNK
                            if chunk.kind == SymbolKind.FUNCTION:
                                node_kind = NodeKind.FUNCTION
                            elif chunk.kind == SymbolKind.METHOD:
                                node_kind = NodeKind.METHOD
                            elif chunk.kind == SymbolKind.CLASS:
                                node_kind = NodeKind.CLASS

                            node = GraphNode(
                                id=0,
                                kind=node_kind,
                                name=chunk.name,
                                file_path=rel_path,
                                start_line=chunk.start_line,
                                end_line=chunk.end_line,
                                signature=chunk.signature,
                                skeleton=chunk.skeleton,
                                full_body=chunk.full_body,
                                docstring=chunk.docstring,
                                language=chunk.language,
                                enclosing_scope=chunk.enclosing_scope,
                                symbol_kind=chunk.kind,
                                metadata={
                                    "token_count_skeleton": chunk.token_count_skeleton,
                                    "token_count_full": chunk.token_count_full,
                                },
                            )
                            node_id = store.add_node(node)
                            chunk_node_map.setdefault(chunk.name, []).append(node_id)

                            # Link File -> Symbol (DECLARES)
                            store.add_edge(GraphEdge(source_id=file_id, target_id=node_id, kind=EdgeKind.DECLARES))

                    except Exception:
                        pass
                p.advance(task)

        # 2. Build class containment edges (Class -> Method)
        for chunk in all_chunks:
            if chunk.kind == SymbolKind.METHOD and chunk.enclosing_scope:
                class_ids = chunk_node_map.get(chunk.enclosing_scope, [])
                method_ids = chunk_node_map.get(chunk.name, [])
                for cid in class_ids:
                    for mid in method_ids:
                        store.add_edge(GraphEdge(source_id=cid, target_id=mid, kind=EdgeKind.CONTAINS))

        # 3. Resolve imports -> IMPORTS edges between file nodes
        for rel_path, content in file_contents.items():
            file_id = file_node_map.get(rel_path)
            if not file_id:
                continue
            lang = "python" if rel_path.endswith(".py") else "javascript"
            imports = self.resolver.resolve_imports(rel_path, content, lang)
            for imp in imports:
                # Find matching target file
                for other_rel, other_id in file_node_map.items():
                    if other_id == file_id:
                        continue
                    # Match module name or relative path
                    mod_norm = imp.imported_module.replace(".", "/").replace("\\", "/")
                    if mod_norm and (other_rel.startswith(mod_norm) or other_rel.endswith(f"{mod_norm}.py") or mod_norm in other_rel):
                        store.add_edge(GraphEdge(source_id=file_id, target_id=other_id, kind=EdgeKind.IMPORTS))

        # 4. Resolve references -> CALLS / REFERENCES edges
        references = self.resolver.resolve_references(all_chunks, all_chunks)
        for caller_name, callee_name in references:
            caller_ids = chunk_node_map.get(caller_name, [])
            callee_ids = chunk_node_map.get(callee_name, [])
            for s_id in caller_ids:
                for t_id in callee_ids:
                    if s_id != t_id:
                        store.add_edge(GraphEdge(source_id=s_id, target_id=t_id, kind=EdgeKind.CALLS))

        return cpg

    def incremental_build(self, cpg: CodePropertyGraph) -> CodePropertyGraph:
        """Re-index only changed files. Removes old nodes for changed files and re-parses them."""
        store = cpg.store
        scanner = FileScanner(self.root)

        new_files, changed_files, deleted_files = scanner.incremental_scan()

        # 1. Remove nodes for deleted and changed files
        for f in (deleted_files + changed_files):
            rel_path = f.relative_path if hasattr(f, 'relative_path') else f
            existing_nodes = store.get_nodes_by_file(rel_path)
            for node in existing_nodes:
                # Remove all edges involving this node
                cursor = store.conn.cursor()
                cursor.execute("DELETE FROM edges WHERE source_id = ? OR target_id = ?", (node.id, node.id))
                cursor.execute("DELETE FROM nodes WHERE id = ?", (node.id,))
                # Remove from rustworkx if present
                if node.id in store._node_id_to_rx_idx:
                    rx_idx = store._node_id_to_rx_idx.pop(node.id)
                    del store._rx_idx_to_node_id[rx_idx]
                    try:
                        store.graph.remove_node(rx_idx)
                    except Exception:
                        pass

        # 2. Re-parse changed and new files
        all_new_chunks: list[CodeChunk] = []
        file_contents: dict[str, str] = {}

        for f in (new_files + changed_files):
            rel_path = f.relative_path if hasattr(f, 'relative_path') else str(f)
            file_path = f.path if hasattr(f, 'path') else self.root / rel_path

            # Create/update file node
            file_node = GraphNode(
                id=0,
                kind=NodeKind.FILE,
                name=rel_path,
                file_path=str(file_path),
                language=f.language if hasattr(f, 'language') else None,
                metadata={"size": f.size if hasattr(f, 'size') else 0, "content_hash": f.content_hash if hasattr(f, 'content_hash') else ""},
            )
            file_id = store.add_node(file_node)

            if file_node.language:
                try:
                    content = Path(file_path).read_text(encoding="utf-8", errors="replace")
                    file_contents[rel_path] = content
                    chunks = self.parser.parse_file(rel_path, content, file_node.language)
                    all_new_chunks.extend(chunks)

                    chunk_node_map: dict[str, list[int]] = {}
                    for chunk in chunks:
                        node_kind = NodeKind.CHUNK
                        if chunk.kind == SymbolKind.FUNCTION:
                            node_kind = NodeKind.FUNCTION
                        elif chunk.kind == SymbolKind.METHOD:
                            node_kind = NodeKind.METHOD
                        elif chunk.kind == SymbolKind.CLASS:
                            node_kind = NodeKind.CLASS

                        node = GraphNode(
                            id=0,
                            kind=node_kind,
                            name=chunk.name,
                            file_path=rel_path,
                            start_line=chunk.start_line,
                            end_line=chunk.end_line,
                            signature=chunk.signature,
                            skeleton=chunk.skeleton,
                            full_body=chunk.full_body,
                            docstring=chunk.docstring,
                            language=chunk.language,
                            enclosing_scope=chunk.enclosing_scope,
                            symbol_kind=chunk.kind,
                            metadata={
                                "token_count_skeleton": chunk.token_count_skeleton,
                                "token_count_full": chunk.token_count_full,
                            },
                        )
                        node_id = store.add_node(node)
                        chunk_node_map.setdefault(chunk.name, []).append(node_id)
                        store.add_edge(GraphEdge(source_id=file_id, target_id=node_id, kind=EdgeKind.DECLARES))

                    # Build containment edges for this file
                    for chunk in chunks:
                        if chunk.kind == SymbolKind.METHOD and chunk.enclosing_scope:
                            class_ids = chunk_node_map.get(chunk.enclosing_scope, [])
                            method_ids = chunk_node_map.get(chunk.name, [])
                            for cid in class_ids:
                                for mid in method_ids:
                                    store.add_edge(GraphEdge(source_id=cid, target_id=mid, kind=EdgeKind.CONTAINS))

                except Exception:
                    pass

        # 3. Resolve imports and references for affected files
        for rel_path, content in file_contents.items():
            file_nodes = store.get_nodes_by_file(rel_path)
            file_id = file_nodes[0].id if file_nodes else None
            if not file_id:
                continue
            lang = "python" if rel_path.endswith(".py") else "javascript"
            imports = self.resolver.resolve_imports(rel_path, content, lang)
            all_file_nodes = store.get_nodes_by_kind(NodeKind.FILE)
            for imp in imports:
                for other_node in all_file_nodes:
                    if other_node.id == file_id:
                        continue
                    mod_norm = imp.imported_module.replace(".", "/").replace("\\", "/")
                    if mod_norm and (other_node.name.startswith(mod_norm) or other_node.name.endswith(f"{mod_norm}.py") or mod_norm in other_node.name):
                        store.add_edge(GraphEdge(source_id=file_id, target_id=other_node.id, kind=EdgeKind.IMPORTS))

        return cpg

