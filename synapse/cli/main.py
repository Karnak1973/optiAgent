import sys
import time
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from rich import box
from rich.align import Align
from rich.columns import Columns
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich.rule import Rule
from rich.table import Table
from rich.text import Text
from rich.tree import Tree
import typer

from synapse.graph.cpg import CodePropertyGraph
from synapse.graph.model import NodeKind, ZoomLevel
from synapse.graph.store import GraphStore

app = typer.Typer(
    name="synapse",
    help="[bold cyan]Synapse[/bold cyan] — Graph-based code intelligence for token-efficient AI agents",
    add_completion=False,
    rich_markup_mode="rich",
)
console = Console()

BANNER = """[bold cyan]
  ╔═══════════════════════════════════════════════════╗
  ║   ███████╗██╗   ██╗███████╗███╗   ██╗ ██████╗███████╗██████╗  ║
  ║   ██╔════╝╚██╗ ██╔╝██╔════╝████╗  ██║██╔════╝██╔════╝██╔══██╗ ║
  ║   ███████╗ ╚████╔╝ █████╗  ██╔██╗ ██║██║     █████╗  ██████╔╝ ║
  ║   ╚════██║  ╚██╔╝  ██╔══╝  ██║╚██╗██║██║     ██╔══╝  ██╔══██╗ ║
  ║   ███████║   ██║   ███████╗██║ ╚████║╚██████╗███████╗██║  ██║ ║
  ║   ╚══════╝   ╚═╝   ╚══════╝╚═╝  ╚═══╝ ╚═════╝╚══════╝╚═╝  ╚═╝ ║
  ╚═══════════════════════════════════════════════════╝[/bold cyan]
[dim]  Graph-based code intelligence  ·  95-99% fewer tokens[/dim]
"""


def get_cpg(path: Path) -> CodePropertyGraph:
    store_path = path.resolve() / ".synapse" / "graph.db"
    if not store_path.exists():
        console.print(f"\n[bold red]  ✗ Graph store not found[/bold red]")
        console.print(f"  [dim]{store_path}[/dim]")
        console.print(f"\n  Run [bold cyan]synapse index {path}[/bold cyan] first.\n")
        raise typer.Exit(code=1)
    store = GraphStore(store_path)
    return CodePropertyGraph(store)


def _bar(value: int, max_value: int, width: int = 20, fill: str = "cyan", empty: str = "dim white") -> str:
    """Create a text-based progress bar."""
    if max_value == 0:
        filled = 0
    else:
        filled = int((value / max_value) * width)
    return f"[{fill}]{'█' * filled}[/{fill}][{empty}]{'░' * (width - filled)}[/{empty}]"


def _token_bar(value: int, max_value: int) -> str:
    """Create a colored token bar based on size."""
    if max_value == 0:
        filled = 0
    else:
        filled = int((value / max_value) * 20)
    if value < max_value * 0.3:
        color = "green"
    elif value < max_value * 0.7:
        color = "yellow"
    else:
        color = "red"
    return f"[{color}]{'█' * filled}{'░' * (20 - filled)}[/{color}] {value}"


