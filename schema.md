# SCHEMA.md

## Chunk
- id: str
- file_path: str
- start_line: int
- end_line: int
- type: str        # "function" | "class" | "method"
- name: str
- code: str
- embedding: list[float] | None

### Naming Convention for `Chunk.name`

For chunks with a natural identifier (functions, classes, methods), `name` is just that identifier (e.g. `HTTPBasicAuth`, `__call__`).

For findings/chunks without a natural name (e.g. bare `except`, stray `pass`, magic numbers), use the enclosing function/class name plus a bracketed qualifier:

```
<enclosing_scope>[<qualifier>]
```

Examples:
- `HTTPBasicAuth.__call__[bare_except]`
- `Session.rebuild_auth[magic_number]`

If there is no enclosing function/class (module-level code), fall back to the filename:
```
<filename>[<qualifier>]
```
Example: `auth.py[bare_except]`

This keeps `name` descriptive and ties every finding back to the same chunk hierarchy used elsewhere, rather than relying on line numbers alone for context.

## RetrievalResult
- chunk: Chunk
- score: float
- query: str

## AgentResponse
- agent_name: str
- summary: str
- details: dict
- confidence: float | None