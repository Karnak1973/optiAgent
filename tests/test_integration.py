from pathlib import Path
import pytest
from typer.testing import CliRunner

from synapse.cli.main import app
from synapse.graph.model import NodeKind, SymbolKind, ZoomLevel
from synapse.indexer.embedder import CodeTokenizer, Embedder
from synapse.indexer.graph_builder import GraphBuilder
from synapse.retriever.budget_allocator import TokenBudgetAllocator
from synapse.retriever.hybrid_search import HybridSearch
from synapse.retriever.zoom_controller import ZoomController

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "sample_project"


class TestFullPipeline:
    def test_graph_builder_on_sample_project(self, tmp_path):
        db_path = tmp_path / "test_synapse.db"
        builder = GraphBuilder(root=FIXTURES_DIR, db_path=db_path)
        cpg = builder.build()

        assert cpg.store.node_count > 0
        assert cpg.store.edge_count > 0

        # Check files indexed
        file_nodes = cpg.store.get_nodes_by_kind(NodeKind.FILE)
        file_names = [f.name for f in file_nodes]
        assert any("service.py" in f for f in file_names)
        assert any("jwt_handler.py" in f for f in file_names)
        assert any("connection.py" in f for f in file_names)

        # Check functions and classes
        class_nodes = cpg.store.get_nodes_by_kind(NodeKind.CLASS)
        class_names = [c.name for c in class_nodes]
        assert "AuthService" in class_names
        assert "JWTHandler" in class_names
        assert "Database" in class_names

        # Check methods
        method_nodes = cpg.store.get_nodes_by_kind(NodeKind.METHOD)
        method_names = [m.name for m in method_nodes]
        assert "login" in method_names
        assert "create_token" in method_names

    def test_zoom_controller(self, tmp_path):
        db_path = tmp_path / "test_zoom.db"
        builder = GraphBuilder(root=FIXTURES_DIR, db_path=db_path)
        cpg = builder.build()
        zoom = ZoomController(cpg)

        # L0 Architecture
        l0 = zoom.get_architecture_map()
        assert l0.zoom_level == ZoomLevel.ARCHITECTURE
        assert l0.token_count > 0
        assert "auth" in l0.content or "db" in l0.content

        # L1 Skeleton
        l1 = zoom.get_module_skeleton("service.py")
        assert l1.zoom_level == ZoomLevel.SKELETON
        assert "AuthService" in l1.content
        assert "def login" in l1.content

        # L2 Interface Contract
        l2 = zoom.get_interface_contracts("AuthService")
        assert l2.zoom_level == ZoomLevel.INTERFACE
        assert "AuthService" in l2.content

        # L3 Implementation
        l3 = zoom.get_implementation("login")
        assert l3.zoom_level == ZoomLevel.IMPLEMENTATION
        assert "def login" in l3.content
        assert "password" in l3.content

    def test_token_budget_allocator(self):
        allocator = TokenBudgetAllocator()
        comp_simple = allocator.estimate_complexity("find where user login is defined")
        comp_complex = allocator.estimate_complexity("refactor auth flow and migrate sessions across database")

        assert comp_simple < comp_complex

        alloc_simple = allocator.allocate(total_budget=2048, query_complexity=comp_simple)
        assert alloc_simple.total_budget == 2048
        assert alloc_simple.target_skeletons > 0
        assert alloc_simple.target_bodies > 0

    def test_code_tokenizer(self):
        tokenizer = CodeTokenizer()
        tokens = tokenizer.tokenize("def verify_jwt_token(userAuthId: str) -> None:")
        assert "verify" in tokens
        assert "jwt" in tokens
        assert "token" in tokens
        assert "user" in tokens
        assert "auth" in tokens
        assert "id" in tokens

    def test_hybrid_search(self, tmp_path):
        db_path = tmp_path / "test_search.db"
        builder = GraphBuilder(root=FIXTURES_DIR, db_path=db_path)
        cpg = builder.build()

        embedder = Embedder()
        searcher = HybridSearch(cpg.store, embedder)
        searcher.build_index()

        results = searcher.search("login user authentication", top_k=5)
        assert len(results) > 0
        top_names = [r.node.name for r in results]
        assert any(name in ["login", "AuthService", "User", "Session"] for name in top_names)

    def test_cli_commands(self, tmp_path):
        runner = CliRunner()

        # Run index command
        result = runner.invoke(app, ["index", str(FIXTURES_DIR)])
        assert result.exit_code == 0
        assert "Indexed" in result.stdout

        # Run map command
        result_map = runner.invoke(app, ["map", str(FIXTURES_DIR)])
        assert result_map.exit_code == 0
        assert "Architecture" in result_map.stdout

        # Run outline command
        result_outline = runner.invoke(app, ["outline", "service.py", str(FIXTURES_DIR)])
        assert result_outline.exit_code == 0
        assert "AuthService" in result_outline.stdout

        # Run inspect command
        result_inspect = runner.invoke(app, ["inspect", "AuthService", str(FIXTURES_DIR), "--level", "2"])
        assert result_inspect.exit_code == 0

        # Run stats command
        result_stats = runner.invoke(app, ["stats", str(FIXTURES_DIR)])
        assert result_stats.exit_code == 0
        assert "Total Nodes" in result_stats.stdout