@app.command()
def index(
    path: Path = typer.Argument(".", help="Repository path to index"),
    verbose: bool = typer.Option(False, "-v", "--verbose", help="Show detailed per-file output"),
):
    """[bold cyan]Index[/bold cyan] a repository and build the Code Property Graph."""
    from synapse.indexer.graph_builder import GraphBuilder
    from synapse.indexer.scanner import FileScanner
    from synapse.graph.model import NodeKind

    target_dir = path.resolve()

    console.print(BANNER)
    console.print(f"  [bold]Indexing:[/bold] [cyan]{target_dir}[/cyan]\n")

    start_time = time.time()

    scanner = FileScanner(root=target_dir)
    files = list(scanner.scan())

    if not files:
        console.print("  [yellow]No scannable files found.[/yellow]")
        raise typer.Exit()

    # File type breakdown
    ext_counts = {}
    for f in files:
        ext = f.path.suffix.lower() or "(no ext)"
        ext_counts[ext] = ext_counts.get(ext, 0) + 1

    ext_table = Table(show_header=False, box=None, padding=(0, 2))
    ext_table.add_column("Ext", style="cyan", width=8)
    ext_table.add_column("Count", style="white")
    ext_table.add_column("Bar", style="dim")
    max_count = max(ext_counts.values()) if ext_counts else 1
    for ext, count in sorted(ext_counts.items(), key=lambda x: -x[1]):
        ext_table.add_row(ext, str(count), _bar(count, max_count, width=15))
    console.print(ext_table)
    console.print()

    # Build the graph
    synapse_dir = target_dir / ".synapse"
    synapse_dir.mkdir(parents=True, exist_ok=True)
    db_path = synapse_dir / "graph.db"

    builder = GraphBuilder(root=target_dir, db_path=db_path)
    cpg = builder.build()
    elapsed = time.time() - start_time

    store = cpg.store
    files_count = len(store.get_nodes_by_kind(NodeKind.FILE))
    nodes_count = store.node_count
    edges_count = store.edge_count

    # Node kind breakdown
    kind_counts = {}
    for kind in NodeKind:
        count = len(store.get_nodes_by_kind(kind))
        if count > 0:
            kind_counts[kind.value] = count

    # Summary stats
    stats_table = Table(title="Indexing Results", box=box.ROUNDED, border_style="cyan", title_style="bold cyan")
    stats_table.add_column("Metric", style="bold white", width=20)
    stats_table.add_column("Value", style="bold", justify="right", width=10)
    stats_table.add_column("", width=25)
    stats_table.add_row("Files scanned", str(len(files)), _bar(len(files), len(files), 20, "cyan"))
    stats_table.add_row("Files indexed", str(files_count), _bar(files_count, len(files), 20, "blue"))
    stats_table.add_row("Total nodes", str(nodes_count), _bar(nodes_count, max(kind_counts.values()) if kind_counts else 1, 20, "green"))
    stats_table.add_row("Total edges", str(edges_count), _bar(edges_count, max(edges_count, 1), 20, "magenta"))
    stats_table.add_row("Time", f"{elapsed:.2f}s", "")
    stats_table.add_row("DB size", f"{db_path.stat().st_size / 1024:.1f} KB", "")
    console.print(stats_table)

    # Node kinds
    if kind_counts:
        console.print()
        kind_table = Table(title="Node Types", box=box.SIMPLE_HEAVY, border_style="dim", title_style="bold")
        kind_table.add_column("Type", style="cyan", width=14)
        kind_table.add_column("Count", justify="right", width=6)
        kind_table.add_column("Bar", width=30)
        max_kind = max(kind_counts.values())
        for kind_name, count in sorted(kind_counts.items(), key=lambda x: -x[1]):
            color = {"FILE": "blue", "CLASS": "red", "INTERFACE": "yellow", "FUNCTION": "green", "METHOD": "cyan", "CHUNK": "dim"}.get(kind_name, "white")
            kind_table.add_row(f"[{color}]{kind_name}[/{color}]", str(count), _bar(count, max_kind, 25, color))
        console.print(kind_table)

    console.print(f"\n  [bold green]✓[/bold green] Indexed into [cyan]{db_path}[/cyan]\n")


