import pytest
from synapse.indexer.parser import ASTParser
from synapse.graph.model import SymbolKind


class TestASTParser:
    def setup_method(self):
        self.parser = ASTParser()
    
    def test_parse_python_function(self):
        code = '''def greet(name: str) -> str:
    """Greet a person."""
    return f"Hello, {name}!"
'''
        chunks = self.parser.parse_file("test.py", code, "python")
        assert len(chunks) >= 1
        func_chunks = [c for c in chunks if c.kind == SymbolKind.FUNCTION]
        assert len(func_chunks) == 1
        assert func_chunks[0].name == "greet"
        assert "name: str" in func_chunks[0].signature
        assert "-> str" in func_chunks[0].signature
    
    def test_parse_python_class(self):
        code = '''class Calculator:
    """A simple calculator."""
    
    def add(self, a: int, b: int) -> int:
        return a + b
    
    def subtract(self, a: int, b: int) -> int:
        return a - b
'''
        chunks = self.parser.parse_file("test.py", code, "python")
        class_chunks = [c for c in chunks if c.kind == SymbolKind.CLASS]
        method_chunks = [c for c in chunks if c.kind == SymbolKind.METHOD]
        assert len(class_chunks) == 1
        assert class_chunks[0].name == "Calculator"
        assert len(method_chunks) == 2
    
    def test_skeleton_elides_body(self):
        code = '''def complex_function(x: int, y: int) -> int:
    """Do something complex."""
    result = 0
    for i in range(x):
        for j in range(y):
            result += i * j
    return result
'''
        chunks = self.parser.parse_file("test.py", code, "python")
        func = [c for c in chunks if c.kind == SymbolKind.FUNCTION][0]
        assert "..." in func.skeleton
        assert "complex_function" in func.skeleton
        assert "Do something complex" in func.skeleton
        # Skeleton should be shorter than full body
        assert len(func.skeleton) < len(func.full_body)
    
    def test_parse_empty_file(self):
        chunks = self.parser.parse_file("empty.py", "", "python")
        assert chunks == []
    
    def test_extract_docstring(self):
        code = '''def documented(x: int) -> bool:
    """Check if x is positive.
    
    Args:
        x: The number to check.
    
    Returns:
        True if x > 0.
    """
    return x > 0
'''
        chunks = self.parser.parse_file("test.py", code, "python")
        func = [c for c in chunks if c.kind == SymbolKind.FUNCTION][0]
        assert func.docstring is not None
        assert "Check if x is positive" in func.docstring
