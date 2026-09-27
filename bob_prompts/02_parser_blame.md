You are helping build TraceFix (read docs/DESIGN.md first — it defines the Frame and ParsedTrace dataclasses you must use exactly).

Implement these modules (Python 3.11+, stdlib only, full type hints, docstrings on public functions, small focused functions, max line length 88):

1. `tracefix/trace_parser.py`
   - `parse_traceback(text: str) -> ParsedTrace`: find the LAST "Traceback (most recent call last):" block in arbitrary log text (log lines before/after are noise). Handle chained exceptions ("During handling of the above exception..." and "The above exception was the direct cause...") by using the final exception. Parse `File "path", line N, in func` plus the following indented source line (may be absent). Handle Python 3.11+ caret lines (`^^^^` / `~~~^^^`) by skipping them. Exception line may be `module.sub.ErrorType: message`, `ErrorType: message`, or just `ErrorType`; exc_type should be the bare class name (e.g. `decimal.DivisionByZero` -> keep full dotted name in a separate field? NO — keep ParsedTrace as designed: exc_type = text before the first ':' stripped, message = rest). Raise `ValueError` if no traceback is found.

2. `tracefix/repo_map.py`
   - `@dataclass(frozen=True) class MappedFrame: frame: Frame; repo_path: str | None; context: str` (context = up to 5 lines before and 2 after the line, prefixed with line numbers, crash line marked with `>`).
   - `map_frames(trace: ParsedTrace, repo: Path) -> list[MappedFrame]`: map each traceback path to a file tracked in the repo by longest path-suffix match against `git ls-files` output (e.g. `/srv/app/shopcart/loyalty.py` -> `shopcart/loyalty.py`). Frames from site-packages / stdlib that don't match are kept with repo_path None and empty context.

3. `tracefix/blame.py`
   - `@dataclass(frozen=True) class BlameHit: sha: str; author: str; author_time: int; summary: str; path: str; line: int; code: str`
   - `blame_lines(repo: Path, path: str, start: int, end: int) -> list[BlameHit]` using `git blame --porcelain -L start,end -- path` (parse porcelain correctly; header info is only emitted once per commit).
   - `suspect_commits(repo: Path, frames: list[MappedFrame], window: int = 3) -> list[tuple[BlameHit, float]]`: blame ±window lines around each in-repo frame's line, score each commit (crash frame hits weigh 3x, the exact crash line 5x, more recent = higher), return unique commits sorted by score descending.

4. Tests in `tests/test_trace_parser.py`, `tests/test_repo_map.py`, `tests/test_blame.py` using pytest. For repo_map and blame, build a tiny temporary git repo in a fixture (`tmp_path`, `subprocess.run(["git", ...])` with author env vars) — do not depend on anything outside the test. Cover: noise before trace, chained exceptions, missing source lines, caret lines, bare exception without message, no traceback -> ValueError, porcelain parsing with repeated commits, suspect ranking puts the commit touching the crash line first.

The project uses uv: there is (or create) a `pyproject.toml` with project name `tracefix`, requires-python >=3.11, a `[project.scripts] tracefix = "tracefix.cli:main"` entry, and pytest as a dev dependency (`uv add --dev pytest`). Do NOT use pip. Run `uv run pytest -q` and make everything pass. Do not modify `tracefix/bob_acp.py`. Keep your final answer short: files created and test results.
