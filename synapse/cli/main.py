import sys
import time
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table
from rich.tree import Tree
import typer

from synapse.graph.cpg import CodePropertyGraph
from synapse.graph.model import NodeKind, ZoomLevel
from synapse.graph.store import GraphStore
from synapse.indexer.embedder import Embedder
from synapse.indexer.graph_builder import GraphBuilder
from synapse.retriever.hybrid_search import HybridSearch
from synapse.retriever.program_slicer import ProgramSlicer
from synapse.retriever.zoom_controller import ZoomController

app = typer.Typer(
    name="synapse",
    help="Synapse — Graph-based code intelligence for token-efficient AI agents",
    add_completion=False,
)
console = Console()


def get_cpg(path: Path) -> CodePropertyGraph:
    store_path = path.resolve() / ".synapse" / "graph.db"
    if not store_path.exists():
        console.print(f"[red]Error: Graph store not found at {store_path}[/red]")
        console.print("Please run [bold cyan]synapse index[/bold cyan] first.")
        raise typer.Exit(code=1)

    store = GraphStore(store_path)
    return CodePropertyGraph(store)


@app.command()
def index(path: Path = typer.Argument(".", help="Repository path to index")):
    """Index a repository and build the Code Property Graph."""
    target_dir = path.resolve()
    synapse_dir = target_dir / ".synapse"
    synapse_dir.mkdir(parents=True, exist_ok=True)
    db_path = synapse_dir / "graph.db"

    start_time = time.time()
    builder = GraphBuilder(root=target_dir, db_path=db_path)
    cpg = builder.build()
    elapsed = time.time() - start_time

    store = cpg.store
    files_count = len(store.get_nodes_by_kind(NodeKind.FILE))
    nodes_count = store.node_count
    edges_count = store.edge_count

    table = Table(title="Synapse Indexing Statistics", border_style="cyan")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="magenta")

    table.add_row("Files Indexed", str(files_count))
    table.add_row("Total Nodes", str(nodes_count))
    table.add_row("Total Edges", str(edges_count))
    table.add_row("Time Taken", f"{elapsed:.2f}s")

    console.print(table)
    console.print(f"[bold green]Repository indexed successfully into {db_path}[/bold green]")


@app.command()
def search(query: str, path: Path = typer.Argument("."), top_k: int = 10, content: str = "code"):
    """Search the codebase with hybrid BM25 + semantic search."""
    cpg = get_cpg(path)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("[cyan]Initializing search index...", total=None)
        embedder = Embedder()
        searcher = HybridSearch(cpg.store, embedder)
        searcher.build_index()
        progress.update(task, description="[green]Searching...[/green]")

        results = searcher.search(query, top_k=top_k, content_filter=content)

    if not results:
        console.print("[yellow]No results found.[/yellow]")
        return

    for i, res in enumerate(results):
        node = res.node
        title = f"[{i+1}] {node.name} ({node.kind.value if hasattr(node.kind, 'value') else node.kind}) — {node.file_path or 'unknown'}"
        body = res.snippet or node.skeleton or node.full_body or str(node)

        if len(body) > 400:
            body = body[:400] + "...\n(truncated)"

        panel = Panel(body, title=title, border_style="blue")
        console.print(panel)
        console.print(f"[dim]Score: {res.score:.4f} | Match Type: {res.match_type}[/dim]\n")


@app.command()
def map(path: Path = typer.Argument(".")):
    """Show the architectural map of the repository (L0 zoom)."""
    cpg = get_cpg(path)
    zoom = ZoomController(cpg)
    context = zoom.get_architecture_map()

    tree = Tree("[bold cyan]Repository Architecture (L0 Zoom)[/bold cyan]")
    lines = context.content.split("\n")
    current_node = tree
    for line in lines:
        if line.startswith("── "):
            current_node = tree.add(f"[bold blue]{line[3:]}[/bold blue]")
        elif line.startswith("│  "):
            current_node.add(f"[green]{line[3:]}[/green]")

    console.print(tree)
    console.print(f"[dim]Token cost: ~{context.token_count} tokens[/dim]")


@app.command()
def outline(file_path: str, path: Path = typer.Argument(".")):
    """Show the skeleton outline of a file (L1 zoom)."""
    cpg = get_cpg(path)
    zoom = ZoomController(cpg)
    context = zoom.get_module_skeleton(file_path)

    panel = Panel(context.content, title=f"File Skeleton (L1): {file_path}", border_style="cyan")
    console.print(panel)
    console.print(f"[dim]Token cost: ~{context.token_count} tokens[/dim]")