@app.command()
def search(query: str, path: Path = typer.Argument("."), top_k: int = 10, content: str = "code"):
    """[bold cyan]Search[/bold cyan] the codebase with hybrid BM25 + semantic search."""
    from synapse.indexer.embedder import Embedder
    from synapse.retriever.hybrid_search import HybridSearch

    cpg = get_cpg(path)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("[cyan]Building search index...", total=None)
        embedder = Embedder()
        searcher = HybridSearch(cpg.store, embedder)
        searcher.build_index()
        progress.update(task, description="[green]Searching...[/green]")
        results = searcher.search(query, top_k=top_k, content_filter=content)

    if not results:
        console.print("\n  [yellow]No results found.[/yellow]\n")
        return

    console.print()
    console.print(Rule(f"[bold cyan]Search Results: [white]\"{query}\"[/white][/bold cyan]", style="cyan"))
    console.print()

    for i, res in enumerate(results):
        node = res.node
        kind_str = node.kind.value if hasattr(node.kind, "value") else node.kind
        kind_color = {"FILE": "blue", "CLASS": "red", "INTERFACE": "yellow", "FUNCTION": "green", "METHOD": "cyan"}.get(kind_str, "white")
        file_short = Path(node.file_path).name if node.file_path else "?"

        # Score visualization
        score_pct = min(100, int(res.score * 100))
        score_bar = _bar(score_pct, 100, 15, "green" if score_pct > 70 else "yellow" if score_pct > 40 else "red")

        header = Text()
        header.append(f"  {i+1}. ", style="bold white")
        header.append(f"{node.name}", style="bold cyan")
        header.append(f"  [{kind_color}]{kind_str}[/{kind_color}]", style="dim")
        header.append(f"  {file_short}:{node.start_line or '?'}", style="dim")
        header.append(f"  [{res.match_type}]", style="dim italic")

        console.print(header)

        body = res.snippet or node.skeleton or node.full_body or str(node)
        if len(body) > 350:
            body = body[:350] + "\n  ... (truncated)"

        snippet = Panel(
            body,
            border_style="dim blue",
            box=box.ROUNDED,
            padding=(0, 1),
        )
        console.print(snippet)
        console.print(f"  Score: {score_bar} [dim]{res.score:.4f}[/dim]\n")


@app.command()
def map(path: Path = typer.Argument(".")):
    """[bold cyan]Map[/bold cyan] the architectural overview of the repository (L0 zoom)."""
    from synapse.retriever.zoom_controller import ZoomController

    cpg = get_cpg(path)
    zoom = ZoomController(cpg)
    context = zoom.get_architecture_map()

    console.print()
    console.print(Rule("[bold cyan]Repository Architecture — L0[/bold cyan]", style="cyan"))
    console.print()

    tree = Tree("[bold]📦 Repository[/bold]", guide_style="dim blue")
    lines = context.content.split("\n")
    current_module = None
    module_tree = None

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        # Module headers like: ── auth/ (depends on: ...)
        if stripped.startswith("── ") or stripped.startswith("\u2500\u2500 "):
            module_name = stripped.replace("── ", "").replace("\u2500\u2500 ", "")
            module_tree = tree.add(f"[bold blue]📁 {module_name}[/bold blue]")
            current_module = module_name
        elif stripped.startswith("\u2502  ") or stripped.startswith("│  "):
            content = stripped.lstrip("\u2502 ").lstrip("│ ").strip()
            if module_tree:
                if content.startswith("\u251c\u2500") or content.startswith("├─"):
                    module_tree.add(f"[green]{content}[/green]")
                elif content.startswith("\u2514\u2500") or content.startswith("└─"):
                    module_tree.add(f"[green]{content}[/green]")
                else:
                    module_tree.add(f"[dim]{content}[/dim]")
            else:
                tree.add(f"[green]{content}[/green]")
        else:
            tree.add(f"[dim]{stripped}[/dim]")

    console.print(tree)
    console.print()
    console.print(f"  [dim]Token cost: ~{context.token_count} tokens[/dim]\n")


@app.command()
def outline(file_path: str, path: Path = typer.Argument(".")):
    """[bold cyan]Outline[/bold cyan] — show the skeleton of a file (L1 zoom)."""
    from synapse.retriever.zoom_controller import ZoomController

    cpg = get_cpg(path)
    zoom = ZoomController(cpg)
    context = zoom.get_module_skeleton(file_path)

    # Parse skeleton into a tree
    tree = Tree(f"[bold cyan]📄 {file_path}[/bold cyan] — L1 Skeleton", guide_style="dim blue")
    for line in context.content.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("\u251c\u2500") or stripped.startswith("├─"):
            tree.add(f"[green]{stripped}[/green]")
        elif stripped.startswith("\u2514\u2500") or stripped.startswith("└─"):
            tree.add(f"[green]{stripped}[/green]")
        elif stripped.startswith("\u2502") or stripped.startswith("│"):
            tree.add(f"[dim]{stripped}[/dim]")
        else:
            tree.add(f"[white]{stripped}[/white]")

    console.print()
    console.print(tree)
    console.print(f"\n  [dim]Token cost: ~{context.token_count} tokens[/dim]\n")


