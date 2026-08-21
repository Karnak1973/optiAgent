"""HTTP server for 3D graph visualization with token metrics."""

import json
import threading
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from synapse.graph.cpg import CodePropertyGraph
from synapse.graph.model import EdgeKind, NodeKind


class GraphAPIHandler(SimpleHTTPRequestHandler):
    """Serves the 3D visualization HTML and provides graph data API."""

    cpg: CodePropertyGraph = None  # Set by start_server

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")

        if path == "" or path == "/index.html":
            self._serve_html()
        elif path == "/api/graph":
            self._serve_graph_data()
        elif path == "/api/tokens":
            self._serve_token_metrics()
        elif path == "/api/stats":
            self._serve_stats()
        else:
            self.send_error(404)

    def _serve_html(self):
        html_path = Path(__file__).parent / "static" / "index.html"
        content = html_path.read_text(encoding="utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(content.encode("utf-8"))

    def _serve_graph_data(self):
        """Return nodes and edges as JSON for Three.js."""
        store = self.cpg.store
        nodes_json = []
        edges_json = []

        # Node kind -> color mapping
        kind_colors = {
            "FILE": "#4a9eff",
            "CLASS": "#ff6b6b",
            "INTERFACE": "#ffd93d",
            "FUNCTION": "#6bcb77",
            "METHOD": "#4ecdc4",
            "VARIABLE": "#a8a8a8",
            "CHUNK": "#95a5a6",
        }

        # Node kind -> size multiplier
        kind_sizes = {
            "FILE": 3.0,
            "CLASS": 2.5,
            "INTERFACE": 2.0,
            "FUNCTION": 1.5,
            "METHOD": 1.2,
            "VARIABLE": 0.8,
            "CHUNK": 1.0,
        }

        for node in store.get_nodes_by_kind(NodeKind.FILE):
            tokens = node.metadata.get("token_count_full", 0)
            nodes_json.append({
                "id": node.id,
                "name": node.name,
                "kind": "FILE",
                "color": kind_colors["FILE"],
                "size": kind_sizes["FILE"],
                "tokens": tokens,
                "filePath": node.file_path or "",
                "signature": "",
                "line": 0,
            })

        for kind in [NodeKind.CLASS, NodeKind.INTERFACE, NodeKind.FUNCTION, NodeKind.METHOD]:
            for node in store.get_nodes_by_kind(kind):
                kind_str = kind.value
                tokens = node.metadata.get("token_count_full", node.metadata.get("token_count_skeleton", 0))
                nodes_json.append({
                    "id": node.id,
                    "name": node.name,
                    "kind": kind_str,
                    "color": kind_colors.get(kind_str, "#95a5a6"),
                    "size": kind_sizes.get(kind_str, 1.0),
                    "tokens": tokens,
                    "filePath": node.file_path or "",
                    "signature": node.signature or "",
                    "line": node.start_line or 0,
                })

        # Edges
        for node in store.get_nodes_by_kind(NodeKind.FILE):
            for edge in store.get_edges(source_id=node.id):
                if edge.kind in [EdgeKind.DECLARES, EdgeKind.IMPORTS, EdgeKind.CALLS, EdgeKind.CONTAINS, EdgeKind.INHERITS]:
                    edges_json.append({
                        "source": edge.source_id,
                        "target": edge.target_id,
                        "kind": edge.kind.value,
                    })

        for kind in [NodeKind.CLASS, NodeKind.INTERFACE, NodeKind.FUNCTION, NodeKind.METHOD]:
            for node in store.get_nodes_by_kind(kind):
                for edge in store.get_edges(source_id=node.id):
                    if edge.kind in [EdgeKind.DECLARES, EdgeKind.CALLS, EdgeKind.CONTAINS, EdgeKind.INHERITS]:
                        edges_json.append({
                            "source": edge.source_id,
                            "target": edge.target_id,
                            "kind": edge.kind.value,
                        })

        data = {"nodes": nodes_json, "edges": edges_json}
        self._send_json(data)

    def _serve_token_metrics(self):
        """Return token consumption metrics for each zoom level."""
        store = self.cpg.store
        zoom = __import__("synapse.retriever.zoom_controller", fromlist=["ZoomController"]).ZoomController(self.cpg)

        # L0: Architecture
        ctx0 = zoom.get_architecture_map()
        # L1: Skeleton of each file
        files = store.get_nodes_by_kind(NodeKind.FILE)
        file_skeletons = []
        total_skeleton_tokens = 0
        for f in files[:20]:
            ctx1 = zoom.get_module_skeleton(f.file_path or f.name)
            file_skeletons.append({
                "name": f.name,
                "tokens": ctx1.token_count,
            })
            total_skeleton_tokens += ctx1.token_count

        # L2-L3: Per-symbol
        symbol_metrics = []
        total_impl_tokens = 0
        for kind in [NodeKind.FUNCTION, NodeKind.CLASS, NodeKind.METHOD]:
            for node in store.get_nodes_by_kind(kind):
                skel_tokens = node.metadata.get("token_count_skeleton", max(1, len(node.skeleton or node.name) // 4))
                full_tokens = node.metadata.get("token_count_full", max(1, len(node.full_body or node.name) // 4))
                symbol_metrics.append({
                    "name": node.name,
                    "kind": kind.value,
                    "file": node.file_path or "",
                    "skeletonTokens": skel_tokens,
                    "fullTokens": full_tokens,
                    "line": node.start_line or 0,
                })
                total_impl_tokens += full_tokens

        # Totals
        total_nodes = store.node_count
        total_edges = store.edge_count

        metrics = {
            "summary": {
                "totalNodes": total_nodes,
                "totalEdges": total_edges,
                "totalFiles": len(files),
                "totalSymbols": len(symbol_metrics),
                "architectureTokens": ctx0.token_count,
                "totalSkeletonTokens": total_skeleton_tokens,
                "totalImplementationTokens": total_impl_tokens,
            },
            "architecture": {
                "content": ctx0.content,
                "tokens": ctx0.token_count,
            },
            "fileSkeletons": file_skeletons,
            "symbols": symbol_metrics,
            "zoomComparison": {
                "L0": ctx0.token_count,
                "L1Avg": total_skeleton_tokens // max(1, len(file_skeletons)),
                "L2Avg": sum(s["skeletonTokens"] for s in symbol_metrics) // max(1, len(symbol_metrics)),
                "L3Avg": sum(s["fullTokens"] for s in symbol_metrics) // max(1, len(symbol_metrics)),
            },
        }
        self._send_json(metrics)

    def _serve_stats(self):
        """Return basic graph statistics."""
        store = self.cpg.store
        kind_counts = {}
        for kind in NodeKind:
            count = len(store.get_nodes_by_kind(kind))
            if count > 0:
                kind_counts[kind.value] = count

        edge_counts = {}
        all_nodes = []
        for kind in NodeKind:
            all_nodes.extend(store.get_nodes_by_kind(kind))
        for node in all_nodes:
            for edge in store.get_edges(source_id=node.id):
                edge_counts[edge.kind.value] = edge_counts.get(edge.kind.value, 0) + 1

        self._send_json({
            "nodesByKind": kind_counts,
            "edgesByKind": edge_counts,
            "totalNodes": store.node_count,
            "totalEdges": store.edge_count,
        })

    def _send_json(self, data):
        content = json.dumps(data, default=str)
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(content.encode("utf-8"))

    def log_message(self, format, *args):
        pass  # Suppress request logs


def start_server(cpg: CodePropertyGraph, port: int = 8765, open_browser: bool = True):
    """Start the 3D visualization server."""
    GraphAPIHandler.cpg = cpg
    server = HTTPServer(("127.0.0.1", port), GraphAPIHandler)

    url = f"http://127.0.0.1:{port}"

    if open_browser:
        import webbrowser
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()

    print(f"\n  Synapse 3D Graph Viewer")
    print(f"  Open: {url}")
    print(f"  Press Ctrl+C to stop\n")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  Server stopped.")
        server.server_close()
