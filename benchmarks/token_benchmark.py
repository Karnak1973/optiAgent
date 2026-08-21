"""Benchmark comparing token consumption between Grep+Read, Semble-style, and Synapse."""

from pathlib import Path
from rich.console import Console
from rich.table import Table

from synapse.indexer.graph_builder import GraphBuilder
from synapse.retriever.prompt_compressor import PromptCompressor
from synapse.retriever.zoom_controller import ZoomController

console = Console()
REPO_ROOT = Path(__file__).parent.parent


def run_benchmark():
    db_path = REPO_ROOT / ".synapse" / "benchmark.db"
    builder = GraphBuilder(root=REPO_ROOT, db_path=db_path)
    cpg = builder.build()
    compressor = PromptCompressor(cpg)
    zoom = ZoomController(cpg)

    # 1. Baseline Grep+Read: reading all project files fully
    total_raw_chars = 0
    file_count = 0
    for f in REPO_ROOT.rglob("*.py"):
        if ".venv" in str(f) or "__pycache__" in str(f):
            continue
        try:
            total_raw_chars += len(f.read_text(encoding="utf-8", errors="ignore"))
            file_count += 1
        except Exception:
            pass

    grep_read_tokens = max(1, total_raw_chars // 4)

    # 2. Semble-style: Top-5 10-line snippets
    semble_tokens = 5 * 10 * 8  # ~5 snippets * 10 lines * 8 tokens/line = ~400 tokens

    # 3. Synapse Zoom L0 (Architecture)
    l0 = zoom.get_architecture_map()
    synapse_l0_tokens = l0.token_count

    # 4. Synapse Graph-Compressed Prompt for a key symbol
    synapse_prompt = compressor.compress("GraphBuilder", token_budget=1500)
    synapse_prompt_tokens = synapse_prompt.token_count

    # 5. Synapse Interface L2
    l2 = zoom.get_interface_contracts("GraphBuilder")
    synapse_l2_tokens = l2.token_count

    table = Table(title="Token Consumption Benchmark: Codebase Exploration", border_style="cyan")
    table.add_column("Approach", style="bold cyan")
    table.add_column("Strategy", style="magenta")
    table.add_column("Tokens Consumed", style="green")
    table.add_column("Token Reduction vs Baseline", style="bold yellow")

    table.add_row(
        "Grep + Read Files",
        "Dump full files into prompt context",
        f"{grep_read_tokens:,}",
        "0.0% (Baseline)",
    )
    table.add_row(
        "Semble Style",
        "Flat 10-line AST chunks",
        f"{semble_tokens:,}",
        f"{((grep_read_tokens - semble_tokens) / grep_read_tokens) * 100:.1f}%",
    )
    table.add_row(
        "Synapse L0 Architecture Map",
        "DAG dependency tree + exports",
        f"{synapse_l0_tokens:,}",
        f"{((grep_read_tokens - synapse_l0_tokens) / grep_read_tokens) * 100:.1f}%",
    )
    table.add_row(
        "Synapse L2 Interface Contract",
        "Symbol signature + callees",
        f"{synapse_l2_tokens:,}",
        f"{((grep_read_tokens - synapse_l2_tokens) / grep_read_tokens) * 100:.1f}%",
    )
    table.add_row(
        "Synapse Graph-Compressed Prompt",
        "PPR Subgraph (Focus + Callees + Schemas)",
        f"{synapse_prompt_tokens:,}",
        f"{((grep_read_tokens - synapse_prompt_tokens) / grep_read_tokens) * 100:.1f}%",
    )

    console.print(table)


if __name__ == "__main__":
    run_benchmark()