@app.command()
def inspect(symbol: str, path: Path = typer.Argument("."), level: int = 2):
    """[bold cyan]Inspect[/bold cyan] a symbol at specified zoom level (L2-L3)."""
    from synapse.retriever.zoom_controller import ZoomController

    cpg = get_cpg(path)
    zoom = ZoomController(cpg)

    level_names = {2: ("Interface Contract", "L2", "cyan"), 3: ("Implementation Body", "L3", "magenta")}
    name, tag, color = level_names.get(level, ("Full", f"L{level}", "white"))

    if level == 2:
        context = zoom.get_interface_contracts(symbol)
    else:
        context = zoom.get_implementation(symbol)

    panel = Panel(
        context.content,
        title=f"[bold {color}] {tag}: {symbol} — {name}[/bold {color}]",
        border_style=color,
        box=box.DOUBLE_EDGE,
        padding=(1, 2),
    )
    console.print()
    console.print(panel)
    console.print(f"\n  [dim]Token cost: ~{context.token_count} tokens[/dim]\n")


@app.command()
def callers(symbol: str, path: Path = typer.Argument(".")):
    """[bold cyan]Callers[/bold cyan] — show all callers of a function/method."""
    from synapse.graph.model import NodeKind

    cpg = get_cpg(path)
    caller_nodes = cpg.get_callers(symbol)

    if not caller_nodes:
        console.print(f"\n  [yellow]No callers found for '{symbol}'.[/yellow]\n")
        return

    tree = Tree(f"[bold cyan]📞 Callers of {symbol}[/bold cyan]", guide_style="dim blue")
    for c in caller_nodes:
        kind_color = {"FUNCTION": "green", "METHOD": "cyan", "CLASS": "red"}.get(
            c.kind.value if hasattr(c.kind, "value") else c.kind, "white"
        )
        file_short = Path(c.file_path).name if c.file_path else "?"
        tree.add(f"[{kind_color}]{c.name}[/{kind_color}] [dim]{file_short}:{c.start_line}[/dim]")

    console.print()
    console.print(tree)
    console.print(f"\n  [dim]{len(caller_nodes)} caller(s) found[/dim]\n")


@app.command()
def callees(symbol: str, path: Path = typer.Argument(".")):
    """[bold cyan]Callees[/bold cyan] — show all functions/methods called by a symbol."""
    cpg = get_cpg(path)
    callee_nodes = cpg.get_callees(symbol)

    if not callee_nodes:
        console.print(f"\n  [yellow]No callees found for '{symbol}'.[/yellow]\n")
        return

    tree = Tree(f"[bold cyan]📱 Callees of {symbol}[/bold cyan]", guide_style="dim blue")
    for c in callee_nodes:
        kind_color = {"FUNCTION": "green", "METHOD": "cyan", "CLASS": "red"}.get(
            c.kind.value if hasattr(c.kind, "value") else c.kind, "white"
        )
        file_short = Path(c.file_path).name if c.file_path else "?"
        tree.add(f"[{kind_color}]{c.name}[/{kind_color}] [dim]{file_short}:{c.start_line}[/dim]")

    console.print()
    console.print(tree)
    console.print(f"\n  [dim]{len(callee_nodes)} callee(s) found[/dim]\n")


