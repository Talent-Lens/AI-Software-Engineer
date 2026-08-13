# SCHEMA.md

## Target repo (Day 0)
We're using `psf/requests` (github.com/psf/requests) as our sample repo to index/test against.
Cloned locally at: D:\test-repos\requests

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

**Boundary rule:** only findings without a natural standalone name use the bracket convention below. `function`, `method`, and `class` chunks already have real, unique identifiers (e.g. `Session.get`, `HTTPBasicAuth`) — they are exempt and never get a bracket suffix.

For findings/chunks without a natural name (e.g. bare `except`, no-arg calls, magic numbers), use the enclosing function/class name plus a bracketed qualifier:

```
<enclosing_scope>[<type>]              # no extra detail to carry
<enclosing_scope>[<type>:<detail>]     # type carries a specific detail
```

Whether a type uses `[<type>]` or `[<type>:<detail>]` depends on whether that finding type has something more specific to say beyond its category:

| Type | Has detail? | Format |
|---|---|---|
| `bare_except` | no — nothing more specific to say | `[bare_except]` |
| `noarg_call` | yes — the call target (`close`, `copy`, etc.) | `[noarg_call:close]` |
| `magic_number` (hypothetical) | yes — the number itself | `[magic_number:42]` |

Examples:
- `HTTPBasicAuth.__call__[bare_except]`
- `Session.request[noarg_call:close]`
- `Session.rebuild_auth[magic_number:42]`

If there is no enclosing function/class (module-level code), fall back to the filename:
```
<filename>[<type>]
<filename>[<type>:<detail>]
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