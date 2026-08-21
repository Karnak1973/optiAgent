"""Tests for Program Slicer, Task-Adaptive Retrieval, and new Phase 3 features."""

import pytest
from pathlib import Path

from synapse.graph.cpg import CodePropertyGraph
from synapse.graph.model import NodeKind, ZoomLevel
from synapse.graph.store import GraphStore
from synapse.indexer.graph_builder import GraphBuilder
from synapse.retriever.program_slicer import ProgramSlicer, ProgramSlice, ImpactAnalysis
from synapse.retriever.task_adaptive import TaskAdaptiveRetriever, TaskType
from synapse.retriever.budget_allocator import TokenBudgetAllocator
from synapse.retriever.zoom_controller import ZoomController
from synapse.indexer.parser import ASTParser


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "sample_project"
DB_PATH = FIXTURE_DIR / ".synapse" / "graph.db"


@pytest.fixture(scope="module")
def cpg():
    builder = GraphBuilder(root=FIXTURE_DIR, db_path=DB_PATH)
    return builder.build()


class TestProgramSlicer:
    def test_backward_slice_returns_lines(self, cpg):
        slicer = ProgramSlicer(cpg)
        result = slicer.backward_slice("auth/service.py", 50)
        assert isinstance(result, ProgramSlice)
        assert result.slice_type == "backward"
        assert result.target_file == "auth/service.py"
        assert result.target_line == 50

    def test_forward_slice_returns_lines(self, cpg):
        slicer = ProgramSlicer(cpg)
        result = slicer.forward_slice("auth/service.py", 50)
        assert isinstance(result, ProgramSlice)
        assert result.slice_type == "forward"

    def test_impact_analysis_returns_results(self, cpg):
        slicer = ProgramSlicer(cpg)
        result = slicer.impact_analysis(["auth/service.py"])
        assert isinstance(result, ImpactAnalysis)
        assert "auth/service.py" in result.changed_files
        assert isinstance(result.impacted_functions, list)
        assert isinstance(result.summary, str)
        assert result.token_count > 0

    def test_impact_analysis_with_ranges(self, cpg):
        slicer = ProgramSlicer(cpg)
        result = slicer.impact_analysis(["auth/service.py"], changed_ranges=[(10, 30)])
        assert isinstance(result, ImpactAnalysis)

    def test_slice_nonexistent_file(self, cpg):
        slicer = ProgramSlicer(cpg)
        result = slicer.backward_slice("nonexistent.py", 1)
        assert result.slice_lines == []
        assert result.token_count == 0


class TestTaskAdaptive:
    def test_classify_debug_task(self, cpg):
        from synapse.retriever.hybrid_search import HybridSearch
        from synapse.indexer.embedder import Embedder
        embedder = Embedder()
        searcher = HybridSearch(cpg.store, embedder)
        retriever = TaskAdaptiveRetriever(cpg, searcher)
        assert retriever.classify_task("debug the login error crash") == TaskType.DEBUG

    def test_classify_explore_task(self, cpg):
        from synapse.retriever.hybrid_search import HybridSearch
        from synapse.indexer.embedder import Embedder
        embedder = Embedder()
        searcher = HybridSearch(cpg.store, embedder)
        retriever = TaskAdaptiveRetriever(cpg, searcher)
        assert retriever.classify_task("explore the project structure") == TaskType.EXPLORE

    def test_classify_edit_task(self, cpg):
        from synapse.retriever.hybrid_search import HybridSearch
        from synapse.indexer.embedder import Embedder
        embedder = Embedder()
        searcher = HybridSearch(cpg.store, embedder)
        retriever = TaskAdaptiveRetriever(cpg, searcher)
        assert retriever.classify_task("edit the login function") == TaskType.EDIT

    def test_classify_refactor_task(self, cpg):
        from synapse.retriever.hybrid_search import HybridSearch
        from synapse.indexer.embedder import Embedder
        embedder = Embedder()
        searcher = HybridSearch(cpg.store, embedder)
        retriever = TaskAdaptiveRetriever(cpg, searcher)
        assert retriever.classify_task("refactor the auth module") == TaskType.REFACTOR

    def test_retrieve_returns_contexts(self, cpg):
        from synapse.retriever.hybrid_search import HybridSearch
        from synapse.indexer.embedder import Embedder
        embedder = Embedder()
        searcher = HybridSearch(cpg.store, embedder)
        searcher.build_index()
        retriever = TaskAdaptiveRetriever(cpg, searcher)
        result = retriever.retrieve("understand how login works", target_symbol="AuthService")
        assert "task_type" in result
        assert "contexts" in result
        assert "total_tokens" in result
        assert result["total_tokens"] >= 0


