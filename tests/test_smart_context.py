from pathlib import Path
import pytest

from synapse.graph.model import NodeKind
from synapse.indexer.graph_builder import GraphBuilder
from synapse.retriever.diff_aware import DiffAwareContextEngine
from synapse.retriever.fingerprinter import CodebaseFingerprinter
from synapse.retriever.graph_expander import GraphExpander
from synapse.retriever.prompt_compressor import PromptCompressor
from synapse.server.mcp_server import (
    synapse_clusters,
    synapse_diff_context,
    synapse_expand,
    synapse_prompt,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "sample_project"


@pytest.fixture
def sample_cpg(tmp_path):
    db_path = tmp_path / "smart_test.db"
    builder = GraphBuilder(root=FIXTURES_DIR, db_path=db_path)
    return builder.build()


def test_personalized_pagerank_expansion(sample_cpg):
    expander = GraphExpander(sample_cpg)

    # Find AuthService node
    auth_nodes = [n for n in sample_cpg.store.get_nodes_by_kind(NodeKind.CLASS) if n.name == "AuthService"]
    assert len(auth_nodes) > 0
    auth_id = auth_nodes[0].id

    # Expand around AuthService
    expanded = expander.expand([auth_id], token_budget=1024, alpha=0.85)
    assert len(expanded.expanded_nodes) > 0
    assert expanded.total_tokens <= 1024
    assert auth_id in expanded.included_node_ids

    # Top scored node should be either the seed or directly connected method
    top_node, top_score = expanded.expanded_nodes[0]
    assert top_score > 0.0


def test_ego_subgraph(sample_cpg):
    expander = GraphExpander(sample_cpg)
    auth_nodes = [n for n in sample_cpg.store.get_nodes_by_kind(NodeKind.CLASS) if n.name == "AuthService"]
    auth_id = auth_nodes[0].id

    ego_nodes = expander.get_ego_subgraph(auth_id, hops=1)
    assert len(ego_nodes) >= 1
    ego_names = {n.name for n in ego_nodes}
    assert "AuthService" in ego_names


def test_prompt_compressor(sample_cpg):
    compressor = PromptCompressor(sample_cpg)
    result = compressor.compress(focus_symbol_name="login", token_budget=1500)

    assert result.focus_symbol == "login"
    assert result.token_count > 0
    assert result.token_count <= 1500
    assert "FOCUS: login" in result.text
    assert "def login" in result.text
    assert "CONNECTED INTERFACES" in result.text or "DATA TYPES" in result.text


def test_codebase_fingerprinter(sample_cpg):
    fingerprinter = CodebaseFingerprinter(sample_cpg)
    fingerprints = fingerprinter.compute_fingerprints()

    assert len(fingerprints) > 0
    for node_id, fp in fingerprints.items():
        assert fp.name
        assert 0.0 <= fp.centrality_percentile <= 1.0

    clusters = fingerprinter.get_topology_clusters()
    assert len(clusters) >= 2
    cluster_names = [c.name for c in clusters]
    assert any("auth" in name for name in cluster_names)
    assert any("db" in name for name in cluster_names)


def test_diff_aware_context_engine(sample_cpg):
    engine = DiffAwareContextEngine(sample_cpg)
    service_file = [f.name for f in sample_cpg.store.get_nodes_by_kind(NodeKind.FILE) if "service.py" in f.name][0]

    delta = engine.compute_delta_from_files([service_file])
    assert len(delta.modified_symbols) > 0
    assert any(s.name == "AuthService" for s in delta.modified_symbols)
    assert "Incremental Context Delta" in delta.summary_markdown


def test_phase2_mcp_tools():
    # Test expand tool
    expand_res = synapse_expand(symbol="AuthService", token_budget=1024, repo_path=str(FIXTURES_DIR))
    assert "Personalized PageRank" in expand_res

    # Test prompt tool
    prompt_res = synapse_prompt(symbol="AuthService", token_budget=1024, repo_path=str(FIXTURES_DIR))
    assert "FOCUS: AuthService" in prompt_res or "Codebase Context" in prompt_res

    # Test diff_context tool
    diff_res = synapse_diff_context(changed_files=["auth/service.py"], repo_path=str(FIXTURES_DIR))
    assert "Incremental Context Delta" in diff_res

    # Test clusters tool
    clusters_res = synapse_clusters(repo_path=str(FIXTURES_DIR))
    assert "Topology Clusters" in clusters_res
