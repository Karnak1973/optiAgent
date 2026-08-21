"""MCPServer exposing Synapse code intelligence tools for AI Agents."""

from pathlib import Path
from mcp.server.mcpserver import MCPServer

from synapse.graph.cpg import CodePropertyGraph
from synapse.graph.model import NodeKind
from synapse.graph.store import GraphStore
from synapse.indexer.embedder import Embedder
from synapse.indexer.graph_builder import GraphBuilder
from synapse.retriever.diff_aware import DiffAwareContextEngine
from synapse.retriever.fingerprinter import CodebaseFingerprinter
from synapse.retriever.graph_expander import GraphExpander
from synapse.retriever.hybrid_search import HybridSearch
from synapse.retriever.prompt_compressor import PromptCompressor
from synapse.retriever.zoom_controller import ZoomController

mcp = MCPServer("synapse-code-intelligence")

# Global cache of loaded CPG
_cpg_cache: dict[str, tuple[CodePropertyGraph, HybridSearch, ZoomController]] = {}


def get_or_load_cpg(repo_path: str = ".") -> tuple[CodePropertyGraph, HybridSearch, ZoomController]:
    path_obj = Path(repo_path).resolve()
    repo_str = str(path_obj)
    if repo_str in _cpg_cache:
        return _cpg_cache[repo_str]

    db_path = path_obj / ".synapse" / "graph.db"
    if not db_path.exists():
        builder = GraphBuilder(root=path_obj, db_path=db_path)
        cpg = builder.build()
    else:
        store = GraphStore(db_path)
        cpg = CodePropertyGraph(store)

    embedder = Embedder()
    searcher = HybridSearch(cpg.store, embedder)
    searcher.build_index()
    zoom = ZoomController(cpg)

    _cpg_cache[repo_str] = (cpg, searcher, zoom)
    return _cpg_cache[repo_str]


@mcp.tool()
def synapse_search(query: str, repo_path: str = ".", top_k: int = 5) -> str:
    """Search the codebase using hybrid BM25 + dense semantic retrieval with graph-aware reranking.
    Returns high-signal concise code snippets (~10 lines).
    """
    cpg, searcher, zoom = get_or_load_cpg(repo_path)
    results = searcher.search(query, top_k=top_k)
    if not results:
        return "No matches found."

    lines = []
    for i, res in enumerate(results):
        node = res.node
        kind_str = node.kind.value if hasattr(node.kind, "value") else str(node.kind)
        lines.append(f"### [{i+1}] {node.name} ({kind_str})")
        lines.append(f"**Location:** `{node.file_path}:{node.start_line}` | **Score:** {res.score:.3f}")
        snippet = res.snippet or node.skeleton or node.full_body or ""
        lines.append(f"```python\n{snippet}\n```\n")
    return "\n".join(lines)


@mcp.tool()
def synapse_map(repo_path: str = ".") -> str:
    """Get the high-level architectural map of the codebase (L0 zoom, ~100-300 tokens).
    Shows packages, modules, dependencies and exported symbols.
    """
    cpg, searcher, zoom = get_or_load_cpg(repo_path)
    ctx = zoom.get_architecture_map()
    return f"```\n{ctx.content}\n```\n(Tokens: ~{ctx.token_count})"


@mcp.tool()
def synapse_outline(file_path: str, repo_path: str = ".") -> str:
    """Get the skeleton outline of a file (L1 zoom, ~300-800 tokens).
    Shows class definitions, method signatures and docstrings with elided bodies.
    """
    cpg, searcher, zoom = get_or_load_cpg(repo_path)
    ctx = zoom.get_module_skeleton(file_path)
    return f"```python\n{ctx.content}\n```\n(Tokens: ~{ctx.token_count})"


