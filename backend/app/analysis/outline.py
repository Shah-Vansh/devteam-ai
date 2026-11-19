"""Short outlines of source files, built from the Python AST.

An outline keeps what another file needs to know (imports, route decorators, class
fields, function signatures, module-level names) and drops function bodies. It lets an
agent see the whole project while only the files it works on are sent in full, which
keeps each request inside small per-minute token limits.
"""

import ast

MAX_TEXT_OUTLINE_LINES = 15


def outline_file(path: str, content: str) -> str:
    if path.endswith(".py"):
        return outline_python(content)
    lines = content.splitlines()
    head = lines[:MAX_TEXT_OUTLINE_LINES]
    if len(lines) > len(head):
        head.append(f"... ({len(lines) - len(head)} more lines)")
    return "\n".join(head)


def outline_python(content: str) -> str:
    try:
        tree = ast.parse(content)
    except SyntaxError as exc:
        return f"# (could not parse: {exc.msg} on line {exc.lineno})"
    lines: list[str] = []
    for node in tree.body:
        lines.extend(_outline_node(node, indent=""))
    return "\n".join(lines) if lines else "# (empty module)"


def _outline_node(node: ast.stmt, indent: str) -> list[str]:
    if isinstance(node, ast.Import | ast.ImportFrom):
        return [indent + ast.unparse(node)]
    if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
        return [*_decorators(node, indent), indent + _signature(node)]
    if isinstance(node, ast.ClassDef):
        bases = ", ".join(ast.unparse(b) for b in node.bases)
        lines = [*_decorators(node, indent), f"{indent}class {node.name}({bases}):"]
        members = [m for child in node.body for m in _outline_node(child, indent + "    ")]
        return lines + (members or [indent + "    ..."])
    if isinstance(node, ast.AnnAssign):
        return [indent + ast.unparse(node)]  # e.g. `title: str = Field(...)`
    if isinstance(node, ast.Assign):
        targets = ", ".join(ast.unparse(t) for t in node.targets)
        value = ast.unparse(node.value)
        if len(value) > 60:
            value = value[:57] + "..."
        return [f"{indent}{targets} = {value}"]
    return []


def _decorators(node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef, indent: str):
    return [f"{indent}@{ast.unparse(d)}" for d in node.decorator_list]


def _signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
    returns = f" -> {ast.unparse(node.returns)}" if node.returns else ""
    return f"{prefix} {node.name}({ast.unparse(node.args)}){returns}: ..."