@app.command()
def stats(path: Path = typer.Argument(".")):
    """[bold cyan]Stats[/bold cyan] — detailed statistics about the indexed repository."""
    from synapse.retriever.zoom_controller import ZoomController

    cpg = get_cpg(path)
    store = cpg.store
    zoom = ZoomController(cpg)

    files_count = len(store.get_nodes_by_kind(NodeKind.FILE))
    nodes_count = store.node_count
    edges_count = store.edge_count

    # Token summary via zoom levels
    arch_ctx = zoom.get_architecture_map()
    arch_tokens = arch_ctx.token_count

    # Node kind breakdown
    kind_counts = {}
    for kind in NodeKind:
        count = len(store.get_nodes_by_kind(kind))
        if count > 0:
            kind_counts[kind.value] = count

    # Edge kind breakdown
    edge_counts = {}
    from synapse.graph.model import EdgeKind
    all_nodes = store.get_nodes_by_kind(NodeKind.FILE) + store.get_nodes_by_kind(NodeKind.FUNCTION) + store.get_nodes_by_kind(NodeKind.CLASS) + store.get_nodes_by_kind(NodeKind.METHOD)
    for node in all_nodes:
        for edge in store.get_edges(source_id=node.id):
            ek = edge.kind.value
            edge_counts[ek] = edge_counts.get(ek, 0) + 1

    # Build dashboard
    console.print()
    console.print(Rule("[bold cyan]Repository Dashboard[/bold cyan]", style="cyan"))
    console.print()

    # Main stats panel
    main_table = Table(box=box.SIMPLE_HEAVY, border_style="cyan", show_header=False)
    main_table.add_column("Metric", style="bold white", width=22)
    main_table.add_column("Value", style="bold cyan", justify="right", width=12)
    main_table.add_column("Visual", width=30)
    max_metric = max(files_count, nodes_count, edges_count, 1)
    main_table.add_row("📁 Files", str(files_count), _bar(files_count, max_metric, 25, "blue"))
    main_table.add_row("🔵 Nodes", str(nodes_count), _bar(nodes_count, max_metric, 25, "green"))
    main_table.add_row("🔗 Edges", str(edges_count), _bar(edges_count, max_metric, 25, "magenta"))
    main_table.add_row("📊 Arch Tokens", f"~{arch_tokens}", _token_bar(arch_tokens, max(arch_tokens * 3, 1)))

    console.print(Panel(main_table, title="[bold]Overview[/bold]", border_style="cyan", box=box.ROUNDED))

    # Node types panel
    if kind_counts:
        kind_table = Table(box=box.SIMPLE, border_style="dim", show_header=True)
        kind_table.add_column("Type", style="bold")
        kind_table.add_column("Count", justify="right")
        kind_table.add_column("", width=20)
        max_kind = max(kind_counts.values())
        for kind_name, count in sorted(kind_counts.items(), key=lambda x: -x[1]):
            color = {"FILE": "blue", "CLASS": "red", "INTERFACE": "yellow", "FUNCTION": "green", "METHOD": "cyan"}.get(kind_name, "dim")
            icon = {"FILE": "📄", "CLASS": "🏗️", "INTERFACE": "📋", "FUNCTION": "⚡", "METHOD": "🔧"}.get(kind_name, "•")
            kind_table.add_row(f"[{color}]{icon} {kind_name}[/{color}]", str(count), _bar(count, max_kind, 18, color))
        console.print(Panel(kind_table, title="[bold]Node Types[/bold]", border_style="blue", box=box.ROUNDED))

    # Edge types panel
    if edge_counts:
        edge_table = Table(box=box.SIMPLE, border_style="dim", show_header=True)
        edge_table.add_column("Type", style="bold")
        edge_table.add_column("Count", justify="right")
        edge_table.add_column("", width=20)
        max_edge = max(edge_counts.values())
        for edge_name, count in sorted(edge_counts.items(), key=lambda x: -x[1]):
            color = {"CALLS": "cyan", "CONTAINS": "blue", "DECLARES": "green", "IMPORTS": "yellow", "INHERITS": "red"}.get(edge_name, "dim")
            arrow = {"CALLS": "→", "CONTAINS": "⊃", "DECLARES": "≡", "IMPORTS": "⇤", "INHERITS": "⊳"}.get(edge_name, "•")
            edge_table.add_row(f"[{color}]{arrow} {edge_name}[/{color}]", str(count), _bar(count, max_edge, 18, color))
        console.print(Panel(edge_table, title="[bold]Edge Types[/bold]", border_style="magenta", box=box.ROUNDED))

    console.print()


