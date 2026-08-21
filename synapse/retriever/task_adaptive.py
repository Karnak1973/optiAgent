"""Task-Adaptive Retrieval — automatically selects retrieval strategy based on query intent."""

from dataclasses import dataclass
from enum import StrEnum

from synapse.graph.cpg import CodePropertyGraph
from synapse.graph.model import NodeKind, ZoomLevel, ZoomedContext
from synapse.retriever.budget_allocator import TokenBudgetAllocator
from synapse.retriever.graph_expander import GraphExpander
from synapse.retriever.hybrid_search import HybridSearch
from synapse.retriever.zoom_controller import ZoomController


class TaskType(StrEnum):
    EXPLORE = "EXPLORE"
    UNDERSTAND = "UNDERSTAND"
    EDIT = "EDIT"
    DEBUG = "DEBUG"
    REFACTOR = "REFACTOR"
    REVIEW = "REVIEW"


@dataclass
class TaskStrategy:
    zoom_start: ZoomLevel
    zoom_end: ZoomLevel
    token_budget: int
    expansion_hops: int
    description: str


STRATEGIES: dict[TaskType, TaskStrategy] = {
    TaskType.EXPLORE: TaskStrategy(
        zoom_start=ZoomLevel.ARCHITECTURE,
        zoom_end=ZoomLevel.SKELETON,
        token_budget=1024,
        expansion_hops=0,
        description="Broad overview, no deep expansion",
    ),
    TaskType.UNDERSTAND: TaskStrategy(
        zoom_start=ZoomLevel.SKELETON,
        zoom_end=ZoomLevel.INTERFACE,
        token_budget=2048,
        expansion_hops=1,
        description="Skeletons + interface contracts",
    ),
    TaskType.EDIT: TaskStrategy(
        zoom_start=ZoomLevel.INTERFACE,
        zoom_end=ZoomLevel.IMPLEMENTATION,
        token_budget=4096,
        expansion_hops=1,
        description="Full implementation bodies",
    ),
    TaskType.DEBUG: TaskStrategy(
        zoom_start=ZoomLevel.IMPLEMENTATION,
        zoom_end=ZoomLevel.SLICE,
        token_budget=2048,
        expansion_hops=2,
        description="Program slices for surgical debugging",
    ),
    TaskType.REFACTOR: TaskStrategy(
        zoom_start=ZoomLevel.SKELETON,
        zoom_end=ZoomLevel.IMPLEMENTATION,
        token_budget=8192,
        expansion_hops=2,
        description="Cross-module impact analysis",
    ),
    TaskType.REVIEW: TaskStrategy(
        zoom_start=ZoomLevel.INTERFACE,
        zoom_end=ZoomLevel.SLICE,
        token_budget=4096,
        expansion_hops=1,
        description="Diff-focused with caller analysis",
    ),
}

# Keywords that hint at task type
_TASK_KEYWORDS: dict[TaskType, list[str]] = {
    TaskType.EXPLORE: ["explore", "overview", "map", "structure", "what does", "show me"],
    TaskType.UNDERSTAND: ["understand", "how does", "explain", "what is", "why", "read"],
    TaskType.EDIT: ["edit", "change", "modify", "update", "fix", "implement", "add"],
    TaskType.DEBUG: ["debug", "error", "bug", "crash", "trace", "stack", "exception", "fail"],
    TaskType.REFACTOR: ["refactor", "reorganize", "move", "extract", "split", "migrate", "rename"],
    TaskType.REVIEW: ["review", "diff", "change", "pr", "pull request", "commit"],
}