class TestBudgetAllocatorBinarySearch:
    def test_fit_nodes_empty(self):
        allocator = TokenBudgetAllocator()
        result = allocator.fit_nodes_to_budget([], 4096)
        assert result == []

    def test_fit_nodes_within_budget(self, cpg):
        allocator = TokenBudgetAllocator()
        nodes = []
        for kind in [NodeKind.FUNCTION, NodeKind.METHOD]:
            for n in cpg.store.get_nodes_by_kind(kind):
                nodes.append((n, 0.5))
        result = allocator.fit_nodes_to_budget(nodes, 10000)
        assert len(result) > 0

    def test_fit_nodes_respects_budget(self, cpg):
        allocator = TokenBudgetAllocator()
        nodes = []
        for kind in [NodeKind.FUNCTION, NodeKind.METHOD]:
            for n in cpg.store.get_nodes_by_kind(kind):
                nodes.append((n, 0.5))
        result = allocator.fit_nodes_to_budget(nodes, 100)
        total_tokens = sum(max(1, len(n.skeleton or n.name) // 4) for n in result)
        assert total_tokens <= 100


class TestZoomL4:
    def test_get_context_l4(self, cpg):
        zoom = ZoomController(cpg)
        # Find a function node to slice
        funcs = cpg.store.get_nodes_by_kind(NodeKind.FUNCTION)
        if funcs:
            func = funcs[0]
            ctx = zoom.get_context(
                f"{func.file_path}:{func.start_line}",
                ZoomLevel.SLICE,
            )
            assert ctx.zoom_level == ZoomLevel.SLICE
            assert isinstance(ctx.content, str)

    def test_get_program_slice_invalid_format(self, cpg):
        zoom = ZoomController(cpg)
        ctx = zoom.get_program_slice("invalid_format")
        assert "Invalid" in ctx.content

    def test_get_program_slice_invalid_line(self, cpg):
        zoom = ZoomController(cpg)
        ctx = zoom.get_program_slice("file.py:notanumber")
        assert "Invalid" in ctx.content


class TestJSParsers:
    def test_parse_javascript_function(self):
        parser = ASTParser()
        if "javascript" not in parser.parsers:
            pytest.skip("JS parser not available")
        code = """
function calculateTotal(items) {
    return items.reduce((sum, item) => sum + item.price, 0);
}
"""
        chunks = parser.parse_file("test.js", code, "javascript")
        assert len(chunks) >= 1
        assert chunks[0].name == "calculateTotal"
        assert chunks[0].language == "javascript"

    def test_parse_javascript_class(self):
        parser = ASTParser()
        if "javascript" not in parser.parsers:
            pytest.skip("JS parser not available")
        code = """
class UserService {
    constructor(db) {
        this.db = db;
    }

    findById(id) {
        return this.db.query(id);
    }
}
"""
        chunks = parser.parse_file("test.js", code, "javascript")
        assert len(chunks) >= 1
        names = [c.name for c in chunks]
        assert "UserService" in names

    def test_parse_typescript_interface(self):
        parser = ASTParser()
        if "typescript" not in parser.parsers:
            pytest.skip("TS parser not available")
        code = """
interface User {
    id: number;
    name: string;
}

function getUser(id: number): User {
    return { id, name: "test" };
}
"""
        chunks = parser.parse_file("test.ts", code, "typescript")
        assert len(chunks) >= 1
        names = [c.name for c in chunks]
        assert "User" in names or "getUser" in names

    def test_parse_javascript_arrow_function(self):
        parser = ASTParser()
        if "javascript" not in parser.parsers:
            pytest.skip("JS parser not available")
        code = """
const multiply = (a, b) => a * b;
"""
        chunks = parser.parse_file("test.js", code, "javascript")
        assert len(chunks) >= 1
        assert chunks[0].name == "multiply"