@app.command()
def expand(symbol: str, path: Path = typer.Argument("."), budget: int = 2048):
    """[bold cyan]Expand[/bold cyan] context around a symbol using Personalized PageRank."""
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
        console.print(f"\n  [red]Symbol '{symbol}' not found.[/red]\n")
        return

    expanded = expander.expand([target_node.id], token_budget=budget)

    table = Table(
        title=f"🎯 PPR Subgraph: {symbol} (~{expanded.total_tokens} tokens)",
        box=box.ROUNDED,
        border_style="green",
        title_style="bold green",
    )
    table.add_column("#", style="dim", width=3)
    table.add_column("Symbol", style="cyan", width=25)
    table.add_column("Kind", style="magenta", width=10)
    table.add_column("PPR Score", justify="right", width=10)
    table.add_column("Bar", width=20)
    table.add_column("Location", style="dim", width=30)

    max_score = max((s for _, s in expanded.expanded_nodes), default=1)
    for i, (node, score) in enumerate(expanded.expanded_nodes):
        kind_str = node.kind.value if hasattr(node.kind, "value") else node.kind
        kind_color = {"FUNCTION": "green", "METHOD": "cyan", "CLASS": "red", "FILE": "blue"}.get(kind_str, "white")
        bar = _bar(int(score * 100), int(max_score * 100), 18, "green" if score > 0.5 else "yellow" if score > 0.2 else "dim")
        table.add_row(
            str(i + 1),
            f"[{kind_color}]{node.name}[/{kind_color}]",
            f"[{kind_color}]{kind_str}[/{kind_color}]",
            f"{score:.4f}",
            bar,
            f"{Path(node.file_path).name if node.file_path else '?'}:{node.start_line or '?'}",
        )

    console.print()
    console.print(table)
    console.print()


@app.command()
def prompt(symbol: str, path: Path = typer.Argument("."), budget: int = 2048):
    """[bold cyan]Prompt[/bold cyan] — generate a graph-compressed prompt block for an LLM turn."""
    from synapse.retriever.prompt_compressor import PromptCompressor

    cpg = get_cpg(path)
    compressor = PromptCompressor(cpg)
    result = compressor.compress(focus_symbol_name=symbol, token_budget=budget)

    panel = Panel(
        result.text,
        title=f"[bold cyan]📎 Graph-Compressed Prompt (~{result.token_count} tokens)[/bold cyan]",
        border_style="cyan",
        box=box.DOUBLE_EDGE,
        padding=(1, 2),
    )
    console.print()
    console.print(panel)
    console.print()


@app.command()
def clusters(path: Path = typer.Argument(".")):
    """[bold cyan]Clusters[/bold cyan] — show functional domain clusters and topology."""
    from synapse.retriever.fingerprinter import CodebaseFingerprinter

    cpg = get_cpg(path)
    fingerprinter = CodebaseFingerprinter(cpg)
    cl_list = fingerprinter.get_topology_clusters()

    table = Table(
        title="🌐 Codebase Topology Clusters",
        box=box.ROUNDED,
        border_style="magenta",
        title_style="bold magenta",
    )
    table.add_column("ID", style="dim", width=4)
    table.add_column("Domain", style="bold green", width=20)
    table.add_column("Members", justify="right", width=8)
    table.add_column("Bar", width=15)
    table.add_column("Key Symbols", style="white", width=40)

    max_members = max((c.member_count for c in cl_list), default=1)
    for c in cl_list:
        bar = _bar(c.member_count, max_members, 12, "magenta")
        symbols = ", ".join(c.top_symbols[:4])
        if len(c.top_symbols) > 4:
            symbols += f" [+{len(c.top_symbols) - 4}]"
        table.add_row(str(c.cluster_id), f"[bold]{c.name}[/bold]", str(c.member_count), bar, f"[dim]{symbols}[/dim]")

    console.print()
    console.print(table)
    console.print()


@app.command()
def slice(
    target: str = typer.Argument(..., help="Target: file_path:line_number[:variable]"),
    path: Path = typer.Argument("."),
    direction: str = typer.Option("backward", help="Slice direction: backward or forward"),
):
    """[bold cyan]Slice[/bold cyan] — compute a program slice (L4 zoom) for a target point."""
    from synapse.retriever.program_slicer import ProgramSlicer

    cpg = get_cpg(path)
    slicer = ProgramSlicer(cpg)

    parts = target.split(":")
    if len(parts) < 2:
        console.print("\n  [red]Invalid target format. Use: file_path:line[:variable][/red]\n")
        raise typer.Exit(code=1)

    file_path = parts[0]
    try:
        line = int(parts[1])
    except ValueError:
        console.print(f"\n  [red]Invalid line number: {parts[1]}[/red]\n")
        raise typer.Exit(code=1)

    variable = parts[2] if len(parts) > 2 else None

    if direction == "forward":
        result = slicer.forward_slice(file_path, line, variable)
    else:
        result = slicer.backward_slice(file_path, line, variable)

    if not result.slice_lines:
        console.print(f"\n  [yellow]No slice found for {target}.[/yellow]\n")
        return

    # Build a rich slice display
    table = Table(
        title=f"🔪 Program Slice ({result.slice_type}) — {len(result.slice_lines)} lines",
        box=box.ROUNDED,
        border_style="red",
        title_style="bold red",
    )
    table.add_column("Line", style="dim", width=6, justify="right")
    table.add_column("File", style="cyan", width=20)
    table.add_column("Code", style="white")

    for fpath, lnum, text in result.slice_lines:
        file_short = Path(fpath).name if fpath else "?"
        table.add_row(str(lnum), file_short, text.rstrip())

    console.print()
    console.print(table)
    console.print(f"\n  [dim]Token cost: ~{result.token_count} tokens[/dim]\n")