@mcp.tool()
def synapse_inspect(symbol: str, level: int = 2, repo_path: str = ".") -> str:
    """Inspect a specific symbol (class, function, method) at progressive detail levels:
    level 2 for interface contract and callees (~500 tokens), level 3 for full implementation body (~1500 tokens).
    """
    cpg, searcher, zoom = get_or_load_cpg(repo_path)
    if level == 2:
        ctx = zoom.get_interface_contracts(symbol)
    else:
        ctx = zoom.get_implementation(symbol)
    return f"```python\n{ctx.content}\n```\n(Tokens: ~{ctx.token_count})"


@mcp.tool()
def synapse_callers(symbol: str, repo_path: str = ".") -> str:
    """Find all callers that invoke a specific function or method across the entire codebase."""
    cpg, searcher, zoom = get_or_load_cpg(repo_path)
    callers = cpg.get_callers(symbol)
    if not callers:
        return f"No callers found for '{symbol}'."
    lines = [f"Callers of `{symbol}`:"]
    for c in callers:
        lines.append(f"- `{c.name}` ({c.file_path}:{c.start_line})")
    return "\n".join(lines)


@mcp.tool()
def synapse_callees(symbol: str, repo_path: str = ".") -> str:
    """Find all functions and methods called by a specific symbol."""
    cpg, searcher, zoom = get_or_load_cpg(repo_path)
    callees = cpg.get_callees(symbol)
    if not callees:
        return f"No callees found for '{symbol}'."
    lines = [f"Callees of `{symbol}`:"]
    for c in callees:
        lines.append(f"- `{c.name}` ({c.file_path}:{c.start_line})")
    return "\n".join(lines)


@mcp.tool()
def synapse_fingerprint(symbol: str, repo_path: str = ".") -> str:
    """Get an ultra-compact contextual fingerprint (~20 tokens) of a symbol showing its role,
    popularity, in/out degrees and centrality rank.
    """
    cpg, searcher, zoom = get_or_load_cpg(repo_path)
    for kind in [NodeKind.FUNCTION, NodeKind.CLASS, NodeKind.METHOD]:
        for n in cpg.store.get_nodes_by_kind(kind):
            if n.name == symbol:
                fp = cpg.get_fingerprint(n.id)
                return fp.to_compact_str()
    return f"Symbol '{symbol}' not found."


@mcp.tool()
def synapse_expand(symbol: str, token_budget: int = 2048, repo_path: str = ".") -> str:
    """Expand context around a symbol using Personalized PageRank (PPR) to extract the most
    structurally relevant subgraph fitting the token budget.
    """
    cpg, searcher, zoom = get_or_load_cpg(repo_path)
    expander = GraphExpander(cpg)
    target_node = None
    for kind in [NodeKind.FUNCTION, NodeKind.CLASS, NodeKind.METHOD]:
        for n in cpg.store.get_nodes_by_kind(kind):
            if n.name == symbol:
                target_node = n
                break
        if target_node:
            break

    if not target_node:
        return f"Symbol '{symbol}' not found."

    expanded = expander.expand([target_node.id], token_budget=token_budget)
    lines = [f"### Personalized PageRank Context Expansion for `{symbol}` (Tokens: ~{expanded.total_tokens})"]
    for node, score in expanded.expanded_nodes:
        lines.append(f"- `{node.name}` ({node.kind.value if hasattr(node.kind, 'value') else node.kind}) [PPR: {score:.4f}] — `{node.file_path}:{node.start_line}`")
    return "\n".join(lines)


@mcp.tool()
def synapse_prompt(symbol: str, token_budget: int = 2048, repo_path: str = ".") -> str:
    """Generate a high-density, graph-compressed markdown context block for an LLM agent turn.
    Contains focus code body + 1-hop interface signatures + data schemas.
    """
    cpg, searcher, zoom = get_or_load_cpg(repo_path)
    compressor = PromptCompressor(cpg)
    result = compressor.compress(focus_symbol_name=symbol, token_budget=token_budget)
    return result.text


@mcp.tool()
def synapse_diff_context(changed_files: list[str], repo_path: str = ".") -> str:
    """Compute an incremental context delta from a list of changed/staged files,
    showing modified symbol signatures and impacted cross-file callers.
    """
    cpg, searcher, zoom = get_or_load_cpg(repo_path)
    engine = DiffAwareContextEngine(cpg)
    delta = engine.compute_delta_from_files(changed_files)
    return delta.summary_markdown


