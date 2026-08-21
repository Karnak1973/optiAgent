from rank_bm25 import BM25Okapi
import numpy as np
import re
from typing import List, Tuple, Optional

class CodeTokenizer:
    """Code-aware tokenizer that splits camelCase, snake_case, etc."""
    def tokenize(self, text: str) -> List[str]:
        # Split on whitespace, then split camelCase and snake_case
        tokens = []
        # Split by non-alphanumeric characters first (like dots, slashes, dashes, spaces)
        raw_tokens = re.split(r'[^a-zA-Z0-9_]+', text)
        
        for raw in raw_tokens:
            if not raw:
                continue
            
            # Split camelCase
            camel_split = re.sub('([A-Z][a-z]+)', r' \1', re.sub('([A-Z]+)', r' \1', raw)).split()
            # Split snake_case
            snake_split = []
            for c in camel_split:
                snake_split.extend(c.split('_'))
                
            # Keep original compound token if length > 1
            if len(raw) > 1 and len(snake_split) > 1:
                tokens.append(raw.lower())
                
            for t in snake_split:
                t_lower = t.lower()
                if len(t_lower) >= 2 or t_lower in {'i', 'j', 'k', 'n', 'x', 'y'}:
                    tokens.append(t_lower)
        
        return list(set(tokens))

class Embedder:
    def __init__(self, model_name: str = "minishlab/potion-code-16M-v2"):
        self._model = None  # lazy load
        self._bm25 = None
        self._tokenizer = CodeTokenizer()
        self._corpus_tokens: List[List[str]] = []
        self._corpus_texts: List[str] = []
        self._embeddings: Optional[np.ndarray] = None
        self._model_name = model_name
    
    def index(self, texts: List[str]) -> None:
        """Build BM25 index and compute embeddings for all texts"""
        if not texts:
            self._corpus_tokens = []
            self._corpus_texts = []
            self._bm25 = None
            self._embeddings = None
            return

        self._corpus_tokens = [self._tokenizer.tokenize(t) for t in texts]
        self._bm25 = BM25Okapi(self._corpus_tokens)
        self._corpus_texts = texts
        self._embeddings = self._get_model().encode(texts)
    
    def search_bm25(self, query: str, top_k: int = 20) -> List[Tuple[int, float]]:
        """Return (index, score) pairs sorted by BM25 score"""
        if not self._bm25:
            return []
            
        tokenized_query = self._tokenizer.tokenize(query)
        scores = self._bm25.get_scores(tokenized_query)
        
        # Get top k indices
        top_indices = np.argsort(scores)[::-1][:top_k]
        
        return [(int(idx), float(scores[idx])) for idx in top_indices if scores[idx] > 0]
    
    def search_semantic(self, query: str, top_k: int = 20) -> List[Tuple[int, float]]:
        """Return (index, score) pairs sorted by cosine similarity"""
        if self._embeddings is None or len(self._embeddings) == 0:
            return []
            
        query_embedding = self._get_model().encode([query])[0]
        
        # Cosine similarity
        norm_query = np.linalg.norm(query_embedding)
        norm_embeddings = np.linalg.norm(self._embeddings, axis=1)
        
        # Avoid division by zero
        norm_query = norm_query if norm_query > 0 else 1e-10
        norm_embeddings = np.where(norm_embeddings > 0, norm_embeddings, 1e-10)
        
        similarities = np.dot(self._embeddings, query_embedding) / (norm_embeddings * norm_query)
        
        top_indices = np.argsort(similarities)[::-1][:top_k]
        
        return [(int(idx), float(similarities[idx])) for idx in top_indices]
    
    def _get_model(self):
        """Lazy load the Model2Vec model"""
        if self._model is None:
            from model2vec import StaticModel
            self._model = StaticModel.from_pretrained(self._model_name)
        return self._model