class TaskAdaptiveRetriever:
    """Automatically detects task type from query and adjusts retrieval strategy.

    Provides a single entry point that:
    1. Classifies the query intent
    2. Selects the appropriate zoom levels and budget
    3. Returns a multi-level context block optimized for the task
    """

    def __init__(self, cpg: CodePropertyGraph, searcher: HybridSearch | None = None):
        self.cpg = cpg
        self.store = cpg.store
        self.zoom = ZoomController(cpg)
        self.expander = GraphExpander(cpg)
        self.searcher = searcher
        self.budget_allocator = TokenBudgetAllocator()

    def classify_task(self, query: str) -> TaskType:
        """Classify the query into a task type using keyword matching."""
        query_lower = query.lower()
        scores: dict[TaskType, int] = {t: 0 for t in TaskType}

        for task_type, keywords in _TASK_KEYWORDS.items():
            for kw in keywords:
                if kw in query_lower:
                    scores[task_type] += 1

        best = max(scores, key=lambda t: scores[t])
        if scores[best] == 0:
            return TaskType.UNDERSTAND
        return best

    def retrieve(
        self,
        query: str,
        target_symbol: str | None = None,
        token_budget: int | None = None,
    ) -> dict:
        """Retrieve context adapted to the detected task type.

        Returns a dict with:
            - task_type: detected task type
            - strategy: the strategy used
            - contexts: list of ZoomedContext at different levels
            - total_tokens: total token count
        """
        task_type = self.classify_task(query)
        strategy = STRATEGIES[task_type]
        budget = token_budget or strategy.token_budget

        contexts: list[ZoomedContext] = []

        # If we have a target symbol, search for it
        if target_symbol and self.searcher:
            results = self.searcher.search(target_symbol, top_k=1)
            if results:
                target_symbol = results[0].node.name

        # Generate contexts at the required zoom levels
        if strategy.zoom_start <= ZoomLevel.ARCHITECTURE <= strategy.zoom_end:
            contexts.append(self.zoom.get_architecture_map(budget // 4))

        if strategy.zoom_start <= ZoomLevel.SKELETON <= strategy.zoom_end and target_symbol:
            # Find the file containing the symbol
            file_path = self._find_symbol_file(target_symbol)
            if file_path:
                contexts.append(self.zoom.get_module_skeleton(file_path, budget // 3))

        if strategy.zoom_start <= ZoomLevel.INTERFACE <= strategy.zoom_end and target_symbol:
            contexts.append(self.zoom.get_interface_contracts(target_symbol, budget // 3))

        if strategy.zoom_start <= ZoomLevel.IMPLEMENTATION <= strategy.zoom_end and target_symbol:
            contexts.append(self.zoom.get_implementation(target_symbol, budget // 2))

        if strategy.zoom_start <= ZoomLevel.SLICE <= strategy.zoom_end and target_symbol:
            # Try to get a program slice for the target
            file_path = self._find_symbol_file(target_symbol)
            if file_path:
                node = self._find_symbol_node(target_symbol)
                if node and node.start_line:
                    contexts.append(self.zoom.get_program_slice(
                        f"{file_path}:{node.start_line}",
                        budget // 3,
                    ))

        # Apply graph expansion if hops > 0
        if strategy.expansion_hops > 0 and target_symbol:
            node = self._find_symbol_node(target_symbol)
            if node:
                expanded = self.expander.expand([node.id], token_budget=budget // 4)
                if expanded.expanded_nodes:
                    lines = [f"### Graph Context ({len(expanded.expanded_nodes)} nodes, PPR-ranked)"]
                    for n, score in expanded.expanded_nodes:
                        if n.id != node.id:
                            sig = n.signature or n.skeleton or n.name
                            lines.append(f"- `{n.name}` [PPR:{score:.3f}] — {n.file_path}:{n.start_line}\n  {sig}")
                    contexts.append(ZoomedContext(
                        zoom_level=ZoomLevel.INTERFACE,
                        content="\n".join(lines),
                        token_count=max(1, sum(max(1, len(l) // 4) for l in lines)),
                        nodes_included=[n.id for n, _ in expanded.expanded_nodes],
                    ))

        total_tokens = sum(c.token_count for c in contexts)

        return {
            "task_type": task_type,
            "strategy": strategy,
            "contexts": contexts,
            "total_tokens": total_tokens,
        }

    def _find_symbol_file(self, symbol_name: str) -> str | None:
        for kind in [NodeKind.FUNCTION, NodeKind.CLASS, NodeKind.METHOD]:
            for n in self.store.get_nodes_by_kind(kind):
                if n.name == symbol_name:
                    return n.file_path
        return None

    def _find_symbol_node(self, symbol_name: str) -> NodeKind | None:
        for kind in [NodeKind.FUNCTION, NodeKind.CLASS, NodeKind.METHOD]:
            for n in self.store.get_nodes_by_kind(kind):
                if n.name == symbol_name:
                    return n
        return None
