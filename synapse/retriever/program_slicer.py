"""Program Slicer for ultra-surgical context extraction.

Implements backward and forward slicing on the Program Dependence Graph (PDG)
to extract only the lines that causally affect a specific variable or statement.
"""

from dataclasses import dataclass, field
from typing import Any

from synapse.graph.cpg import CodePropertyGraph
from synapse.graph.model import EdgeKind, GraphNode, NodeKind


@dataclass
class ProgramSlice:
    """Result of a program slice operation."""
    target_file: str
    target_line: int
    target_variable: str | None
    slice_lines: list[tuple[str, int, str]]  # (file_path, line_number, line_text)
    token_count: int
    slice_type: str  # 'backward', 'forward', 'impact'
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ImpactAnalysis:
    """Result of an impact analysis on changed lines."""
    changed_files: list[str]
    changed_symbols: list[GraphNode]
    impacted_functions: list[GraphNode]
    impacted_files: list[str]
    impact_chain: list[tuple[GraphNode, str, GraphNode]]  # (source, edge_type, target)
    summary: str
    token_count: int


class ProgramSlicer:
    """Computes program slices on the Code Property Graph.

    Uses backward slicing to find all statements that contribute to a variable's
    value at a specific point, and forward slicing to find all statements affected
    by a change.
    """

    def __init__(self, cpg: CodePropertyGraph):
        self.cpg = cpg
        self.store = cpg.store

    def backward_slice(
        self,
        target_file: str,
        target_line: int,
        target_variable: str | None = None,
    ) -> ProgramSlice:
        """Compute backward slice: all lines that causally affect the target point.

        Slice(s, v) = { n in V_PDG | n ->(data union control)* s }

        This walks the CALLS and REFERENCES edges backward from the target,
        collecting all upstream definitions and dependencies.
        """
        target_node = self._find_node_at_line(target_file, target_line)
        if not target_node:
            return ProgramSlice(
                target_file=target_file,
                target_line=target_line,
                target_variable=target_variable,
                slice_lines=[],
                token_count=0,
                slice_type="backward",
                metadata={"error": "Target node not found"},
            )

        # BFS backward through the graph following CALLS, REFERENCES, CONTAINS edges
        visited: set[int] = {target_node.id}
        queue: list[tuple[int, int]] = [(target_node.id, 0)]  # (node_id, depth)
        collected_nodes: list[tuple[GraphNode, int]] = [(target_node, 0)]

        backward_edges = {EdgeKind.CALLS, EdgeKind.REFERENCES, EdgeKind.CONTAINS}

        while queue:
            current_id, depth = queue.pop(0)
            if depth > 3:
                continue

            neighbors = self.store.get_neighbors(current_id, direction="incoming")
            for neighbor in neighbors:
                if neighbor.id not in visited and neighbor.kind != NodeKind.FILE:
                    # Only follow relevant edge types
                    edges = self.store.get_edges(target_id=current_id, source_id=neighbor.id)
                    relevant = any(e.kind in backward_edges for e in edges)
                    if relevant or depth == 0:
                        visited.add(neighbor.id)
                        collected_nodes.append((neighbor, depth + 1))
                        queue.append((neighbor.id, depth + 1))

        # Also find variables that feed into this node via DEF_USE
        if target_variable:
            for edge in self.store.get_edges(source_id=target_node.id):
                if edge.kind == EdgeKind.DEF_USE:
                    var_node = self.store.get_node(edge.target_id)
                    if var_node and var_node.id not in visited:
                        visited.add(var_node.id)
                        collected_nodes.append((var_node, 1))

        # Extract source lines from collected nodes
        slice_lines = self._extract_lines(collected_nodes, target_file, target_line)
        token_count = sum(max(1, len(line_text) // 4) for _, _, line_text in slice_lines)

        return ProgramSlice(
            target_file=target_file,
            target_line=target_line,
            target_variable=target_variable,
            slice_lines=slice_lines,
            token_count=token_count,
            slice_type="backward",
            metadata={"nodes_visited": len(visited), "depth": 3},
        )

    def forward_slice(
        self,
        target_file: str,
        target_line: int,
        target_variable: str | None = None,
    ) -> ProgramSlice:
        """Compute forward slice: all lines affected by the target point.

        Walks CALLS, CALLED_BY, and DEF_USE edges forward to find downstream impact.
        """
        target_node = self._find_node_at_line(target_file, target_line)
        if not target_node:
            return ProgramSlice(
                target_file=target_file,
                target_line=target_line,
                target_variable=target_variable,
                slice_lines=[],
                token_count=0,
                slice_type="forward",
                metadata={"error": "Target node not found"},
            )

        visited: set[int] = {target_node.id}
        queue: list[tuple[int, int]] = [(target_node.id, 0)]
        collected_nodes: list[tuple[GraphNode, int]] = [(target_node, 0)]

        forward_edges = {EdgeKind.CALLS, EdgeKind.CALLED_BY, EdgeKind.DEF_USE, EdgeKind.REFERENCES}

        while queue:
            current_id, depth = queue.pop(0)
            if depth > 3:
                continue

            neighbors = self.store.get_neighbors(current_id, direction="outgoing")
            for neighbor in neighbors:
                if neighbor.id not in visited and neighbor.kind != NodeKind.FILE:
                    edges = self.store.get_edges(source_id=current_id, target_id=neighbor.id)
                    relevant = any(e.kind in forward_edges for e in edges)
                    if relevant or depth == 0:
                        visited.add(neighbor.id)
                        collected_nodes.append((neighbor, depth + 1))
                        queue.append((neighbor.id, depth + 1))

        slice_lines = self._extract_lines(collected_nodes, target_file, target_line)
        token_count = sum(max(1, len(line_text) // 4) for _, _, line_text in slice_lines)

        return ProgramSlice(
            target_file=target_file,
            target_line=target_line,
            target_variable=target_variable,
            slice_lines=slice_lines,
            token_count=token_count,
            slice_type="forward",
            metadata={"nodes_visited": len(visited), "depth": 3},
        )

    def impact_analysis(
        self,
        changed_files: list[str],
        changed_ranges: list[tuple[int, int]] | None = None,
    ) -> ImpactAnalysis:
        """Analyze the impact of changes across the codebase.

        Given a set of changed files (and optional line ranges), finds all
        downstream functions and files that might be affected.
        """
        changed_symbols: list[GraphNode] = []
        impacted_functions: list[GraphNode] = []
        impacted_files: set[str] = set()
        impact_chain: list[tuple[GraphNode, str, GraphNode]] = []

        # 1. Collect symbols in changed files
        for fpath in changed_files:
            symbols = self.store.get_nodes_by_file(fpath)
            for sym in symbols:
                if sym.kind in [NodeKind.FUNCTION, NodeKind.CLASS, NodeKind.METHOD]:
                    if changed_ranges:
                        # Filter to symbols within changed ranges
                        for start, end in changed_ranges:
                            if sym.start_line and sym.start_line <= end and (sym.end_line or 0) >= start:
                                changed_symbols.append(sym)
                                break
                    else:
                        changed_symbols.append(sym)

        # 2. For each changed symbol, find all callers (transitive)
        seen_ids: set[int] = set()
        for sym in changed_symbols:
            self._find_transitive_callers(sym.id, impacted_functions, impacted_files, impact_chain, seen_ids, depth=0)

        # 3. Find files that import changed files
        for fpath in changed_files:
            dependents = self.cpg.get_dependents(fpath)
            for dep in dependents:
                if dep.file_path and dep.file_path not in changed_files:
                    impacted_files.add(dep.file_path)

        summary_lines = [f"### Impact Analysis"]
        summary_lines.append(f"**Changed files:** {', '.join(f'`{f}`' for f in changed_files)}")
        summary_lines.append(f"**Changed symbols:** {len(changed_symbols)}")
        summary_lines.append(f"**Impacted functions:** {len(impacted_functions)}")
        summary_lines.append(f"**Impacted files:** {len(impacted_files)}")

        if changed_symbols:
            summary_lines.append("\n**Changed symbols:**")
            for s in changed_symbols[:10]:
                summary_lines.append(f"- `{s.name}` ({s.file_path}:{s.start_line})")

        if impacted_functions:
            summary_lines.append("\n**Impacted functions (verify these):**")
            for f in impacted_functions[:15]:
                summary_lines.append(f"- `{f.name}` ({f.file_path}:{f.start_line})")

        if impacted_files:
            summary_lines.append(f"\n**Files to check:** {', '.join(f'`{f}`' for f in sorted(impacted_files)[:10])}")

        summary = "\n".join(summary_lines)
        token_count = max(1, len(summary) // 4)

        return ImpactAnalysis(
            changed_files=changed_files,
            changed_symbols=changed_symbols,
            impacted_functions=impacted_functions,
            impacted_files=sorted(impacted_files),
            impact_chain=impact_chain,
            summary=summary,
            token_count=token_count,
        )

    def _find_node_at_line(self, file_path: str, line: int) -> GraphNode | None:
        """Find the node closest to a specific line in a file."""
        candidates: list[GraphNode] = []
        for kind in [NodeKind.FUNCTION, NodeKind.METHOD, NodeKind.CLASS, NodeKind.CHUNK]:
            for node in self.store.get_nodes_by_kind(kind):
                if node.file_path and file_path in node.file_path:
                    if node.start_line and node.end_line:
                        if node.start_line <= line <= node.end_line:
                            candidates.append(node)

        if not candidates:
            # Fallback: find closest node
            for kind in [NodeKind.FUNCTION, NodeKind.METHOD, NodeKind.CLASS]:
                for node in self.store.get_nodes_by_kind(kind):
                    if node.file_path and file_path in node.file_path:
                        if node.start_line:
                            candidates.append(node)

        if not candidates:
            return None

        # Return the node closest to the target line
        return min(candidates, key=lambda n: abs((n.start_line or 0) - line))

    def _find_transitive_callers(
        self,
        node_id: int,
        impacted: list[GraphNode],
        impacted_files: set[str],
        chain: list[tuple[GraphNode, str, GraphNode]],
        visited: set[int],
        depth: int,
        max_depth: int = 3,
    ):
        """Recursively find all callers of a function."""
        if depth > max_depth or node_id in visited:
            return
        visited.add(node_id)

        callers = self.store.get_neighbors(node_id, EdgeKind.CALLS, direction="incoming")
        for caller in callers:
            if caller.id not in visited and caller.kind != NodeKind.FILE:
                impacted.append(caller)
                if caller.file_path:
                    impacted_files.add(caller.file_path)
                chain.append((caller, "CALLS", self.store.get_node(node_id)))
                self._find_transitive_callers(
                    caller.id, impacted, impacted_files, chain, visited, depth + 1, max_depth
                )

    def _extract_lines(
        self,
        nodes: list[tuple[GraphNode, int]],
        target_file: str,
        target_line: int,
    ) -> list[tuple[str, int, str]]:
        """Extract source lines from collected nodes, prioritizing the target file."""
        result: list[tuple[str, int, str]] = []
        seen_lines: set[tuple[str, int]] = set()

        # Sort: target file first, then by line number
        def sort_key(item: tuple[GraphNode, int]) -> tuple[int, int]:
            node, depth = item
            is_target = 0 if (node.file_path and target_file in node.file_path) else 1
            return (is_target, abs((node.start_line or 0) - target_line))

        nodes.sort(key=sort_key)

        for node, depth in nodes:
            if node.full_body and node.start_line and node.end_line:
                file_path = node.file_path or "unknown"
                lines = node.full_body.split("\n")
                for i, line_text in enumerate(lines):
                    line_num = node.start_line + i
                    key = (file_path, line_num)
                    if key not in seen_lines:
                        seen_lines.add(key)
                        prefix = ">>>" if file_path == target_file and line_num == target_line else "   "
                        result.append((file_path, line_num, f"{prefix} {line_text}"))

        return result
