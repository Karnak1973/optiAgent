import json
import sqlite3
from pathlib import Path
from typing import Any

import rustworkx as rx
from .model import GraphNode, GraphEdge, NodeKind, EdgeKind, SymbolKind

class GraphStore:
    """Core graph storage providing SQLite persistence and rustworkx algorithms."""
    
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()
        
        self.graph = rx.PyDiGraph()
        # Map SQLite node ID to rustworkx node index
        self._node_id_to_rx_idx: dict[int, int] = {}
        # Map rustworkx node index to SQLite node ID
        self._rx_idx_to_node_id: dict[int, int] = {}
        
        self._sync_to_rustworkx()
        
    def _init_schema(self):
        cursor = self.conn.cursor()
        cursor.executescript("""
        CREATE TABLE IF NOT EXISTS nodes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kind TEXT NOT NULL,
            name TEXT NOT NULL,
            file_path TEXT,
            start_line INTEGER,
            end_line INTEGER,
            signature TEXT,
            skeleton TEXT,
            full_body TEXT,
            docstring TEXT,
            language TEXT,
            enclosing_scope TEXT,
            symbol_kind TEXT,
            metadata TEXT DEFAULT '{}'
        );

        CREATE TABLE IF NOT EXISTS edges (
            source_id INTEGER NOT NULL REFERENCES nodes(id),
            target_id INTEGER NOT NULL REFERENCES nodes(id),
            kind TEXT NOT NULL,
            weight REAL DEFAULT 1.0,
            metadata TEXT DEFAULT '{}',
            PRIMARY KEY (source_id, target_id, kind)
        );
        
        CREATE INDEX IF NOT EXISTS idx_nodes_kind ON nodes(kind);
        CREATE INDEX IF NOT EXISTS idx_nodes_file_path ON nodes(file_path);
        CREATE INDEX IF NOT EXISTS idx_nodes_name ON nodes(name);
        CREATE INDEX IF NOT EXISTS idx_edges_source_id ON edges(source_id);
        CREATE INDEX IF NOT EXISTS idx_edges_target_id ON edges(target_id);
        CREATE INDEX IF NOT EXISTS idx_edges_kind ON edges(kind);
        """)
        self.conn.commit()

    def _sync_to_rustworkx(self):
        """Loads nodes and edges from SQLite into rustworkx in-memory graph."""
        self.graph.clear()
        self._node_id_to_rx_idx.clear()
        self._rx_idx_to_node_id.clear()
        
        cursor = self.conn.cursor()
        
        # Load nodes
        cursor.execute("SELECT id FROM nodes")
        for row in cursor.fetchall():
            node_id = row['id']
            idx = self.graph.add_node(node_id)
            self._node_id_to_rx_idx[node_id] = idx
            self._rx_idx_to_node_id[idx] = node_id
            
        # Load edges
        cursor.execute("SELECT source_id, target_id, kind FROM edges")
        for row in cursor.fetchall():
            src = row['source_id']
            tgt = row['target_id']
            if src in self._node_id_to_rx_idx and tgt in self._node_id_to_rx_idx:
                self.graph.add_edge(
                    self._node_id_to_rx_idx[src],
                    self._node_id_to_rx_idx[tgt],
                    row['kind']
                )

    def _row_to_node(self, row: sqlite3.Row) -> GraphNode:
        return GraphNode(
            id=row['id'],
            kind=NodeKind(row['kind']),
            name=row['name'],
            file_path=row['file_path'],
            start_line=row['start_line'],
            end_line=row['end_line'],
            signature=row['signature'],
            skeleton=row['skeleton'],
            full_body=row['full_body'],
            docstring=row['docstring'],
            language=row['language'],
            enclosing_scope=row['enclosing_scope'],
            symbol_kind=SymbolKind(row['symbol_kind']) if row['symbol_kind'] else None,
            metadata=json.loads(row['metadata'])
        )

    def add_node(self, node: GraphNode) -> int:
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO nodes (
                kind, name, file_path, start_line, end_line,
                signature, skeleton, full_body, docstring,
                language, enclosing_scope, symbol_kind, metadata
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            node.kind.value, node.name, node.file_path, node.start_line, node.end_line,
            node.signature, node.skeleton, node.full_body, node.docstring,
            node.language, node.enclosing_scope, 
            node.symbol_kind.value if node.symbol_kind else None,
            json.dumps(node.metadata)
        ))
        node_id = cursor.lastrowid
        self.conn.commit()
        node.id = node_id
        
        idx = self.graph.add_node(node_id)
        self._node_id_to_rx_idx[node_id] = idx
        self._rx_idx_to_node_id[idx] = node_id
        
        return node_id

    def add_edge(self, edge: GraphEdge):
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO edges (
                source_id, target_id, kind, weight, metadata
            ) VALUES (?, ?, ?, ?, ?)
        """, (
            edge.source_id, edge.target_id, edge.kind.value,
            edge.weight, json.dumps(edge.metadata)
        ))
        self.conn.commit()
        
        if edge.source_id in self._node_id_to_rx_idx and edge.target_id in self._node_id_to_rx_idx:
            src_idx = self._node_id_to_rx_idx[edge.source_id]
            tgt_idx = self._node_id_to_rx_idx[edge.target_id]
            self.graph.add_edge(src_idx, tgt_idx, edge.kind.value)

    def get_node(self, node_id: int) -> GraphNode | None:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM nodes WHERE id = ?", (node_id,))
        row = cursor.fetchone()
        if row:
            return self._row_to_node(row)
        return None

    def get_nodes_by_kind(self, kind: NodeKind) -> list[GraphNode]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM nodes WHERE kind = ?", (kind.value,))
        return [self._row_to_node(row) for row in cursor.fetchall()]

    def get_nodes_by_file(self, file_path: str) -> list[GraphNode]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM nodes WHERE file_path = ?", (file_path,))
        return [self._row_to_node(row) for row in cursor.fetchall()]

    def get_neighbors(self, node_id: int, edge_kind: EdgeKind | None = None, direction: str = 'outgoing') -> list[GraphNode]:
        if node_id not in self._node_id_to_rx_idx:
            return []
            
        idx = self._node_id_to_rx_idx[node_id]
        
        neighbor_indices = []
        if direction in ('outgoing', 'both'):
            if edge_kind:
                out_edges = self.graph.out_edges(idx)
                neighbor_indices.extend([tgt for _, tgt, k in out_edges if k == edge_kind.value])
            else:
                neighbor_indices.extend(self.graph.successor_indices(idx))
                
        if direction in ('incoming', 'both'):
            if edge_kind:
                in_edges = self.graph.in_edges(idx)
                neighbor_indices.extend([src for src, _, k in in_edges if k == edge_kind.value])
            else:
                neighbor_indices.extend(self.graph.predecessor_indices(idx))
                
        # Deduplicate
        neighbor_indices = list(set(neighbor_indices))
        
        neighbor_ids = [self._rx_idx_to_node_id[i] for i in neighbor_indices]
        
        if not neighbor_ids:
            return []
            
        placeholders = ','.join(['?'] * len(neighbor_ids))
        cursor = self.conn.cursor()
        cursor.execute(f"SELECT * FROM nodes WHERE id IN ({placeholders})", neighbor_ids)
        return [self._row_to_node(row) for row in cursor.fetchall()]

    def get_edges(self, source_id: int | None = None, target_id: int | None = None) -> list[GraphEdge]:
        cursor = self.conn.cursor()
        query = "SELECT * FROM edges WHERE 1=1"
        params = []
        if source_id is not None:
            query += " AND source_id = ?"
            params.append(source_id)
        if target_id is not None:
            query += " AND target_id = ?"
            params.append(target_id)
            
        cursor.execute(query, params)
        edges = []
        for row in cursor.fetchall():
            edges.append(GraphEdge(
                source_id=row['source_id'],
                target_id=row['target_id'],
                kind=EdgeKind(row['kind']),
                weight=row['weight'],
                metadata=json.loads(row['metadata'])
            ))
        return edges

    def clear(self):
        cursor = self.conn.cursor()
        cursor.execute("DELETE FROM edges")
        cursor.execute("DELETE FROM nodes")
        self.conn.commit()
        self.graph.clear()
        self._node_id_to_rx_idx.clear()
        self._rx_idx_to_node_id.clear()

    @property
    def node_count(self) -> int:
        cursor = self.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM nodes")
        row = cursor.fetchone()
        return row[0] if row else 0

    @property
    def edge_count(self) -> int:
        cursor = self.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM edges")
        row = cursor.fetchone()
        return row[0] if row else 0

    def get_rustworkx_graph(self) -> rx.PyDiGraph:
        return self.graph
