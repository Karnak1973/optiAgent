"""Diff-Aware Context Engine for incremental agent conversations."""

from dataclasses import dataclass, field
from pathlib import Path
import re

from synapse.graph.cpg import CodePropertyGraph
from synapse.graph.model import EdgeKind, GraphNode, NodeKind


@dataclass
class IncrementalDelta:
    modified_symbols: list[GraphNode]
    impacted_callers: list[GraphNode]
    impacted_files: list[str]
    delta_token_count: int
    summary_markdown: str


class DiffAwareContextEngine:
    """Computes incremental context deltas from modified files or git diffs,
    avoiding resending unchanged codebase context across agent turns.
    """

    def __init__(self, cpg: CodePropertyGraph):
        self.cpg = cpg
        self.store = cpg.store

    def compute_delta_from_files(
        self,
        changed_file_paths: list[str],
    ) -> IncrementalDelta:
        """Analyze impact of changed files and extract impacted callers/symbols."""
        modified_symbols: list[GraphNode] = []
        impacted_callers: list[GraphNode] = []
        impacted_files: set[str] = set(changed_file_paths)

        # 1. Collect all symbols inside the changed files
        for fpath in changed_file_paths:
            file_symbols = self.store.get_nodes_by_file(fpath)
            for sym in file_symbols:
                if sym.kind in [NodeKind.FUNCTION, NodeKind.CLASS, NodeKind.METHOD]:
                    modified_symbols.append(sym)

        # 2. Find callers across the codebase that invoke these modified symbols
        seen_caller_ids = set()
        for sym in modified_symbols:
            callers = self.cpg.get_callers(sym.name)
            for c in callers:
                if c.id not in seen_caller_ids and c.file_path not in changed_file_paths:
                    seen_caller_ids.add(c.id)
                    impacted_callers.append(c)
                    if c.file_path:
                        impacted_files.add(c.file_path)

        # 3. Format compact delta markdown
        lines = ["### Synapse Incremental Context Delta"]
        lines.append(f"**Changed Files ({len(changed_file_paths)}):** " + ", ".join(f"`{f}`" for f in changed_file_paths))

        if modified_symbols:
            lines.append("\n**Directly Modified Symbols:**")
            for s in modified_symbols[:10]:
                lines.append(f"- `{s.name}` ({s.file_path}:{s.start_line}) -> `{s.signature or '...'}`")

        if impacted_callers:
            lines.append(f"\n**Impacted Callers Requiring Verification ({len(impacted_callers)}):**")
            for c in impacted_callers[:10]:
                lines.append(f"- `{c.name}` ({c.file_path}:{c.start_line})")

        summary = "\n".join(lines)
        token_count = max(1, len(summary) // 4)

        return IncrementalDelta(
            modified_symbols=modified_symbols,
            impacted_callers=impacted_callers,
            impacted_files=sorted(impacted_files),
            delta_token_count=token_count,
            summary_markdown=summary,
        )