@app.command()
def inspect(symbol: str, path: Path = typer.Argument("."), level: int = 2):
    """Inspect a symbol at specified zoom level (L2-L3)."""
    cpg = get_cpg(path)
    zoom = ZoomController(cpg)

    if level == 2:
        context = zoom.get_interface_contracts(symbol)
        title = f"Interface Contract (L2): {symbol}"
    else:
        context = zoom.get_implementation(symbol)
        title = f"Implementation Body (L3): {symbol}"

    panel = Panel(context.content, title=title, border_style="magenta")
    console.print(panel)
    console.print(f"[dim]Token cost: ~{context.token_count} tokens[/dim]")


@app.command()
def callers(symbol: str, path: Path = typer.Argument(".")):
    """Show all callers of a function/method."""
    cpg = get_cpg(path)
    caller_nodes = cpg.get_callers(symbol)

    if not caller_nodes:
        console.print(f"[yellow]No callers found for '{symbol}'.[/yellow]")
        return

    tree = Tree(f"[bold cyan]Callers of {symbol}[/bold cyan]")
    for c in caller_nodes:
        tree.add(f"[green]{c.name}[/green] [dim]({c.file_path}:{c.start_line})[/dim]")
    console.print(tree)


@app.command()
def callees(symbol: str, path: Path = typer.Argument(".")):
    """Show all functions/methods called by a symbol."""
    cpg = get_cpg(path)
    callee_nodes = cpg.get_callees(symbol)

    if not callee_nodes:
        console.print(f"[yellow]No callees found for '{symbol}'.[/yellow]")
        return

    tree = Tree(f"[bold cyan]Callees of {symbol}[/bold cyan]")
    for c in callee_nodes:
        tree.add(f"[green]{c.name}[/green] [dim]({c.file_path}:{c.start_line})[/dim]")
    console.print(tree)


@app.command()
def stats(path: Path = typer.Argument(".")):
    """Show statistics about the indexed repository."""
    cpg = get_cpg(path)
    store = cpg.store

    files_count = len(store.get_nodes_by_kind(NodeKind.FILE))
    nodes_count = store.node_count
    edges_count = store.edge_count

    table = Table(title="Repository Statistics")
    table.add_column("Metric", style="cyan")
    table.add_column("Count", style="magenta")

    table.add_row("Files", str(files_count))
    table.add_row("Total Nodes", str(nodes_count))
    table.add_row("Total Edges", str(edges_count))

    console.print(table)


@app.command()
def expand(symbol: str, path: Path = typer.Argument("."), budget: int = 2048):
    """Expand context around a symbol using Personalized PageRank (PPR)."""
    from synapse.retriever.graph_expander import GraphExpander
    cpg = get_cpg(path)
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
        console.print(f"[red]Symbol '{symbol}' not found.[/red]")
        return

    expanded = expander.expand([target_node.id], token_budget=budget)
    table = Table(title=f"Personalized PageRank Subgraph for '{symbol}' (~{expanded.total_tokens} tokens)")
    table.add_column("Symbol", style="cyan")
    table.add_column("Kind", style="magenta")
    table.add_column("PPR Score", style="green")
    table.add_column("Location", style="dim")

    for node, score in expanded.expanded_nodes:
        table.add_row(node.name, str(node.kind.value if hasattr(node.kind, 'value') else node.kind), f"{score:.4f}", f"{node.file_path}:{node.start_line}")

    console.print(table)


@app.command()
def prompt(symbol: str, path: Path = typer.Argument("."), budget: int = 2048):
    """Generate a graph-compressed prompt block for an LLM turn."""
    from synapse.retriever.prompt_compressor import PromptCompressor
    cpg = get_cpg(path)
    compressor = PromptCompressor(cpg)
    result = compressor.compress(focus_symbol_name=symbol, token_budget=budget)

    panel = Panel(result.text, title=f"Graph-Compressed Prompt (~{result.token_count} tokens)", border_style="cyan")
    console.print(panel)


@app.command()
def clusters(path: Path = typer.Argument(".")):
    """Show functional domain clusters and topology of the codebase."""
    from synapse.retriever.fingerprinter import CodebaseFingerprinter
    cpg = get_cpg(path)
    fingerprinter = CodebaseFingerprinter(cpg)
    cl_list = fingerprinter.get_topology_clusters()

    table = Table(title="Codebase Topology Clusters")
    table.add_column("ID", style="cyan")
    table.add_column("Domain Cluster", style="bold green")
    table.add_column("Members", style="magenta")
    table.add_column("Key Symbols", style="white")

    for c in cl_list:
        table.add_row(str(c.cluster_id), c.name, str(c.member_count), ", ".join(c.top_symbols))

    console.print(table)


