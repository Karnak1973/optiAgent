"""Dynamic Token Budget Allocator with binary search fitting."""

from synapse.graph.cpg import CodePropertyGraph
from synapse.graph.model import BudgetAllocation, GraphNode, NodeKind


class TokenBudgetAllocator:
    def allocate(
        self,
        total_budget: int,
        query_complexity: float = 0.5,
    ) -> BudgetAllocation:
        if query_complexity < 0.3:  # Simple lookup
            return BudgetAllocation(
                total_budget=total_budget,
                architectural_map=int(total_budget * 0.05),
                target_skeletons=int(total_budget * 0.30),
                target_bodies=int(total_budget * 0.40),
                neighbor_interfaces=int(total_budget * 0.15),
                data_flow_context=int(total_budget * 0.05),
                reserved=int(total_budget * 0.05),
            )
        elif query_complexity < 0.7:  # Medium
            return BudgetAllocation(
                total_budget=total_budget,
                architectural_map=int(total_budget * 0.10),
                target_skeletons=int(total_budget * 0.25),
                target_bodies=int(total_budget * 0.35),
                neighbor_interfaces=int(total_budget * 0.20),
                data_flow_context=int(total_budget * 0.05),
                reserved=int(total_budget * 0.05),
            )
        else:  # Complex multi-file
            return BudgetAllocation(
                total_budget=total_budget,
                architectural_map=int(total_budget * 0.20),
                target_skeletons=int(total_budget * 0.30),
                target_bodies=int(total_budget * 0.20),
                neighbor_interfaces=int(total_budget * 0.15),
                data_flow_context=int(total_budget * 0.10),
                reserved=int(total_budget * 0.05),
            )

    def estimate_complexity(self, query: str) -> float:
        """Heuristic complexity estimation based on query features"""
        query_lower = query.lower()

        # High complexity keywords
        high_kw = ['refactor', 'migrate', 'all', 'across', 'architecture', 'design']
        if any(kw in query_lower for kw in high_kw):
            return 0.8

        # Medium complexity keywords
        med_kw = ['fix', 'bug', 'error', 'issue', 'update', 'change', 'how does']
        if any(kw in query_lower for kw in med_kw):
            return 0.5

        # Low complexity - default or explicit keywords
        return 0.2

    def fit_nodes_to_budget(
        self,
        ranked_nodes: list[tuple[GraphNode, float]],
        total_budget: int,
    ) -> list[GraphNode]:
        """Binary search fitting: find the maximum set of ranked nodes that fits the budget.

        Given nodes sorted by relevance score, use binary search on the score threshold
        to find the optimal cutoff that maximizes information within the token budget.
        Falls back to greedy selection when scores are uniform.
        """
        if not ranked_nodes:
            return []

        # Sort by score descending (highest first)
        ranked_nodes = sorted(ranked_nodes, key=lambda x: x[1], reverse=True)

        def estimate_tokens(node: GraphNode) -> int:
            if node.metadata.get("token_count_skeleton"):
                return node.metadata["token_count_skeleton"]
            return max(1, len(node.skeleton or node.full_body or node.name) // 4)

        # Check if scores are all the same (binary search won't help)
        unique_scores = set(score for _, score in ranked_nodes)
        if len(unique_scores) <= 1:
            # Greedy selection: just pack nodes in score order
            selected: list[GraphNode] = []
            tokens = 0
            for node, _ in ranked_nodes:
                node_tokens = estimate_tokens(node)
                if tokens + node_tokens <= total_budget:
                    selected.append(node)
                    tokens += node_tokens
            return selected

        def total_tokens_for_threshold(threshold: float) -> tuple[int, list[GraphNode]]:
            selected: list[GraphNode] = []
            tokens = 0
            for node, score in ranked_nodes:
                if score < threshold:
                    break
                node_tokens = estimate_tokens(node)
                if tokens + node_tokens <= total_budget:
                    selected.append(node)
                    tokens += node_tokens
            return tokens, selected

        # Binary search on score threshold
        low = 0.0
        high = ranked_nodes[0][1] + 1e-9
        best_nodes: list[GraphNode] = []

        for _ in range(30):
            mid = (low + high) / 2
            tokens, nodes = total_tokens_for_threshold(mid)
            if tokens <= total_budget:
                best_nodes = nodes
                low = mid
            else:
                high = mid

        return best_nodes
