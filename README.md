# Synapse

**Graph-based code intelligence engine for token-efficient AI agents.**

Synapse builds a **Code Property Graph (CPG)** from your repository and uses graph algorithms (Personalized PageRank, Program Slicing, Hierarchical Zoom) to extract the **minimum subgraph of maximum signal** for each agent query — consuming **up to 95-99% fewer tokens** than grep-based approaches.

## Why Synapse?

| | Grep+Read | Semble | **Synapse** |
|:---|:---|:---|:---|
| Tokens per query | 50k-200k | 500-2k | **200-800** |
| Cross-file context | Manual | Limited | **Multi-hop** |
| Code graph | None | AST only | **Full CPG** |
| Adaptive zoom | No | No | **L0-L4** |
| Program slicing | No | No | **PDG-based** |
| Dynamic budget | No | No | **Yes** |

## Requirements

- Python >= 3.11
- OS: Windows, macOS, Linux

## Installation

### From source (recommended)

```bash
git clone https://github.com/Karnak1973/optiAgent.git
cd optiAgent

# Create virtual environment
python -m venv .venv
# Windows
.\.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate

# Install in development mode
pip install -e ".[dev,mcp]"
```

### Using uv (faster)

```bash
git clone https://github.com/Karnak1973/optiAgent.git
cd optiAgent
uv sync
```

## Quick Start

### 1. Index your repository

```bash
synapse index .
```

This scans all files, parses the AST, builds the Code Property Graph, and stores it in `.synapse/graph.db`.

### 2. Search the codebase

```bash
synapse search "authentication flow" .
```

### 3. See the architectural map

```bash
synapse map .
```

### 4. Inspect a symbol

```bash
# Interface contract (L2) — signatures + docstrings
synapse inspect AuthService.login . --level 2

# Full implementation (L3) — complete body
synapse inspect AuthService.login . --level 3
```

## CLI Commands

### Indexing

| Command | Description |
|:---|:---|
| `synapse index <path>` | Index a repository and build the Code Property Graph |

### Search & Retrieval

| Command | Description |
|:---|:---|
| `synapse search <query>` | Hybrid BM25 + semantic search with graph-aware reranking |
| `synapse adaptive <query>` | Auto-detects task type and retrieves optimized context |

### Zoom Levels

| Command | Zoom | Description |
|:---|:---|:---|
| `synapse map` | L0 | Architectural map — module dependencies, exported symbols |
| `synapse outline <file>` | L1 | File skeleton — classes, functions, signatures |
| `synapse inspect <symbol> --level 2` | L2 | Interface contracts — signatures + callee interfaces |
| `synapse inspect <symbol> --level 3` | L3 | Implementation — full function body |

### Graph Analysis

| Command | Description |
|:---|:---|
| `synapse callers <symbol>` | Show all functions that call a given symbol |
| `synapse callees <symbol>` | Show all functions called by a symbol |
| `synapse expand <symbol>` | Context expansion via Personalized PageRank |
| `synapse prompt <symbol>` | Generate a graph-compressed prompt block |
| `synapse clusters` | Show functional domain clusters |

### Program Slicing & Impact

| Command | Description |
|:---|:---|
| `synapse slice <target>` | Program slice — only lines causally affecting a point |
| `synapse impact <files...>` | Analyze impact of changes across the codebase |

### Utilities

| Command | Description |
|:---|:---|
| `synapse stats` | Show statistics about the indexed repository |

## Program Slicing

Extract only the lines that causally affect a specific variable or statement. This can reduce a 500-line file to 15-30 relevant lines.

```bash
# Backward slice: what feeds into user_token at line 52?
synapse slice auth/service.py:52:user_token

# Forward slice: what is affected by this line?
synapse slice auth/service.py:52 --direction forward
```

## Impact Analysis

Before pushing a change, analyze what might break:

```bash
synapse impact auth/service.py auth/jwt_handler.py
```

Returns a list of impacted functions and files that need verification.

## Task-Adaptive Retrieval

Let Synapse auto-detect the task type and adjust the context:

```bash
# "explore" → L0-L1 architecture overview
synapse adaptive "show me the project structure"

# "understand" → L1-L2 skeletons + interfaces
synapse adaptive "how does login work" --symbol AuthService.login

# "edit" → L2-L3 full implementation bodies
synapse adaptive "fix the token refresh bug" --symbol refresh_token

# "debug" → L3-L4 program slices
synapse adaptive "debug the crash in login" --symbol AuthService.login

# "refactor" → L1-L3 cross-module impact
synapse adaptive "refactor the auth module"
```

## MCP Server (for AI Agents)

Synapse exposes an MCP server with 14 tools for AI agents like GitHub Copilot, Claude Code, Cursor, or Aider.

### GitHub Copilot (VS Code)

Synapse works natively with **GitHub Copilot Agent Mode** via MCP.

**Step 1: Install Synapse**

```bash
git clone https://github.com/Karnak1973/optiAgent.git
cd optiAgent
python -m venv .venv
# Windows
.\.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate
pip install -e ".[dev,mcp]"
```

**Step 2: Index your project**

```bash
synapse index .
```

**Step 3: Configure MCP in VS Code**

The `.vscode/mcp.json` is already included in the repo. It looks like this:

```json
{
  "servers": {
    "synapse": {
      "command": "${workspaceFolder}/.venv/Scripts/python.exe",
      "args": ["-m", "synapse.server"],
      "cwd": "${workspaceFolder}"
    }
  }
}
```

> **Note:** Adjust the `command` path for your OS:
> - **Windows:** `${workspaceFolder}/.venv/Scripts/python.exe`
> - **macOS/Linux:** `${workspaceFolder}/.venv/bin/python`

