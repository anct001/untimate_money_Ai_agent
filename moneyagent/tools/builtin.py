"""A small set of safe, dependency-light tools.

Safety choices:
  * calculator uses an AST whitelist (no eval of arbitrary code).
  * read_file is sandboxed to a workspace directory.
  * http_get / web_search only allow http(s) and cap the response size.
"""
from __future__ import annotations

import ast
import operator
from pathlib import Path

import requests

from .base import Tool, ToolRegistry

MAX_BYTES = 8000

_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.Mod: operator.mod,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
    ast.FloorDiv: operator.floordiv,
}


def _safe_eval(node):
    if isinstance(node, ast.Expression):
        return _safe_eval(node.body)
    if isinstance(node, ast.Constant):  # numbers only
        if isinstance(node.value, (int, float)):
            return node.value
        raise ValueError("only numbers allowed")
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_safe_eval(node.left), _safe_eval(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_safe_eval(node.operand))
    raise ValueError("unsupported expression")


def calculator(expr: str) -> str:
    try:
        return str(_safe_eval(ast.parse(expr.strip(), mode="eval")))
    except Exception as exc:  # noqa: BLE001 - surface the reason to the agent
        return f"ERROR: {exc}"


def http_get(url: str) -> str:
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        return "ERROR: only http(s) URLs allowed"
    try:
        resp = requests.get(url, timeout=15, headers={"User-Agent": "moneyagent/0.1"})
        text = resp.text[:MAX_BYTES]
        return f"[HTTP {resp.status_code}] {text}"
    except requests.RequestException as exc:
        return f"ERROR: {exc}"


def web_search(query: str) -> str:
    """Lightweight search via DuckDuckGo's HTML endpoint (no API key)."""
    try:
        resp = requests.get(
            "https://duckduckgo.com/html/",
            params={"q": query.strip()},
            timeout=15,
            headers={"User-Agent": "Mozilla/5.0 moneyagent/0.1"},
        )
    except requests.RequestException as exc:
        return f"ERROR: {exc}"
    # Crude extraction of result titles; good enough as agent context.
    import re

    titles = re.findall(r'result__a[^>]*>(.*?)</a>', resp.text)
    cleaned = [re.sub(r"<[^>]+>", "", t).strip() for t in titles[:8]]
    cleaned = [c for c in cleaned if c]
    if not cleaned:
        return "(no results)"
    return "\n".join(f"- {c}" for c in cleaned)


def _make_read_file(workspace: Path):
    workspace = workspace.resolve()

    def read_file(rel_path: str) -> str:
        try:
            target = (workspace / rel_path.strip()).resolve()
            target.relative_to(workspace)  # raises if escaping the sandbox
        except (ValueError, OSError):
            return "ERROR: path outside workspace"
        if not target.is_file():
            return "ERROR: not a file"
        return target.read_text(encoding="utf-8", errors="replace")[:MAX_BYTES]

    return read_file


def default_registry(workspace: Path | None = None, *, allow_network: bool = True) -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(Tool("calculator", "evaluate arithmetic, e.g. '2*(3+4)'", calculator))
    if workspace is not None:
        reg.register(
            Tool("read_file", "read a UTF-8 file by path relative to the workspace",
                 _make_read_file(Path(workspace)))
        )
    if allow_network:
        reg.register(Tool("web_search", "search the web; input is a query string", web_search))
        reg.register(Tool("http_get", "fetch a URL's text; input is an http(s) URL", http_get))
    return reg
