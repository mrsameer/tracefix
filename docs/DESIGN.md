# TraceFix — design

**Problem.** When production throws, an on-call engineer spends most of the incident
turning a stack trace into something actionable: finding the right files in the repo,
working out which commit introduced the regression, writing a reproduction, and only
then fixing it. The reproduction step is the one most often skipped, so the same bug
comes back.

**Solution.** `tracefix run trace.txt --repo ./service` turns a pasted Python
traceback into:

1. **Incident brief** — every frame mapped to a file in the repo with code context.
2. **Suspect commit** — `git blame` on the crashing lines, ranked by recency.
3. **Verified reproduction** — IBM Bob writes a pytest regression test; TraceFix runs
   it and only accepts it if it fails with the *same exception type* raised from the
   *same function* as production. Otherwise the failure is fed back to Bob to retry.
4. **Verified fix** — Bob patches the code; TraceFix accepts the fix only if the
   repro test now passes **and** the full existing suite stays green.
5. **Report** — markdown + HTML report and a git branch ready for a PR.

Bob is driven via the Agent Client Protocol (`bob acp`), so each stage runs in its own
Bob session with full repository context. The verification gates are deterministic
Python — Bob proposes, TraceFix proves.

## Modules

| Module | Responsibility |
| --- | --- |
| `tracefix/trace_parser.py` | Parse CPython tracebacks (incl. chained exceptions) into frames |
| `tracefix/repo_map.py` | Map traceback paths to repo files; extract code context |
| `tracefix/blame.py` | `git blame --porcelain` on crash lines; rank suspect commits |
| `tracefix/bob_acp.py` | ACP client that drives Bob Shell |
| `tracefix/verify.py` | Run pytest, check failure signature matches production |
| `tracefix/pipeline.py` | Orchestrates stages, retries, timing |
| `tracefix/report.py` | Markdown + HTML incident report |
| `tracefix/cli.py` | `tracefix run`, `tracefix analyze` |

## Data model

```python
@dataclass(frozen=True)
class Frame:
    path: str        # path as printed in the traceback
    line: int
    function: str
    code: str        # source line printed in the traceback ('' if absent)

@dataclass(frozen=True)
class ParsedTrace:
    exc_type: str    # e.g. "ZeroDivisionError" (last exception in the chain)
    message: str
    frames: list[Frame]   # outermost first, crash frame last
```