@app.command()
def slice(
    target: str = typer.Argument(..., help="Target: file_path:line_number[:variable]"),
    path: Path = typer.Argument("."),
    direction: str = typer.Option("backward", help="Slice direction: backward or forward"),
):
    """Compute a program slice (L4 zoom) — only lines causally affecting the target point.

    Example: synapse slice auth/service.py:52:user_token
    """
    cpg = get_cpg(path)
    slicer = ProgramSlicer(cpg)

    parts = target.split(":")
    if len(parts) < 2:
        console.print("[red]Invalid target format. Use: file_path:line[:variable][/red]")
        raise typer.Exit(code=1)

    file_path = parts[0]
    try:
        line = int(parts[1])
    except ValueError:
        console.print(f"[red]Invalid line number: {parts[1]}[/red]")
        raise typer.Exit(code=1)

    variable = parts[2] if len(parts) > 2 else None

    if direction == "forward":
        result = slicer.forward_slice(file_path, line, variable)
    else:
        result = slicer.backward_slice(file_path, line, variable)

    if not result.slice_lines:
        console.print(f"[yellow]No slice found for {target}.[/yellow]")
        return

    content = f"[bold]Program Slice ({result.slice_type})[/bold]\n"
    content += f"Target: {file_path}:{line}" + (f" (variable: {variable})" if variable else "")
    content += f"\nLines in slice: {len(result.slice_lines)}\n\n"

    for fpath, lnum, text in result.slice_lines:
        content += f"{text}\n"

    panel = Panel(content, title=f"Program Slice (L4): {target}", border_style="red")
    console.print(panel)
    console.print(f"[dim]Token cost: ~{result.token_count} tokens[/dim]")


@app.command()
def impact(
    files: list[str] = typer.Argument(..., help="Changed files to analyze"),
    path: Path = typer.Argument("."),
):
    """Analyze impact of changes across the codebase.

    Example: synapse impact auth/service.py auth/jwt_handler.py
    """
    cpg = get_cpg(path)
    slicer = ProgramSlicer(cpg)
    result = slicer.impact_analysis(files)

    panel = Panel(result.summary, title="Impact Analysis", border_style="red")
    console.print(panel)
    console.print(f"[dim]Token cost: ~{result.token_count} tokens[/dim]")


@app.command()
def adaptive(
    query: str = typer.Argument(..., help="Natural language query"),
    symbol: str = typer.Option(None, help="Target symbol to focus on"),
    path: Path = typer.Argument("."),
    budget: int = typer.Option(None, help="Override token budget"),
):
    """Task-adaptive retrieval — auto-detects task type and retrieves optimized context.

    Example: synapse adaptive "how does login work" --symbol AuthService.login
    """
    from synapse.retriever.task_adaptive import TaskAdaptiveRetriever
    from synapse.retriever.hybrid_search import HybridSearch
    from synapse.indexer.embedder import Embedder

    cpg = get_cpg(path)
    embedder = Embedder()
    searcher = HybridSearch(cpg.store, embedder)
    searcher.build_index()

    retriever = TaskAdaptiveRetriever(cpg, searcher)
    result = retriever.retrieve(query, target_symbol=symbol, token_budget=budget)

    task_type = result["task_type"]
    strategy = result["strategy"]
    contexts = result["contexts"]
    total_tokens = result["total_tokens"]

    console.print(f"[bold cyan]Task Detected:[/bold cyan] {task_type.value}")
    console.print(f"[dim]Strategy: {strategy.description} | Budget: {strategy.token_budget} tokens[/dim]\n")

    for ctx in contexts:
        level_name = {
            ZoomLevel.ARCHITECTURE: "L0 Architecture",
            ZoomLevel.SKELETON: "L1 Skeleton",
            ZoomLevel.INTERFACE: "L2 Interface",
            ZoomLevel.IMPLEMENTATION: "L3 Implementation",
            ZoomLevel.SLICE: "L4 Program Slice",
        }.get(ctx.zoom_level, f"L{ctx.zoom_level}")

        panel = Panel(ctx.content, title=f"{level_name} (~{ctx.token_count} tokens)", border_style="blue")
        console.print(panel)

    console.print(f"\n[bold green]Total tokens: ~{total_tokens}[/bold green]")


if __name__ == "__main__":
    app()