@app.command()
def impact(
    files: list[str] = typer.Argument(..., help="Changed files to analyze"),
    path: Path = typer.Argument("."),
):
    """[bold cyan]Impact[/bold cyan] — analyze impact of changes across the codebase."""
    from synapse.retriever.program_slicer import ProgramSlicer

    cpg = get_cpg(path)
    slicer = ProgramSlicer(cpg)
    result = slicer.impact_analysis(files)

    panel = Panel(
        result.summary,
        title="[bold red]💥 Impact Analysis[/bold red]",
        border_style="red",
        box=box.DOUBLE_EDGE,
        padding=(1, 2),
    )
    console.print()
    console.print(panel)
    console.print(f"\n  [dim]Token cost: ~{result.token_count} tokens[/dim]\n")


@app.command()
def adaptive(
    query: str = typer.Argument(..., help="Natural language query"),
    symbol: str = typer.Option(None, help="Target symbol to focus on"),
    path: Path = typer.Argument("."),
    budget: int = typer.Option(None, help="Override token budget"),
):
    """[bold cyan]Adaptive[/bold cyan] — task-adaptive retrieval with auto-detected strategy."""
    from synapse.indexer.embedder import Embedder
    from synapse.retriever.hybrid_search import HybridSearch
    from synapse.retriever.task_adaptive import TaskAdaptiveRetriever

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

    # Header
    task_icons = {"EXPLORE": "🔭", "UNDERSTAND": "📖", "EDIT": "✏️", "DEBUG": "🐛", "REFACTOR": "♻️", "REVIEW": "🔍"}
    icon = task_icons.get(task_type.value, "•")

    console.print()
    console.print(Rule(f"[bold cyan]{icon} Task-Adaptive Retrieval[/bold cyan]", style="cyan"))
    console.print()
    console.print(f"  [bold]Detected:[/bold] [cyan]{task_type.value}[/cyan]")
    console.print(f"  [dim]Strategy: {strategy.description} | Budget: {strategy.token_budget} tokens[/dim]")
    console.print()

    for ctx in contexts:
        level_name = {
            ZoomLevel.ARCHITECTURE: "L0 Architecture",
            ZoomLevel.SKELETON: "L1 Skeleton",
            ZoomLevel.INTERFACE: "L2 Interface",
            ZoomLevel.IMPLEMENTATION: "L3 Implementation",
            ZoomLevel.SLICE: "L4 Program Slice",
        }.get(ctx.zoom_level, f"L{ctx.zoom_level}")
        level_color = {0: "blue", 1: "green", 2: "cyan", 3: "magenta", 4: "red"}.get(
            ctx.zoom_level.value if hasattr(ctx.zoom_level, "value") else ctx.zoom_level, "white"
        )

        panel = Panel(
            ctx.content,
            title=f"[{level_color}]{level_name} (~{ctx.token_count} tokens)[/{level_color}]",
            border_style=level_color,
            box=box.ROUNDED,
            padding=(0, 1),
        )
        console.print(panel)

    console.print()
    console.print(f"  [bold green]Total: ~{total_tokens} tokens[/bold green]")
    console.print()


