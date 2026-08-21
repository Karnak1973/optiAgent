import pytest
from pathlib import Path
from synapse.graph.model import GraphNode, GraphEdge, NodeKind, EdgeKind, SymbolKind
from synapse.graph.store import GraphStore


class TestGraphStore:
    def setup_method(self, tmp_path_factory=None):
        import tempfile
        self.tmp_dir = Path(tempfile.mkdtemp())
        self.store = GraphStore(self.tmp_dir / "test.db")
    
    def test_add_and_get_node(self):
        node = GraphNode(
            id=0,  # Will be assigned by store
            kind=NodeKind.FUNCTION,
            name="test_func",
            file_path="test.py",
            start_line=1,
            end_line=5,
            signature="def test_func(x: int) -> bool",
        )
        node_id = self.store.add_node(node)
        retrieved = self.store.get_node(node_id)
        assert retrieved is not None
        assert retrieved.name == "test_func"
        assert retrieved.kind == NodeKind.FUNCTION
    
    def test_add_edge(self):
        n1_id = self.store.add_node(GraphNode(id=0, kind=NodeKind.FUNCTION, name="caller"))
        n2_id = self.store.add_node(GraphNode(id=0, kind=NodeKind.FUNCTION, name="callee"))
        edge = GraphEdge(source_id=n1_id, target_id=n2_id, kind=EdgeKind.CALLS)
        self.store.add_edge(edge)
        edges = self.store.get_edges(source_id=n1_id)
        assert len(edges) == 1
        assert edges[0].kind == EdgeKind.CALLS
    
    def test_get_neighbors(self):
        n1_id = self.store.add_node(GraphNode(id=0, kind=NodeKind.FILE, name="a.py"))
        n2_id = self.store.add_node(GraphNode(id=0, kind=NodeKind.FILE, name="b.py"))
        n3_id = self.store.add_node(GraphNode(id=0, kind=NodeKind.FILE, name="c.py"))
        self.store.add_edge(GraphEdge(source_id=n1_id, target_id=n2_id, kind=EdgeKind.IMPORTS))
        self.store.add_edge(GraphEdge(source_id=n1_id, target_id=n3_id, kind=EdgeKind.IMPORTS))
        
        neighbors = self.store.get_neighbors(n1_id, direction="outgoing")
        assert len(neighbors) == 2
        neighbor_names = {n.name for n in neighbors}
        assert neighbor_names == {"b.py", "c.py"}
    
    def test_node_count(self):
        self.store.add_node(GraphNode(id=0, kind=NodeKind.FILE, name="a.py"))
        self.store.add_node(GraphNode(id=0, kind=NodeKind.FILE, name="b.py"))
        assert self.store.node_count == 2
