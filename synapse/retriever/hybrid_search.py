from typing import List, Tuple, Dict
from synapse.graph.store import GraphStore
from synapse.graph.model import SearchResult, NodeKind
from synapse.indexer.embedder import Embedder

class HybridSearch:
    def __init__(self, graph_store: GraphStore, embedder: Embedder):
        self.store = graph_store
        self.embedder = embedder
        self._node_ids: List[str] = []
    
    def search(
        self, 
        query: str, 
        top_k: int = 10,
        content_filter: str = "code",
        boost_definitions: bool = True
    ) -> List[SearchResult]:
        """Hybrid search with RRF fusion and graph-aware reranking."""
        if not self._node_ids:
            return []
            
        # 1. BM25 search -> top_k*3 candidates
        bm25_res = self.embedder.search_bm25(query, top_k=top_k * 3)
        
        # 2. Semantic search -> top_k*3 candidates
        semantic_res = self.embedder.search_semantic(query, top_k=top_k * 3)
        
        # 3. RRF fusion of both ranked lists
        fused = self._rrf_fusion(bm25_res, semantic_res)
        
        # 4. Graph-aware reranking
        if boost_definitions:
            fused = self._apply_boosts(fused, query)
            # Re-sort after boosts
            fused.sort(key=lambda x: x[1], reverse=True)
            
        # 5. Return top_k results
        results = []
        for idx, score in fused[:top_k]:
            node_id = self._node_ids[idx]
            node = self.store.get_node(node_id)
            if node:
                snippet = node.skeleton or (node.full_body[:200] if node.full_body else None)
                results.append(
                    SearchResult(
                        node=node,
                        score=score,
                        match_type="hybrid",
                        snippet=snippet,
                        context_line=node.start_line,
                    )
                )
        return results
    
    def _rrf_fusion(
        self,
        bm25_results: List[Tuple[int, float]],
        semantic_results: List[Tuple[int, float]],
        k: int = 60
    ) -> List[Tuple[int, float]]:
        """Reciprocal Rank Fusion"""
        scores: Dict[int, float] = {}
        
        for rank, (idx, _) in enumerate(bm25_results):
            scores[idx] = scores.get(idx, 0.0) + 1.0 / (k + rank + 1)
            
        for rank, (idx, _) in enumerate(semantic_results):
            scores[idx] = scores.get(idx, 0.0) + 1.0 / (k + rank + 1)
            
        return sorted([(idx, score) for idx, score in scores.items()], key=lambda x: x[1], reverse=True)
    
    def _apply_boosts(
        self,
        results: List[Tuple[int, float]],
        query: str
    ) -> List[Tuple[int, float]]:
        """Apply graph-aware boosts"""
        boosted = []
        query_terms = set(query.lower().split())
        
        for idx, score in results:
            node_id = self._node_ids[idx]
            node = self.store.get_node(node_id)
            new_score = score
            
            if node:
                # Definition boost: +200% if query identifier is DEFINED in chunk
                if node.kind in [NodeKind.FUNCTION, NodeKind.CLASS, getattr(NodeKind, 'METHOD', None)]:
                    node_name = node.name.lower() if node.name else ""
                    if any(term in node_name for term in query_terms):
                        new_score *= 3.0  # +200%
                        
                # Centrality: higher score for more central nodes
                try:
                    edges = self.store.get_edges(node_id)
                    edge_count = len(edges)
                    # Small boost based on connectivity
                    new_score *= (1.0 + min(edge_count, 10) * 0.05)
                except Exception:
                    pass
                    
            boosted.append((idx, new_score))
            
        return boosted
    
    def build_index(self) -> None:
        """Build search index from all chunk nodes in the graph"""
        chunks = self.store.get_nodes_by_kind(NodeKind.CHUNK)
        funcs = self.store.get_nodes_by_kind(NodeKind.FUNCTION)
        classes = self.store.get_nodes_by_kind(NodeKind.CLASS)
        methods = self.store.get_nodes_by_kind(getattr(NodeKind, 'METHOD', NodeKind.FUNCTION)) if hasattr(NodeKind, 'METHOD') else []
        
        all_nodes = chunks + funcs + classes + methods
        # Deduplicate
        seen = set()
        unique_nodes = []
        for n in all_nodes:
            if n.id not in seen:
                seen.add(n.id)
                unique_nodes.append(n)
                
        texts = []
        self._node_ids = []
        for node in unique_nodes:
            text = node.skeleton or node.full_body or node.name or ""
            texts.append(text)
            self._node_ids.append(node.id)
            
        self.embedder.index(texts)
