from dataclasses import dataclass, field
from enum import StrEnum, IntEnum
from typing import Any

class NodeKind(StrEnum):
    FILE = "FILE"
    PACKAGE = "PACKAGE"
    CLASS = "CLASS"
    INTERFACE = "INTERFACE"
    FUNCTION = "FUNCTION"
    METHOD = "METHOD"
    VARIABLE = "VARIABLE"
    CHUNK = "CHUNK"
    DOCSTRING = "DOCSTRING"
    CONFIG_BLOCK = "CONFIG_BLOCK"

class EdgeKind(StrEnum):
    IMPORTS = "IMPORTS"
    DECLARES = "DECLARES"
    INHERITS = "INHERITS"
    IMPLEMENTS = "IMPLEMENTS"
    CALLS = "CALLS"
    CALLED_BY = "CALLED_BY"
    REFERENCES = "REFERENCES"
    DEF_USE = "DEF_USE"
    CONTAINS = "CONTAINS"
    OVERRIDES = "OVERRIDES"
    NEXT_SIBLING = "NEXT_SIBLING"

class SymbolKind(StrEnum):
    MODULE = "MODULE"
    CLASS = "CLASS"
    INTERFACE = "INTERFACE"
    FUNCTION = "FUNCTION"
    METHOD = "METHOD"
    VARIABLE = "VARIABLE"
    CONSTANT = "CONSTANT"
    PROPERTY = "PROPERTY"
    ENUM = "ENUM"
    TYPE_ALIAS = "TYPE_ALIAS"

class ZoomLevel(IntEnum):
    ARCHITECTURE = 0
    SKELETON = 1
    INTERFACE = 2
    IMPLEMENTATION = 3
    SLICE = 4

@dataclass
class GraphNode:
    id: int
    kind: NodeKind
    name: str
    file_path: str | None = None
    start_line: int | None = None
    end_line: int | None = None
    signature: str | None = None      # e.g. 'def foo(x: int) -> bool'
    skeleton: str | None = None       # Signature + docstring, body replaced with ...
    full_body: str | None = None      # Complete source code
    docstring: str | None = None
    language: str | None = None
    enclosing_scope: str | None = None # Parent class/module name
    symbol_kind: SymbolKind | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

@dataclass
class GraphEdge:
    source_id: int
    target_id: int
    kind: EdgeKind
    weight: float = 1.0
    metadata: dict[str, Any] = field(default_factory=dict)

@dataclass
class ContextualFingerprint:
    """Ultra-compact representation of a code element's role (~20 tokens)"""
    name: str
    kind: str
    signature: str | None
    in_degree: int
    out_degree: int
    cluster: str | None = None
    centrality_percentile: float = 0.0
    
    def to_compact_str(self) -> str:
        """Format as minimal token string"""
        parts = [f"{self.kind} {self.name}"]
        if self.signature:
            parts.append(self.signature)
        parts.append(f"[in:{self.in_degree} out:{self.out_degree} rank:{self.centrality_percentile:.0%}]")
        return " ".join(parts)

@dataclass 
class CodeChunk:
    """A semantically coherent unit of code extracted from AST"""
    file_path: str
    start_line: int
    end_line: int
    kind: SymbolKind
    name: str
    language: str
    signature: str
    skeleton: str
    full_body: str
    enclosing_scope: str | None = None
    docstring: str | None = None
    token_count_skeleton: int = 0
    token_count_full: int = 0

@dataclass
class SearchResult:
    node: GraphNode
    score: float
    match_type: str  # 'bm25', 'semantic', 'hybrid'
    snippet: str | None = None
    context_line: int | None = None

@dataclass
class ZoomedContext:
    zoom_level: ZoomLevel
    content: str
    token_count: int
    nodes_included: list[int]  # node IDs
    metadata: dict[str, Any] = field(default_factory=dict)

@dataclass
class BudgetAllocation:
    total_budget: int
    architectural_map: int
    target_skeletons: int
    target_bodies: int
    neighbor_interfaces: int
    data_flow_context: int
    reserved: int
