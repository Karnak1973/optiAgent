from typing import Any
import rustworkx as rx
from .model import (
    GraphNode, GraphEdge, NodeKind, EdgeKind, SymbolKind,
    CodeChunk, ContextualFingerprint
)
from .store import GraphStore

class CodePropertyGraph:
    """Higher-level operations wrapper around GraphStore for the Code Property Graph."""
    
    def __init__(self, store: GraphStore):
        self.store = store
        
    def from_chunks(self, chunks: list[CodeChunk]):
        """Build the graph from parsed CodeChunks."""
        for chunk in chunks:
            node = GraphNode(
                id=0, # Assigned by store
                kind=NodeKind.CHUNK,
                name=chunk.name,
                file_path=chunk.file_path,
                start_line=chunk.start_line,
                end_line=chunk.end_line,
                signature=chunk.signature,
                skeleton=chunk.skeleton,
                full_body=chunk.full_body,
                docstring=chunk.docstring,
                language=chunk.language,
                enclosing_scope=chunk.enclosing_scope,
                symbol_kind=chunk.kind,
            )
            self.store.add_node(node)
            
    def get_callers(self, function_name: str) -> list[GraphNode]:
        """Find nodes that call a given function name."""
        cursor = self.store.conn.cursor()
        cursor.execute("SELECT id FROM nodes WHERE name = ? AND kind IN ('FUNCTION', 'METHOD', 'CHUNK')", (function_name,))
        rows = cursor.fetchall()
        
        callers = []
        for row in rows:
            node_id = row['id']
            # Find incoming CALLS edges to this function node
            callers.extend(self.store.get_neighbors(node_id, EdgeKind.CALLS, direction='incoming'))
        return list({n.id: n for n in callers}.values())

    def get_callees(self, function_name: str) -> list[GraphNode]:
        """Find functions called by a given function name."""
        cursor = self.store.conn.cursor()
        cursor.execute("SELECT id FROM nodes WHERE name = ? AND kind IN ('FUNCTION', 'METHOD', 'CHUNK')", (function_name,))
        rows = cursor.fetchall()
        
        callees = []
        for row in rows:
            node_id = row['id']
            callees.extend(self.store.get_neighbors(node_id, EdgeKind.CALLS, direction='outgoing'))
        return list({n.id: n for n in callees}.values())

    def get_dependencies(self, file_path: str) -> list[GraphNode]:
        """Get nodes representing files this file depends on."""
        cursor = self.store.conn.cursor()
        cursor.execute("SELECT id FROM nodes WHERE file_path = ? AND kind = 'FILE'", (file_path,))
        row = cursor.fetchone()
        if not row:
            return []
        return self.store.get_neighbors(row['id'], EdgeKind.IMPORTS, direction='outgoing')

    def get_dependents(self, file_path: str) -> list[GraphNode]:
        """Get nodes representing files that depend on this file."""
        cursor = self.store.conn.cursor()
        cursor.execute("SELECT id FROM nodes WHERE file_path = ? AND kind = 'FILE'", (file_path,))
        row = cursor.fetchone()
        if not row:
            return []
        return self.store.get_neighbors(row['id'], EdgeKind.IMPORTS, direction='incoming')

    def get_class_hierarchy(self, class_name: str) -> dict[str, Any]:
        """Returns the inheritance tree (bases and subclasses) for a given class."""
        cursor = self.store.conn.cursor()
        cursor.execute("SELECT id, name FROM nodes WHERE name = ? AND (kind = 'CLASS' OR symbol_kind = 'CLASS')", (class_name,))
        row = cursor.fetchone()
        if not row:
            return {}
            
        node_id = row['id']
        
        hierarchy = {"name": class_name, "bases": [], "subclasses": []}
        
        bases = self.store.get_neighbors(node_id, EdgeKind.INHERITS, direction='outgoing')
        subclasses = self.store.get_neighbors(node_id, EdgeKind.INHERITS, direction='incoming')
        
        hierarchy["bases"] = [b.name for b in bases]
        hierarchy["subclasses"] = [s.name for s in subclasses]
        
        return hierarchy

    def get_file_symbols(self, file_path: str) -> list[GraphNode]:
        """Get all symbols defined within a specific file."""
        return self.store.get_nodes_by_file(file_path)

    def get_fingerprint(self, node_id: int) -> ContextualFingerprint:
        """Generate a contextual fingerprint for a specific node."""
        node = self.store.get_node(node_id)
        if not node:
            raise ValueError(f"Node {node_id} not found")
            
        if node_id not in self.store._node_id_to_rx_idx:
            in_degree = 0
            out_degree = 0
        else:
            idx = self.store._node_id_to_rx_idx[node_id]
            in_degree = self.store.graph.in_degree(idx)
            out_degree = self.store.graph.out_degree(idx)
            
        return ContextualFingerprint(
            name=node.name,
            kind=node.kind.value if node.kind else "UNKNOWN",
            signature=node.signature,
            in_degree=in_degree,
            out_degree=out_degree,
            cluster=node.metadata.get("cluster"),
            centrality_percentile=node.metadata.get("centrality_percentile", 0.0)
        )