**Step 4: Use in Copilot Chat (Agent Mode)**

1. Open VS Code with your project
2. Toggle **Agent Mode** in the Copilot Chat panel (click the icon next to the chat input)
3. Copilot will auto-discover the Synapse MCP server
4. Ask questions — Copilot will automatically use Synapse tools:

```
@copilot Show me the architecture of this project
@copilot How does the login flow work?
@copilot What functions call AuthService.login?
@copilot What would break if I change auth/service.py?
```

**Available tools in Copilot:**

| Tool | What Copilot uses it for |
|:---|:---|
| `synapse_search` | Finding relevant code snippets |
| `synapse_map` | Understanding project architecture |
| `synapse_outline` | Reading file structures |
| `synapse_inspect` | Reading function implementations |
| `synapse_callers` / `synapse_callees` | Tracing call chains |
| `synapse_slice` | Debugging specific variables |
| `synapse_impact` | Analyzing change impact |
| `synapse_adaptive` | Auto-adjusting context depth |

### Claude Desktop / Cursor / Other MCP Clients

Add to your MCP client configuration:

```json
{
  "mcpServers": {
    "synapse": {
      "command": "python",
      "args": ["-m", "synapse.server"],
      "env": {}
    }
  }
}
```

### All MCP Tools

| Tool | Description |
|:---|:---|
| `synapse_search` | Hybrid search with graph-aware reranking |
| `synapse_map` | L0 architectural map (~100-300 tokens) |
| `synapse_outline` | L1 file skeleton (~300-800 tokens) |
| `synapse_inspect` | L2/L3 symbol inspection |
| `synapse_callers` | Find all callers of a function |
| `synapse_callees` | Find all callees of a function |
| `synapse_fingerprint` | Ultra-compact symbol fingerprint (~20 tokens) |
| `synapse_expand` | PPR-based context expansion |
| `synapse_prompt` | Graph-compressed prompt block |
| `synapse_diff_context` | Incremental context delta |
| `synapse_clusters` | Topology clusters |
| `synapse_slice` | Program slice (L4) |
| `synapse_impact` | Change impact analysis |
| `synapse_adaptive` | Task-adaptive retrieval |

## Python API

```python
from synapse.graph.store import GraphStore
from synapse.graph.cpg import CodePropertyGraph
from synapse.indexer.graph_builder import GraphBuilder
from synapse.retriever.zoom_controller import ZoomController
from synapse.retriever.hybrid_search import HybridSearch
from synapse.indexer.embedder import Embedder
from pathlib import Path

# Build the graph
builder = GraphBuilder(root=Path("./my-project"))
cpg = builder.build()

# Zoom L0: Architecture map
zoom = ZoomController(cpg)
ctx = zoom.get_architecture_map()
print(ctx.content)

# Zoom L3: Full implementation
ctx = zoom.get_implementation("AuthService.login")
print(ctx.content)

# Program slice
from synapse.retriever.program_slicer import ProgramSlicer
slicer = ProgramSlicer(cpg)
slice_result = slicer.backward_slice("auth/service.py", 52, "user_token")
for file, line, text in slice_result.slice_lines:
    print(f"  {line}: {text}")

# Impact analysis
impact = slicer.impact_analysis(["auth/service.py"])
print(impact.summary)

# Task-adaptive retrieval
from synapse.retriever.task_adaptive import TaskAdaptiveRetriever
embedder = Embedder()
searcher = HybridSearch(cpg.store, embedder)
searcher.build_index()
retriever = TaskAdaptiveRetriever(cpg, searcher)
result = retriever.retrieve("fix the login bug", target_symbol="AuthService.login")
```

## Architecture

```
synapse/
├── graph/          # Data model + SQLite/rustworkx storage
│   ├── model.py    # Node/Edge dataclasses, enums
│   ├── store.py    # SQLite + rustworkx dual storage
│   └── cpg.py      # Code Property Graph operations
│
├── indexer/        # Build pipeline
│   ├── scanner.py      # File scanner + change detection
│   ├── parser.py       # Tree-sitter AST parser (Python, JS, TS)
│   ├── scope_resolver.py  # Import + reference resolution
│   ├── graph_builder.py   # CPG construction
│   └── embedder.py    # BM25 + Model2Vec embeddings
│
├── retriever/      # Search & context optimization
│   ├── hybrid_search.py       # BM25 + semantic + RRF
│   ├── graph_expander.py      # Personalized PageRank
│   ├── zoom_controller.py     # L0-L4 zoom levels
│   ├── budget_allocator.py    # Dynamic token budget
│   ├── program_slicer.py      # Backward/forward slicing
│   ├── task_adaptive.py       # Auto task detection
│   ├── fingerprinter.py       # Centrality + clustering
│   ├── diff_aware.py          # Incremental context
│   └── prompt_compressor.py   # Graph-compressed prompts
│
├── server/         # MCP server
│   └── mcp_server.py   # 14 MCP tools
│
└── cli/            # CLI interface
    └── main.py     # 12 Typer commands
```

## Supported Languages

| Language | Parser Status |
|:---|:---|
| Python | Full support (classes, functions, methods, docstrings) |
| JavaScript | Full support (classes, functions, arrow functions, JSDoc) |
| TypeScript | Full support (classes, functions, interfaces, arrow functions) |

## Running Tests

```bash
# Run all tests
pytest tests/ -v

# Run specific test file
pytest tests/test_phase3.py -v

# Run with coverage
pytest tests/ --cov=synapse --cov-report=term-missing
```

## Development

```bash
# Install dev dependencies
pip install -e ".[dev,mcp]"

# Lint
ruff check synapse/

# Format
ruff format synapse/
```

## License

MIT
