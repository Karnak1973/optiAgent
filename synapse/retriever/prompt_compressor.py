"""Graph-Compressed Prompt Generator for minimal LLM token consumption."""

from dataclasses import dataclass
from synapse.graph.cpg import CodePropertyGraph
from synapse.graph.model import EdgeKind, GraphNode, NodeKind
from .graph_expander import ExpandedContext, GraphExpander


@dataclass
class CompressedPrompt:
    text: str
    token_count: int
    focus_symbol: str | None
    referenced_files: list[str]


class PromptCompressor:
    """Formats graph-retrieved subgraphs into high-density, low-token prompts
    structured with progressive detail for LLMs.
    """

    def __init__(self, cpg: CodePropertyGraph):
        self.cpg = cpg
        self.store = cpg.store
        self.expander = GraphExpander(cpg)

    def compress(
        self,
        focus_symbol_name: str | None = None,
        seed_node_ids: list[int] | None = None,
        token_budget: int = 2048,
    ) -> CompressedPrompt:
        """Create a graph-compressed prompt block.
        
        Structure:
        1. Context header
        2. Focus implementation (if specified)
        3. Neighbor interface signatures
        4. Cross-file type/data models
        """
        focus_node: GraphNode | None = None
        referenced_files: set[str] = set()

        if focus_symbol_name:
            for kind in [NodeKind.FUNCTION, NodeKind.CLASS, NodeKind.METHOD]:
                for n in self.store.get_nodes_by_kind(kind):
                    if n.name == focus_symbol_name:
                        focus_node = n
                        break
                if focus_node:
                    break

        # If seed_node_ids not provided, use focus_node
        if seed_node_ids is None:
            seed_node_ids = [focus_node.id] if focus_node else []

        expanded = self.expander.expand(seed_node_ids, token_budget=token_budget)

        lines: list[str] = []
        lines.append("# Codebase Context (Graph-Compressed by Synapse)")

        # 1. Focus Section
        if focus_node:
            f_path = focus_node.file_path or "unknown"
            referenced_files.add(f_path)
            lines.append(f"\n--- FOCUS: {focus_node.name} [{f_path}:{focus_node.start_line}-{focus_node.end_line}] ---")
            body = focus_node.full_body or focus_node.skeleton or focus_node.signature or ""
            lines.append(f"```python\n{body}\n```")

        # 2. Callee / Caller Interface Contracts
        interfaces: list[str] = []
        models: list[str] = []

        for node, score in expanded.expanded_nodes:
            if focus_node and node.id == focus_node.id:
                continue

            if node.file_path:
                referenced_files.add(node.file_path)

            if node.kind == NodeKind.CLASS:
                skel = node.skeleton or node.signature or f"class {node.name}: ..."
                models.append(f"# {node.file_path}\n{skel}")
            elif node.kind in [NodeKind.FUNCTION, NodeKind.METHOD]:
                sig = node.signature or node.skeleton or f"def {node.name}(...): ..."
                doc = f'    """{node.docstring}"""\n' if node.docstring else ""
                interfaces.append(f"{sig}\n{doc}    ...")

        if interfaces:
            lines.append("\n--- CONNECTED INTERFACES (Callees & Callers) ---")
            lines.append("```python\n" + "\n\n".join(interfaces[:8]) + "\n```")

        if models:
            lines.append("\n--- DATA TYPES & SCHEMAS ---")
            lines.append("```python\n" + "\n\n".join(models[:5]) + "\n```")

        output_text = "\n".join(lines)
        token_count = max(1, len(output_text) // 4)

        return CompressedPrompt(
            text=output_text,
            token_count=token_count,
            focus_symbol=focus_symbol_name,
            referenced_files=sorted(referenced_files),
        )
