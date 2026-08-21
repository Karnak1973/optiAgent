import os
from synapse.graph.cpg import CodePropertyGraph
from synapse.graph.model import EdgeKind, NodeKind, ZoomLevel, ZoomedContext


class ZoomController:
    def __init__(self, cpg: CodePropertyGraph):
        self.cpg = cpg
        self.store = cpg.store

    def get_context(
        self,
        target: str = "",
        zoom_level: ZoomLevel = ZoomLevel.SKELETON,
        token_budget: int = 2048,
        **kwargs,
    ) -> ZoomedContext:
        """Get context at specified zoom level"""
        if zoom_level == ZoomLevel.ARCHITECTURE or zoom_level == 0:
            return self.get_architecture_map(token_budget)
        elif zoom_level == ZoomLevel.SKELETON or zoom_level == 1:
            return self.get_module_skeleton(target, token_budget)
        elif zoom_level == ZoomLevel.INTERFACE or zoom_level == 2:
            return self.get_interface_contracts(target, token_budget)
        elif zoom_level == ZoomLevel.IMPLEMENTATION or zoom_level == 3:
            return self.get_implementation(target, token_budget)
        elif zoom_level == ZoomLevel.SLICE or zoom_level == 4:
            return self.get_program_slice(target, token_budget, **kwargs)
        return ZoomedContext(zoom_level=zoom_level, content="", token_count=0, nodes_included=[])

    def get_program_slice(
        self,
        target: str,
        token_budget: int = 800,
        target_variable: str | None = None,
        slice_type: str = "backward",
    ) -> ZoomedContext:
        """L4: Program slice — only lines causally affecting the target point.

        target format: "file_path:line" or "file_path:line:variable"
        """
        from synapse.retriever.program_slicer import ProgramSlicer

        slicer = ProgramSlicer(self.cpg)

        # Parse target format: "file.py:42" or "file.py:42:var_name"
        parts = target.split(":")
        if len(parts) < 2:
            return ZoomedContext(
                zoom_level=ZoomLevel.SLICE,
                content=f"# Invalid slice target format: {target}\n# Expected: file_path:line_number[:variable]",
                token_count=10,
                nodes_included=[],
            )

        file_path = parts[0]
        try:
            line = int(parts[1])
        except ValueError:
            return ZoomedContext(
                zoom_level=ZoomLevel.SLICE,
                content=f"# Invalid line number: {parts[1]}",
                token_count=10,
                nodes_included=[],
            )

        variable = parts[2] if len(parts) > 2 else target_variable

        if slice_type == "forward":
            result = slicer.forward_slice(file_path, line, variable)
        else:
            result = slicer.backward_slice(file_path, line, variable)

        if not result.slice_lines:
            return ZoomedContext(
                zoom_level=ZoomLevel.SLICE,
                content=f"# No slice found for {file_path}:{line}",
                token_count=5,
                nodes_included=[],
            )

        lines = [f"── Program Slice ({result.slice_type}) ──"]
        lines.append(f"Target: {file_path}:{line}" + (f" (variable: {variable})" if variable else ""))
        lines.append(f"Lines in slice: {len(result.slice_lines)}")
        lines.append("")

        for fpath, lnum, text in result.slice_lines:
            lines.append(text)

        content = "\n".join(lines)
        token_count = max(1, len(content) // 4)

        # Truncate if over budget
        if token_count > token_budget:
            truncated_lines = lines[:3]
            running_tokens = 0
            for fpath, lnum, text in result.slice_lines:
                line_tokens = max(1, len(text) // 4)
                if running_tokens + line_tokens > token_budget - 20:
                    truncated_lines.append(f"... ({len(result.slice_lines) - len(truncated_lines) + 3} more lines truncated)")
                    break
                truncated_lines.append(text)
                running_tokens += line_tokens
            content = "\n".join(truncated_lines)
            token_count = running_tokens + 10

        return ZoomedContext(
            zoom_level=ZoomLevel.SLICE,
            content=content,
            token_count=token_count,
            nodes_included=[],
            metadata={"slice_type": result.slice_type, "lines_in_slice": len(result.slice_lines)},
        )

    def get_architecture_map(self, token_budget: int = 300) -> ZoomedContext:
        """L0: Module dependency map"""
        files = self.store.get_nodes_by_kind(NodeKind.FILE)
        dirs: dict[str, list] = {}
        nodes_included = [f.id for f in files]

        for f in files:
            path_str = f.file_path or f.name
            dir_name = os.path.dirname(path_str).replace("\\", "/")
            if not dir_name:
                dir_name = "."
            dirs.setdefault(dir_name, []).append(f)

        lines = []
        for d, fs in sorted(dirs.items()):
            dep_files = []
            for f in fs:
                for edge in self.store.get_edges(source_id=f.id):
                    if edge.kind == EdgeKind.IMPORTS:
                        dep_node = self.store.get_node(edge.target_id)
                        if dep_node:
                            dep_files.append(dep_node.name)
            dep_str = f" (depends on: {', '.join(set(dep_files))})" if dep_files else ""
            lines.append(f"── {d}/{dep_str}")

            for f in fs:
                symbol_names = []
                for edge in self.store.get_edges(source_id=f.id):
                    if edge.kind in [EdgeKind.CONTAINS, EdgeKind.DECLARES]:
                        n = self.store.get_node(edge.target_id)
                        if n and n.kind in [NodeKind.CLASS, NodeKind.FUNCTION, NodeKind.METHOD]:
                            symbol_names.append(n.name)
                if symbol_names:
                    lines.append(f"│  {', '.join(sorted(set(symbol_names)))}")

        content = "\n".join(lines)
        token_count = max(1, len(content) // 4)
        return ZoomedContext(
            zoom_level=ZoomLevel.ARCHITECTURE,
            content=content,
            token_count=token_count,
            nodes_included=nodes_included,
        )

    def get_module_skeleton(self, file_path: str, token_budget: int = 800) -> ZoomedContext:
        """L1: File outline with class/function signatures"""
        files = self.store.get_nodes_by_kind(NodeKind.FILE)
        f_node = None
        for f in files:
            p = f.file_path or f.name
            if file_path in p or file_path == f.name:
                f_node = f
                break

        if not f_node:
            return ZoomedContext(
                zoom_level=ZoomLevel.SKELETON,
                content=f"# File not found: {file_path}",
                token_count=5,
                nodes_included=[],
            )

        lines = [f"── {f_node.name} ──"]
        nodes_included = [f_node.id]
        edges = self.store.get_edges(source_id=f_node.id)

        for e in edges:
            if e.kind in [EdgeKind.CONTAINS, EdgeKind.DECLARES]:
                n = self.store.get_node(e.target_id)
                if n:
                    nodes_included.append(n.id)
                    if n.skeleton:
                        lines.append(n.skeleton)
                    elif n.signature:
                        lines.append(n.signature)

        content = "\n".join(lines)
        token_count = max(1, len(content) // 4)
        return ZoomedContext(
            zoom_level=ZoomLevel.SKELETON,
            content=content,
            token_count=token_count,
            nodes_included=nodes_included,
        )

    def get_interface_contracts(self, symbol_name: str, token_budget: int = 1500) -> ZoomedContext:
        """L2: Full signatures + docstrings + 1-hop callee signatures"""
        nodes_included = []
        for kind in [NodeKind.FUNCTION, NodeKind.CLASS, NodeKind.METHOD]:
            for n in self.store.get_nodes_by_kind(kind):
                if n.name == symbol_name:
                    nodes_included.append(n.id)
                    content = n.skeleton or n.signature or n.name
                    if n.docstring and n.signature and n.docstring not in content:
                        content = f'{n.signature}\n    """{n.docstring}"""\n    ...'

                    # Find callees
                    edges = self.store.get_edges(source_id=n.id)
                    callees = []
                    for e in edges:
                        if e.kind == EdgeKind.CALLS:
                            callee = self.store.get_node(e.target_id)
                            if callee:
                                nodes_included.append(callee.id)
                                callees.append(callee.skeleton or callee.signature or callee.name)

                    if callees:
                        content += "\n\n# Callee interfaces:\n" + "\n".join(set(callees))

                    token_count = max(1, len(content) // 4)
                    return ZoomedContext(
                        zoom_level=ZoomLevel.INTERFACE,
                        content=content,
                        token_count=token_count,
                        nodes_included=nodes_included,
                    )

        return ZoomedContext(
            zoom_level=ZoomLevel.INTERFACE,
            content=f"# Symbol not found: {symbol_name}",
            token_count=5,
            nodes_included=[],
        )

    def get_implementation(self, symbol_name: str, token_budget: int = 4000) -> ZoomedContext:
        """L3: Full body of target + skeleton of neighbors"""
        for kind in [NodeKind.FUNCTION, NodeKind.CLASS, NodeKind.METHOD]:
            for n in self.store.get_nodes_by_kind(kind):
                if n.name == symbol_name:
                    content = n.full_body or n.skeleton or n.name
                    token_count = max(1, len(content) // 4)
                    return ZoomedContext(
                        zoom_level=ZoomLevel.IMPLEMENTATION,
                        content=content,
                        token_count=token_count,
                        nodes_included=[n.id],
                    )

        return ZoomedContext(
            zoom_level=ZoomLevel.IMPLEMENTATION,
            content=f"# Symbol not found: {symbol_name}",
            token_count=5,
            nodes_included=[],
        )

