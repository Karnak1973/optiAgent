import tree_sitter
import tree_sitter_python
import tree_sitter_javascript
import tree_sitter_typescript

from synapse.graph.model import CodeChunk, SymbolKind


class ASTParser:
    def __init__(self):
        self.parsers = {}

        try:
            py_lang = tree_sitter.Language(tree_sitter_python.language())
            self.parsers["python"] = tree_sitter.Parser(py_lang)
        except Exception:
            pass

        try:
            js_lang = tree_sitter.Language(tree_sitter_javascript.language())
            self.parsers["javascript"] = tree_sitter.Parser(js_lang)
        except Exception:
            pass

        try:
            ts_lang = tree_sitter.Language(tree_sitter_typescript.language_typescript())
            self.parsers["typescript"] = tree_sitter.Parser(ts_lang)
        except Exception:
            pass

    def parse_file(self, file_path: str, content: str, language: str) -> list[CodeChunk]:
        if not content.strip() or language not in self.parsers:
            return []

        parser = self.parsers[language]
        tree = parser.parse(content.encode("utf-8"))

        if language == "python":
            return self._parse_python(file_path, content, tree)
        elif language == "javascript":
            return self._parse_javascript(file_path, content, tree)
        elif language == "typescript":
            return self._parse_typescript(file_path, content, tree)
        return []

    def _parse_python(self, file_path: str, content: str, tree: tree_sitter.Tree) -> list[CodeChunk]:
        chunks: list[CodeChunk] = []
        source_bytes = content.encode("utf-8")

        def traverse(node: tree_sitter.Node, current_class: str | None = None):
            if node.type == "class_definition":
                name_node = node.child_by_field_name("name")
                name = name_node.text.decode("utf-8") if name_node else "unknown"
                sig = self._extract_signature(node, source_bytes)
                doc = self._extract_docstring(node, source_bytes)
                skel = self._extract_skeleton(node, source_bytes)
                full_body = node.text.decode("utf-8")
                start_line = node.start_point[0] + 1
                end_line = node.end_point[0] + 1

                chunks.append(
                    CodeChunk(
                        file_path=file_path,
                        start_line=start_line,
                        end_line=end_line,
                        kind=SymbolKind.CLASS,
                        name=name,
                        language="python",
                        signature=sig,
                        skeleton=skel,
                        full_body=full_body,
                        enclosing_scope=current_class,
                        docstring=doc,
                        token_count_skeleton=max(1, len(skel) // 4),
                        token_count_full=max(1, len(full_body) // 4),
                    )
                )

                # Process children with this class as enclosing scope
                body_node = node.child_by_field_name("body")
                if body_node:
                    for child in body_node.children:
                        traverse(child, current_class=name)
                return

            elif node.type == "function_definition":
                name_node = node.child_by_field_name("name")
                name = name_node.text.decode("utf-8") if name_node else "unknown"
                sig = self._extract_signature(node, source_bytes)
                doc = self._extract_docstring(node, source_bytes)
                skel = self._extract_skeleton(node, source_bytes)
                full_body = node.text.decode("utf-8")
                start_line = node.start_point[0] + 1
                end_line = node.end_point[0] + 1
                kind = SymbolKind.METHOD if current_class else SymbolKind.FUNCTION

                chunks.append(
                    CodeChunk(
                        file_path=file_path,
                        start_line=start_line,
                        end_line=end_line,
                        kind=kind,
                        name=name,
                        language="python",
                        signature=sig,
                        skeleton=skel,
                        full_body=full_body,
                        enclosing_scope=current_class,
                        docstring=doc,
                        token_count_skeleton=max(1, len(skel) // 4),
                        token_count_full=max(1, len(full_body) // 4),
                    )
                )

            for child in node.children:
                traverse(child, current_class=current_class)

        traverse(tree.root_node)
        return chunks

    def _parse_javascript(self, file_path: str, content: str, tree: tree_sitter.Tree) -> list[CodeChunk]:
        chunks: list[CodeChunk] = []
        source_bytes = content.encode("utf-8")

        def traverse(node: tree_sitter.Node, current_class: str | None = None):
            # class_declaration / class
            if node.type in ("class_declaration", "class"):
                name_node = node.child_by_field_name("name")
                name = name_node.text.decode("utf-8") if name_node else "unknown"
                sig = self._extract_js_signature(node, source_bytes)
                doc = self._extract_js_docstring(node, source_bytes)
                skel = self._extract_skeleton_js(node, source_bytes)
                full_body = node.text.decode("utf-8")
                start_line = node.start_point[0] + 1
                end_line = node.end_point[0] + 1

                chunks.append(CodeChunk(
                    file_path=file_path,
                    start_line=start_line,
                    end_line=end_line,
                    kind=SymbolKind.CLASS,
                    name=name,
                    language="javascript",
                    signature=sig,
                    skeleton=skel,
                    full_body=full_body,
                    enclosing_scope=current_class,
                    docstring=doc,
                    token_count_skeleton=max(1, len(skel) // 4),
                    token_count_full=max(1, len(full_body) // 4),
                ))

                body_node = node.child_by_field_name("body")
                if body_node:
                    for child in body_node.children:
                        traverse(child, current_class=name)
                return

            # function_declaration
            if node.type == "function_declaration":
                name_node = node.child_by_field_name("name")
                name = name_node.text.decode("utf-8") if name_node else "anonymous"
                sig = self._extract_js_signature(node, source_bytes)
                doc = self._extract_js_docstring(node, source_bytes)
                skel = self._extract_skeleton_js(node, source_bytes)
                full_body = node.text.decode("utf-8")
                start_line = node.start_point[0] + 1
                end_line = node.end_point[0] + 1
                kind = SymbolKind.METHOD if current_class else SymbolKind.FUNCTION

                chunks.append(CodeChunk(
                    file_path=file_path,
                    start_line=start_line,
                    end_line=end_line,
                    kind=kind,
                    name=name,
                    language="javascript",
                    signature=sig,
                    skeleton=skel,
                    full_body=full_body,
                    enclosing_scope=current_class,
                    docstring=doc,
                    token_count_skeleton=max(1, len(skel) // 4),
                    token_count_full=max(1, len(full_body) // 4),
                ))

            # Arrow functions: const foo = (args) => body / const foo = function(...)
            if node.type == "lexical_declaration":
                for child in node.children:
                    if child.type == "variable_declarator":
                        name_node = child.child_by_field_name("name")
                        value_node = child.child_by_field_name("value")
                        if name_node and value_node:
                            name = name_node.text.decode("utf-8")
                            if value_node.type in ("arrow_function", "function"):
                                sig = self._extract_js_signature(value_node, source_bytes)
                                doc = ""
                                skel = f"{name} {sig}\n    ..."
                                full_body = value_node.text.decode("utf-8")
                                start_line = node.start_point[0] + 1
                                end_line = node.end_point[0] + 1

                                chunks.append(CodeChunk(
                                    file_path=file_path,
                                    start_line=start_line,
                                    end_line=end_line,
                                    kind=SymbolKind.FUNCTION,
                                    name=name,
                                    language="javascript",
                                    signature=f"const {name} = {sig}",
                                    skeleton=skel,
                                    full_body=full_body,
                                    enclosing_scope=current_class,
                                    docstring=doc or None,
                                    token_count_skeleton=max(1, len(skel) // 4),
                                    token_count_full=max(1, len(full_body) // 4),
                                ))

            # Method definition (inside class body)
            if node.type == "method_definition":
                name_node = node.child_by_field_name("name")
                name = name_node.text.decode("utf-8") if name_node else "unknown"
                sig = self._extract_js_signature(node, source_bytes)
                doc = self._extract_js_docstring(node, source_bytes)
                skel = self._extract_skeleton_js(node, source_bytes)
                full_body = node.text.decode("utf-8")
                start_line = node.start_point[0] + 1
                end_line = node.end_point[0] + 1

                chunks.append(CodeChunk(
                    file_path=file_path,
                    start_line=start_line,
                    end_line=end_line,
                    kind=SymbolKind.METHOD,
                    name=name,
                    language="javascript",
                    signature=sig,
                    skeleton=skel,
                    full_body=full_body,
                    enclosing_scope=current_class,
                    docstring=doc,
                    token_count_skeleton=max(1, len(skel) // 4),
                    token_count_full=max(1, len(full_body) // 4),
                ))

            for child in node.children:
                traverse(child, current_class=current_class)

        traverse(tree.root_node)
        return chunks

    def _parse_typescript(self, file_path: str, content: str, tree: tree_sitter.Tree) -> list[CodeChunk]:
        chunks: list[CodeChunk] = []
        source_bytes = content.encode("utf-8")

        def traverse(node: tree_sitter.Node, current_class: str | None = None):
            # class_declaration
            if node.type == "class_declaration":
                name_node = node.child_by_field_name("name")
                name = name_node.text.decode("utf-8") if name_node else "unknown"
                sig = self._extract_js_signature(node, source_bytes)
                doc = self._extract_js_docstring(node, source_bytes)
                skel = self._extract_skeleton_js(node, source_bytes)
                full_body = node.text.decode("utf-8")
                start_line = node.start_point[0] + 1
                end_line = node.end_point[0] + 1

                chunks.append(CodeChunk(
                    file_path=file_path,
                    start_line=start_line,
                    end_line=end_line,
                    kind=SymbolKind.CLASS,
                    name=name,
                    language="typescript",
                    signature=sig,
                    skeleton=skel,
                    full_body=full_body,
                    enclosing_scope=current_class,
                    docstring=doc,
                    token_count_skeleton=max(1, len(skel) // 4),
                    token_count_full=max(1, len(full_body) // 4),
                ))

                body_node = node.child_by_field_name("body")
                if body_node:
                    for child in body_node.children:
                        traverse(child, current_class=name)
                return

            # function_declaration
            if node.type == "function_declaration":
                name_node = node.child_by_field_name("name")
                name = name_node.text.decode("utf-8") if name_node else "anonymous"
                sig = self._extract_js_signature(node, source_bytes)
                doc = self._extract_js_docstring(node, source_bytes)
                skel = self._extract_skeleton_js(node, source_bytes)
                full_body = node.text.decode("utf-8")
                start_line = node.start_point[0] + 1
                end_line = node.end_point[0] + 1
                kind = SymbolKind.METHOD if current_class else SymbolKind.FUNCTION

                chunks.append(CodeChunk(
                    file_path=file_path,
                    start_line=start_line,
                    end_line=end_line,
                    kind=kind,
                    name=name,
                    language="typescript",
                    signature=sig,
                    skeleton=skel,
                    full_body=full_body,
                    enclosing_scope=current_class,
                    docstring=doc,
                    token_count_skeleton=max(1, len(skel) // 4),
                    token_count_full=max(1, len(full_body) // 4),
                ))

            # interface_declaration (TypeScript-specific)
            if node.type == "interface_declaration":
                name_node = node.child_by_field_name("name")
                name = name_node.text.decode("utf-8") if name_node else "unknown"
                full_body = node.text.decode("utf-8")
                start_line = node.start_point[0] + 1
                end_line = node.end_point[0] + 1

                chunks.append(CodeChunk(
                    file_path=file_path,
                    start_line=start_line,
                    end_line=end_line,
                    kind=SymbolKind.INTERFACE,
                    name=name,
                    language="typescript",
                    signature=f"interface {name}",
                    skeleton=full_body.split("\n")[0] + "\n    ...",
                    full_body=full_body,
                    enclosing_scope=current_class,
                    docstring=None,
                    token_count_skeleton=max(1, len(full_body.split("\n")[0]) // 4),
                    token_count_full=max(1, len(full_body) // 4),
                ))

            # Arrow functions / const declarations
            if node.type == "lexical_declaration":
                for child in node.children:
                    if child.type == "variable_declarator":
                        name_node = child.child_by_field_name("name")
                        value_node = child.child_by_field_name("value")
                        if name_node and value_node:
                            name = name_node.text.decode("utf-8")
                            if value_node.type in ("arrow_function", "function"):
                                sig = self._extract_js_signature(value_node, source_bytes)
                                skel = f"{name} {sig}\n    ..."
                                full_body = value_node.text.decode("utf-8")
                                start_line = node.start_point[0] + 1
                                end_line = node.end_point[0] + 1

                                chunks.append(CodeChunk(
                                    file_path=file_path,
                                    start_line=start_line,
                                    end_line=end_line,
                                    kind=SymbolKind.FUNCTION,
                                    name=name,
                                    language="typescript",
                                    signature=f"const {name} = {sig}",
                                    skeleton=skel,
                                    full_body=full_body,
                                    enclosing_scope=current_class,
                                    docstring=None,
                                    token_count_skeleton=max(1, len(skel) // 4),
                                    token_count_full=max(1, len(full_body) // 4),
                                ))

            # Method definition (inside class body)
            if node.type == "method_definition":
                name_node = node.child_by_field_name("name")
                name = name_node.text.decode("utf-8") if name_node else "unknown"
                sig = self._extract_js_signature(node, source_bytes)
                doc = self._extract_js_docstring(node, source_bytes)
                skel = self._extract_skeleton_js(node, source_bytes)
                full_body = node.text.decode("utf-8")
                start_line = node.start_point[0] + 1
                end_line = node.end_point[0] + 1

                chunks.append(CodeChunk(
                    file_path=file_path,
                    start_line=start_line,
                    end_line=end_line,
                    kind=SymbolKind.METHOD,
                    name=name,
                    language="typescript",
                    signature=sig,
                    skeleton=skel,
                    full_body=full_body,
                    enclosing_scope=current_class,
                    docstring=doc,
                    token_count_skeleton=max(1, len(skel) // 4),
                    token_count_full=max(1, len(full_body) // 4),
                ))

            for child in node.children:
                traverse(child, current_class=current_class)

        traverse(tree.root_node)
        return chunks

    def _extract_js_signature(self, node: tree_sitter.Node, source: bytes) -> str:
        """Extract JS/TS function/method signature up to the body."""
        body_node = node.child_by_field_name("body")
        if body_node:
            sig = source[node.start_byte:body_node.start_byte].decode("utf-8").strip()
            return sig
        # Fallback: first line
        return source[node.start_byte:node.end_byte].decode("utf-8").split("\n")[0].strip()

    def _extract_skeleton_js(self, node: tree_sitter.Node, source: bytes) -> str:
        """Extract JS/TS skeleton: signature + optional docstring + ..."""
        sig = self._extract_js_signature(node, source)
        doc = self._extract_js_docstring(node, source)
        skel = sig
        if doc:
            skel += f'\n    /** {doc} */'
        skel += "\n    ..."
        return skel

    def _extract_js_docstring(self, node: tree_sitter.Node, source: bytes) -> str | None:
        """Extract JSDoc comment from JS/TS node."""
        body = node.child_by_field_name("body")
        if body and body.children:
            for child in body.children:
                if child.type == "comment":
                    raw = child.text.decode("utf-8")
                    # Extract JSDoc: /** ... */
                    if raw.startswith("/**") and raw.endswith("*/"):
                        return raw[3:-3].strip()
                    # Single-line comment: // ...
                    if raw.startswith("//"):
                        return raw[2:].strip()
        # Check for comment before the node (in parent)
        if node.prev_sibling and node.prev_sibling.type == "comment":
            raw = node.prev_sibling.text.decode("utf-8")
            if raw.startswith("/**") and raw.endswith("*/"):
                return raw[3:-3].strip()
        return None

    def _extract_signature(self, node: tree_sitter.Node, source: bytes) -> str:
        body_node = node.child_by_field_name("body")
        if body_node:
            end_byte = body_node.start_byte
            sig = source[node.start_byte:end_byte].decode("utf-8").strip()
            # If the signature doesn't end with ':', check if there was a colon right before body
            if not sig.endswith(":"):
                colon_idx = source.rfind(b":", node.start_byte, body_node.start_byte)
                if colon_idx != -1:
                    sig = source[node.start_byte : colon_idx + 1].decode("utf-8").strip()
            return sig
        return source[node.start_byte:node.end_byte].decode("utf-8").split("\n")[0].strip()

    def _extract_skeleton(self, node: tree_sitter.Node, source: bytes) -> str:
        sig = self._extract_signature(node, source)
        doc = self._extract_docstring(node, source)
        skel = sig
        if doc:
            skel += f'\n    """{doc}"""'
        skel += "\n    ..."
        return skel

    def _extract_docstring(self, node: tree_sitter.Node, source: bytes) -> str | None:
        body = node.child_by_field_name("body")
        if body and body.children:
            for child in body.children:
                if child.type == "expression_statement":
                    for sub in child.children:
                        if sub.type == "string":
                            raw = sub.text.decode("utf-8")
                            for quote in ['"""', "'''", '"', "'"]:
                                if raw.startswith(quote) and raw.endswith(quote):
                                    return raw[len(quote) : -len(quote)].strip()
                            return raw.strip()
                elif child.type not in ["comment", "\n"]:
                    break
        return None

    def _get_enclosing_scope(self, node: tree_sitter.Node, source: bytes) -> str | None:
        parent = node.parent
        while parent:
            if parent.type == "class_definition":
                name_node = parent.child_by_field_name("name")
                if name_node:
                    return name_node.text.decode("utf-8")
            parent = parent.parent
        return None