@app.command()
def viz(
    path: Path = typer.Argument(".", help="Repository path"),
    port: int = typer.Option(8765, help="Server port"),
    no_browser: bool = typer.Option(False, "--no-browser", help="Don't open browser automatically"),
):
    """[bold cyan]Viz[/bold cyan] — launch the 3D graph visualization in your browser."""
    from synapse.viz.server import start_server

    cpg = get_cpg(path)
    start_server(cpg, port=port, open_browser=not no_browser)


@app.command(name="info")
def info_cmd(path: Path = typer.Argument(".")):
    """[bold cyan]Info[/bold cyan] — show detailed project information."""
    cpg = get_cpg(path)
    store = cpg.store

    console.print()
    console.print(BANNER)

    # System info
    files = store.get_nodes_by_kind(NodeKind.FILE)
    classes = store.get_nodes_by_kind(NodeKind.CLASS)
    functions = store.get_nodes_by_kind(NodeKind.FUNCTION)
    methods = store.get_nodes_by_kind(NodeKind.METHOD)

    info_table = Table(box=None, show_header=False, padding=(0, 2))
    info_table.add_column("Key", style="bold cyan", width=18)
    info_table.add_column("Value", style="white")
    info_table.add_row("Project", str(path.resolve()))
    info_table.add_row("DB", str(path.resolve() / ".synapse" / "graph.db"))
    info_table.add_row("Files", f"{len(files)} indexed")
    info_table.add_row("Classes", str(len(classes)))
    info_table.add_row("Functions", str(len(functions)))
    info_table.add_row("Methods", str(len(methods)))
    info_table.add_row("Total Nodes", str(store.node_count))
    info_table.add_row("Total Edges", str(store.edge_count))

    console.print(Panel(info_table, title="[bold]Project Info[/bold]", border_style="cyan", box=box.ROUNDED))

    # Token savings estimate
    total_nodes = len(classes) + len(functions) + len(methods)
    full_tokens = sum(n.metadata.get("token_count_full", 0) for n in classes + functions + methods)
    skeleton_tokens = sum(n.metadata.get("token_count_skeleton", 0) for n in classes + functions + methods)

    if full_tokens > 0:
        savings = int((1 - skeleton_tokens / full_tokens) * 100)
        savings_table = Table(box=None, show_header=False)
        savings_table.add_column("KPI", style="bold", width=20)
        savings_table.add_column("Value", style="bold", width=15)
        savings_table.add_column("Bar", width=25)
        savings_table.add_row("Full implementation", f"{full_tokens:,} tok", _token_bar(full_tokens, full_tokens))
        savings_table.add_row("Skeleton only", f"{skeleton_tokens:,} tok", _token_bar(skeleton_tokens, full_tokens))
        savings_table.add_row("Token savings", f"[green]{savings}%[/green]", _bar(savings, 100, 22, "green"))
        console.print(Panel(savings_table, title="[bold]Token Efficiency[/bold]", border_style="green", box=box.ROUNDED))

    # Top 5 largest symbols
    all_syms = [(n, n.metadata.get("token_count_full", 0)) for n in classes + functions + methods]
    all_syms.sort(key=lambda x: -x[1])
    if all_syms:
        top_table = Table(box=box.SIMPLE, border_style="dim")
        top_table.add_column("#", style="dim", width=3)
        top_table.add_column("Symbol", style="cyan", width=25)
        top_table.add_column("Type", style="magenta", width=10)
        top_table.add_column("Tokens", justify="right", width=10)
        top_table.add_column("Bar", width=20)
        top_table.add_column("File", style="dim", width=20)
        for i, (n, tok) in enumerate(all_syms[:5]):
            kind_str = n.kind.value if hasattr(n.kind, "value") else n.kind
            color = {"FUNCTION": "green", "METHOD": "cyan", "CLASS": "red"}.get(kind_str, "white")
            top_table.add_row(
                str(i + 1),
                f"[{color}]{n.name}[/{color}]",
                f"[{color}]{kind_str}[/{color}]",
                f"{tok:,}",
                _bar(tok, all_syms[0][1], 18, color),
                Path(n.file_path).name if n.file_path else "?",
            )
        console.print(Panel(top_table, title="[bold]Top 5 Largest Symbols[/bold]", border_style="yellow", box=box.ROUNDED))

    console.print()


if __name__ == "__main__":
    app()