@mcp.tool()
def synapse_clusters(repo_path: str = ".") -> str:
    """View functional domain clusters and architectural topology of the repository."""
    cpg, searcher, zoom = get_or_load_cpg(repo_path)
    fingerprinter = CodebaseFingerprinter(cpg)
    clusters = fingerprinter.get_topology_clusters()
    lines = ["### Repository Topology Clusters"]
    for c in clusters:
        lines.append(f"\n**Cluster {c.cluster_id}: `{c.name}`** ({c.member_count} symbols)")
        if c.top_symbols:
            lines.append(f"  *Key Symbols:* {', '.join(c.top_symbols)}")
        if c.lead_files:
            lines.append(f"  *Files:* {', '.join(c.lead_files)}")
    return "\n".join(lines)


@mcp.tool()
def synapse_slice(target: str, direction: str = "backward", repo_path: str = ".") -> str:
    """Compute a program slice (L4 zoom) — extracts only the lines that causally affect
    a specific variable or statement. Target format: file_path:line_number[:variable].
    Uses backward slicing by default (what feeds into this point), or forward (what this affects).
    """
    from synapse.retriever.program_slicer import ProgramSlicer
    cpg, searcher, zoom = get_or_load_cpg(repo_path)
    slicer = ProgramSlicer(cpg)

    parts = target.split(":")
    if len(parts) < 2:
        return "Invalid target format. Use: file_path:line_number[:variable]"

    file_path = parts[0]
    try:
        line = int(parts[1])
    except ValueError:
        return f"Invalid line number: {parts[1]}"

    variable = parts[2] if len(parts) > 2 else None

    if direction == "forward":
        result = slicer.forward_slice(file_path, line, variable)
    else:
        result = slicer.backward_slice(file_path, line, variable)

    if not result.slice_lines:
        return f"No slice found for {target}."

    lines = [f"### Program Slice ({result.slice_type})"]
    lines.append(f"**Target:** `{file_path}:{line}`" + (f" (variable: `{variable}`)" if variable else ""))
    lines.append(f"**Lines in slice:** {len(result.slice_lines)}\n")
    for fpath, lnum, text in result.slice_lines:
        lines.append(text)
    return "\n".join(lines)


@mcp.tool()
def synapse_impact(changed_files: list[str], repo_path: str = ".") -> str:
    """Analyze the impact of changes across the codebase. Given a list of changed files,
    finds all downstream functions and files that might be affected (transitive caller analysis).
    """
    from synapse.retriever.program_slicer import ProgramSlicer
    cpg, searcher, zoom = get_or_load_cpg(repo_path)
    slicer = ProgramSlicer(cpg)
    result = slicer.impact_analysis(changed_files)
    return result.summary


@mcp.tool()
def synapse_adaptive(query: str, symbol: str = None, token_budget: int = None, repo_path: str = ".") -> str:
    """Task-adaptive retrieval: auto-detects task type (explore/understand/edit/debug/refactor/review)
    from the query and retrieves an optimized multi-level context block.
    """
    from synapse.retriever.task_adaptive import TaskAdaptiveRetriever
    cpg, searcher, zoom = get_or_load_cpg(repo_path)
    retriever = TaskAdaptiveRetriever(cpg, searcher)
    result = retriever.retrieve(query, target_symbol=symbol, token_budget=token_budget)

    task_type = result["task_type"]
    strategy = result["strategy"]
    contexts = result["contexts"]
    total_tokens = result["total_tokens"]

    output = [f"### Task-Adaptive Retrieval\n**Task:** {task_type.value} — {strategy.description}\n"]
    for ctx in contexts:
        output.append(f"---\n{ctx.content}\n")
    output.append(f"\n**Total tokens:** ~{total_tokens}")
    return "\n".join(output)


def main():
    mcp.run()


if __name__ == "__main__":
    main()
