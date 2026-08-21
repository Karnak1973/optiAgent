"""Personalized PageRank and Smart Graph Expansion for context selection."""

from dataclasses import dataclass, field
from typing import Any
import rustworkx as rx

from synapse.graph.cpg import CodePropertyGraph
from synapse.graph.model import EdgeKind, GraphNode, NodeKind


@dataclass
class ExpandedContext:
    seed_nodes: list[GraphNode]
    expanded_nodes: list[tuple[GraphNode, float]]  # (node, ppr_score)
    total_tokens: int
    included_node_ids: list[int]
    metadata: dict[str, Any] = field(default_factory=dict)


class GraphExpander:
    """Expands context around seed nodes using Personalized PageRank (PPR)
    and graph centrality ranking within strict token limits.
    """

    def __init__(self, cpg: CodePropertyGraph):
        self.cpg = cpg
        self.store = cpg.store

    def expand(
        self,
        seed_node_ids: list[int],
        token_budget: int = 2048,
        alpha: float = 0.85,
        max_nodes: int = 20,
    ) -> ExpandedContext:
        """Run Personalized PageRank conditioned on seed nodes.
        Returns the highest-scoring subgraph fitting the token budget.
        """
        if not seed_node_ids:
            return ExpandedContext(
                seed_nodes=[],
                expanded_nodes=[],
                total_tokens=0,
                included_node_ids=[],
            )

        graph = self.store.get_rustworkx_graph()
        if graph.num_nodes() == 0:
            return ExpandedContext(
                seed_nodes=[],
                expanded_nodes=[],
                total_tokens=0,
                included_node_ids=[],
            )

        # Build personalization dictionary mapping rx node indices to weights
        personalization = {}
        seed_rx_indices = []
        for s_id in seed_node_ids:
            if s_id in self.store._node_id_to_rx_idx:
                rx_idx = self.store._node_id_to_rx_idx[s_id]
                seed_rx_indices.append(rx_idx)
                personalization[rx_idx] = 1.0 / len(seed_node_ids)

        if not personalization:
            # Fallback if seed nodes not in graph
            return ExpandedContext(
                seed_nodes=[],
                expanded_nodes=[],
                total_tokens=0,
                included_node_ids=[],
            )

        try:
            ppr_scores = rx.pagerank(
                graph,
                alpha=alpha,
                personalization=personalization,
                max_iter=100,
                tol=1e-6,
            )
        except Exception:
            # Fallback: standard degree / proximity
            ppr_scores = {idx: 1.0 for idx in personalization}

        # Map rx index back to SQLite node ID & sort by score descending
        ranked_nodes: list[tuple[GraphNode, float]] = []
        for rx_idx, score in ppr_scores.items():
            if rx_idx in self.store._rx_idx_to_node_id:
                node_id = self.store._rx_idx_to_node_id[rx_idx]
                node = self.store.get_node(node_id)
                if node and node.kind != NodeKind.FILE:
                    ranked_nodes.append((node, float(score)))

        ranked_nodes.sort(key=lambda x: x[1], reverse=True)

        # Binary search / greedy budget packing
        selected: list[tuple[GraphNode, float]] = []
        total_tokens = 0
        included_ids = []
        seed_nodes = [self.store.get_node(sid) for sid in seed_node_ids if self.store.get_node(sid)]

        for node, score in ranked_nodes[:max_nodes]:
            # Estimate tokens: skeleton tokens or length heuristic
            node_tokens = node.metadata.get("token_count_skeleton", max(1, len(node.skeleton or node.name) // 4))
            if total_tokens + node_tokens <= token_budget:
                selected.append((node, score))
                total_tokens += node_tokens
                included_ids.append(node.id)

        return ExpandedContext(
            seed_nodes=seed_nodes,
            expanded_nodes=selected,
            total_tokens=total_tokens,
            included_node_ids=included_ids,
            metadata={"alpha": alpha, "seed_count": len(seed_node_ids)},
        )

    def get_ego_subgraph(
        self,
        center_node_id: int,
        hops: int = 1,
    ) -> list[GraphNode]:
        """Extract k-hop ego network around a center node."""
        visited_ids = {center_node_id}
        current_layer = {center_node_id}

        for _ in range(hops):
            next_layer = set()
            for nid in current_layer:
                neighbors = self.store.get_neighbors(nid, direction="both")
                for n in neighbors:
                    if n.id not in visited_ids:
                        visited_ids.add(n.id)
                        next_layer.add(n.id)
            current_layer = next_layer

        return [self.store.get_node(nid) for nid in visited_ids if self.store.get_node(nid)]
