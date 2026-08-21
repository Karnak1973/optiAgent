"""Contextual Fingerprinting and Codebase Topology Clustering."""

from dataclasses import dataclass
import os
import rustworkx as rx

from synapse.graph.cpg import CodePropertyGraph
from synapse.graph.model import ContextualFingerprint, GraphNode, NodeKind


@dataclass
class CodeCluster:
    cluster_id: int
    name: str
    member_count: int
    top_symbols: list[str]
    lead_files: list[str]


class CodebaseFingerprinter:
    """Computes global structural topology, centrality percentiles,
    and contextual fingerprints for all symbols in the repository.
    """

    def __init__(self, cpg: CodePropertyGraph):
        self.cpg = cpg
        self.store = cpg.store

    def compute_fingerprints(self) -> dict[int, ContextualFingerprint]:
        """Compute fingerprints for all function, method, and class nodes."""
        graph = self.store.get_rustworkx_graph()
        num_nodes = graph.num_nodes()

        # Compute PageRank for centrality baseline
        if num_nodes > 0:
            try:
                pageranks = rx.pagerank(graph, alpha=0.85)
            except Exception:
                pageranks = {i: 1.0 / num_nodes for i in range(num_nodes)}
        else:
            pageranks = {}

        # Determine percentile rank for each node
        sorted_scores = sorted(pageranks.values())
        total_scores = len(sorted_scores)

        fingerprints: dict[int, ContextualFingerprint] = {}

        for kind in [NodeKind.FUNCTION, NodeKind.CLASS, NodeKind.METHOD]:
            for node in self.store.get_nodes_by_kind(kind):
                rx_idx = self.store._node_id_to_rx_idx.get(node.id)
                if rx_idx is not None and rx_idx in pageranks:
                    raw_score = pageranks[rx_idx]
                    rank_idx = sorted_scores.index(raw_score)
                    percentile = (rank_idx + 1) / total_scores if total_scores > 0 else 0.0
                    in_deg = graph.in_degree(rx_idx)
                    out_deg = graph.out_degree(rx_idx)
                else:
                    percentile = 0.0
                    in_deg = 0
                    out_deg = 0

                # Infer cluster/domain from path
                cluster = "core"
                if node.file_path:
                    parts = os.path.normpath(node.file_path).split(os.sep)
                    if len(parts) > 1:
                        cluster = parts[-2]

                fp = ContextualFingerprint(
                    name=node.name,
                    kind=node.kind.value if hasattr(node.kind, "value") else str(node.kind),
                    signature=node.signature,
                    in_degree=in_deg,
                    out_degree=out_deg,
                    cluster=cluster,
                    centrality_percentile=percentile,
                )
                fingerprints[node.id] = fp

        return fingerprints

    def get_topology_clusters(self) -> list[CodeCluster]:
        """Group codebase symbols into cohesive clusters based on directory/module topology."""
        files = self.store.get_nodes_by_kind(NodeKind.FILE)
        clusters_map: dict[str, list[GraphNode]] = {}

        for f in files:
            dir_name = os.path.dirname(f.file_path or f.name).replace("\\", "/")
            if not dir_name or dir_name == ".":
                dir_name = "root"
            else:
                dir_name = dir_name.split("/")[-1]

            symbols = self.store.get_nodes_by_file(f.file_path or f.name)
            clusters_map.setdefault(dir_name, []).extend(symbols)

        result: list[CodeCluster] = []
        for i, (name, members) in enumerate(sorted(clusters_map.items())):
            sym_names = [m.name for m in members if m.kind in [NodeKind.CLASS, NodeKind.FUNCTION]][:6]
            file_names = sorted({m.file_path for m in members if m.file_path})[:4]
            result.append(
                CodeCluster(
                    cluster_id=i + 1,
                    name=name,
                    member_count=len(members),
                    top_symbols=sym_names,
                    lead_files=file_names,
                )
            )

        return result
