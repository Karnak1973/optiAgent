from pathlib import Path
from synapse.server.mcp_server import (
    synapse_search,
    synapse_map,
    synapse_outline,
    synapse_inspect,
    synapse_callers,
    synapse_callees,
    synapse_fingerprint,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "sample_project"


def test_mcp_tools_direct_invocation():
    # Test synapse_map
    map_res = synapse_map(repo_path=str(FIXTURES_DIR))
    assert "auth" in map_res or "db" in map_res

    # Test synapse_search
    search_res = synapse_search(query="login session", repo_path=str(FIXTURES_DIR))
    assert "login" in search_res or "AuthService" in search_res

    # Test synapse_outline
    outline_res = synapse_outline(file_path="service.py", repo_path=str(FIXTURES_DIR))
    assert "AuthService" in outline_res

    # Test synapse_inspect
    inspect_res = synapse_inspect(symbol="AuthService", level=2, repo_path=str(FIXTURES_DIR))
    assert "AuthService" in inspect_res

    # Test synapse_fingerprint
    fp_res = synapse_fingerprint(symbol="AuthService", repo_path=str(FIXTURES_DIR))
    assert "AuthService" in fp_res

