"""
Import Resolver – maps local names to their fully-qualified module origins.

Resolves every ``import`` and ``from … import`` statement in a Python source
string into a symbol table so that downstream security scanners can determine,
for example, that a bare call to ``loads()`` actually refers to
``pickle.loads``.

Usage::

    table = resolve_imports("from pickle import loads")
    module, func = resolve_call_target("loads", "", table)
    # module == "pickle", func == "loads"
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Dict, Tuple

__all__ = [
    "ResolvedSymbol",
    "ImportResolver",
    "resolve_imports",
    "resolve_call_target",
]


# ---------------------------------------------------------------------------
# Data Model
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ResolvedSymbol:
    """A single resolved import symbol.

    Attributes:
        local_name:    The name used in code (e.g. ``pk`` after
                       ``import pickle as pk``).
        full_module:   The fully-qualified module path (e.g. ``pickle``).
        original_name: The original exported name before aliasing
                       (e.g. ``pickle`` for a plain module import, or
                       ``loads`` for ``from pickle import loads``).
        is_aliased:    ``True`` when an ``as`` clause was used.
    """

    local_name: str
    full_module: str
    original_name: str
    is_aliased: bool

    # Sentinel value used when ``from X import *`` is encountered.
    WILDCARD: str = "*"


# ---------------------------------------------------------------------------
# AST Visitor
# ---------------------------------------------------------------------------

class ImportResolver(ast.NodeVisitor):
    """Walk an AST and collect every import into a symbol table.

    Handles all standard import forms:

    * ``import os``
    * ``import os as operating_system``
    * ``from os import system``
    * ``from os import system as sys_exec``
    * ``from os.path import join``
    * ``from . import module``  (relative imports)
    * ``import pickle, json``   (multi-imports)
    * ``from x import *``       (star / wildcard imports)
    """

    def __init__(self) -> None:
        self.symbols: dict[str, ResolvedSymbol] = {}

    # -- import X, import X as Y, import A, B --------------------------

    def visit_Import(self, node: ast.Import) -> None:  # noqa: N802
        for alias in node.names:
            module_path: str = alias.name          # e.g. "os.path"
            local_name: str = alias.asname or alias.name
            is_aliased: bool = alias.asname is not None

            self.symbols[local_name] = ResolvedSymbol(
                local_name=local_name,
                full_module=module_path,
                original_name=alias.name,
                is_aliased=is_aliased,
            )
        self.generic_visit(node)

    # -- from X import Y, from X import Y as Z, from X import * -------

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:  # noqa: N802
        # Determine the module path.  For relative imports the ``module``
        # attribute may be ``None`` (e.g. ``from . import foo``).
        level: int = node.level or 0
        base_module: str = node.module or ""

        # Represent relative-import dots as leading dots in the path so
        # callers can still pattern-match against them.
        prefix: str = "." * level
        full_module: str = f"{prefix}{base_module}" if prefix else base_module

        for alias in node.names:
            if alias.name == "*":
                # Star import – record a wildcard sentinel so callers know
                # that *any* name could originate from this module.
                self.symbols[ResolvedSymbol.WILDCARD] = ResolvedSymbol(
                    local_name=ResolvedSymbol.WILDCARD,
                    full_module=full_module,
                    original_name=ResolvedSymbol.WILDCARD,
                    is_aliased=False,
                )
                continue

            local_name = alias.asname or alias.name
            is_aliased = alias.asname is not None

            self.symbols[local_name] = ResolvedSymbol(
                local_name=local_name,
                full_module=full_module,
                original_name=alias.name,
                is_aliased=is_aliased,
            )
        self.generic_visit(node)

    # -- public helpers ------------------------------------------------

    def get_symbol_table(self) -> dict[str, ResolvedSymbol]:
        """Return a *copy* of the collected symbol table."""
        return dict(self.symbols)


# ---------------------------------------------------------------------------
# Public convenience API
# ---------------------------------------------------------------------------

def resolve_imports(code_text: str) -> dict[str, ResolvedSymbol]:
    """Parse *code_text* and return a mapping of ``local_name → ResolvedSymbol``.

    Example::

        table = resolve_imports("from pickle import loads")
        # table == {
        #     "loads": ResolvedSymbol("loads", "pickle", "loads", False)
        # }

    Raises:
        SyntaxError: If *code_text* is not valid Python.
    """
    tree = ast.parse(code_text)
    resolver = ImportResolver()
    resolver.visit(tree)
    return resolver.get_symbol_table()


def resolve_call_target(
    call_name: str,
    module_name: str,
    symbol_table: dict[str, ResolvedSymbol],
) -> tuple[str, str]:
    """Resolve an observed call site to its fully-qualified origin.

    Parameters:
        call_name:    The function/attribute being called (e.g. ``"loads"``).
        module_name:  The object it was called on, if any (e.g. ``"pk"`` in
                      ``pk.loads(…)``).  Pass ``""`` for bare calls.
        symbol_table: A table previously produced by :func:`resolve_imports`.

    Returns:
        A ``(resolved_module, resolved_function)`` 2-tuple.

        * For ``loads()`` when ``from pickle import loads`` is in scope →
          ``("pickle", "loads")``.
        * For ``pk.loads()`` when ``import pickle as pk`` is in scope →
          ``("pickle", "loads")``.
        * If neither ``call_name`` nor ``module_name`` are found in the
          table the original values are returned unchanged.

    Examples::

        table = resolve_imports("import pickle as pk")
        resolve_call_target("loads", "pk", table)
        # → ("pickle", "loads")

        table = resolve_imports("from pickle import loads")
        resolve_call_target("loads", "", table)
        # → ("pickle", "loads")
    """

    # Case 1: attribute call – e.g. ``module_name.call_name(…)``
    if module_name:
        sym = symbol_table.get(module_name)
        if sym is not None:
            return sym.full_module, call_name
        # ``module_name`` not in the table – fall through to return as-is.
        return module_name, call_name

    # Case 2: bare call – e.g. ``call_name(…)``
    sym = symbol_table.get(call_name)
    if sym is not None:
        # The symbol came from a ``from X import Y`` form.
        return sym.full_module, sym.original_name

    # Not found in the symbol table – return unchanged.
    return module_name, call_name
