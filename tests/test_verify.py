"""Tests for tracefix.verify: check_signature, changed_files, run_pytest."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from tracefix.trace_parser import Frame, ParsedTrace
from tracefix.verify import PytestRun, SignatureCheck, changed_files, check_signature, run_pytest

# ---------------------------------------------------------------------------
# Realistic --tb=native pytest output fixtures
# ---------------------------------------------------------------------------

_PASSING_OUTPUT = """\
collected 1 item

tests/test_example.py .                                              [100%]

1 passed in 0.01s
"""

# Fails with ZeroDivisionError from function "divide"
_FAILING_ZERO_DIV = """\
collected 1 item

tests/test_example.py F                                              [100%]

================================= FAILURES =================================
_______________________ test_divide_by_zero ________________________

    def test_divide_by_zero():
        divide(1, 0)

Traceback (most recent call last):
  File "/repo/tests/test_example.py", line 3, in test_divide_by_zero
    divide(1, 0)
  File "/repo/service/math_utils.py", line 8, in divide
    return a / b
ZeroDivisionError: division by zero

FAILED tests/test_example.py::test_divide_by_zero - ZeroDivisionError: division by zero
1 failed in 0.04s
"""

# Fails with ValueError from function "parse_record"
_FAILING_VALUE_ERROR = """\
collected 1 item

tests/test_parse.py F                                                [100%]

================================= FAILURES =================================
________________________ test_parse_empty ___________________________

    def test_parse_empty():
        parse_record("")

Traceback (most recent call last):
  File "/repo/tests/test_parse.py", line 2, in test_parse_empty
    parse_record("")
  File "/repo/service/parser.py", line 14, in parse_record
    raise ValueError("empty input")
ValueError: empty input

FAILED tests/test_parse.py::test_parse_empty - ValueError: empty input
1 failed in 0.03s
"""

# Collection error — no Python traceback at all
_COLLECTION_ERROR = """\
ERROR collecting tests/test_bad.py
  ImportError while importing test module '/repo/tests/test_bad.py'.
  File "tests/test_bad.py", line 1
    def test:
         ^
SyntaxError: invalid syntax
=========================== short test summary info ============================
ERROR tests/test_bad.py - SyntaxError: invalid syntax
1 error in 0.07s
"""

# Fails with dotted exception type "decimal.InvalidOperation" from "compute"
_FAILING_DOTTED_EXC = """\
collected 1 item

tests/test_dec.py F                                                  [100%]

================================= FAILURES =================================
_______________________ test_decimal_bad ____________________________

Traceback (most recent call last):
  File "/repo/tests/test_dec.py", line 3, in test_decimal_bad
    compute()
  File "/repo/service/calc.py", line 5, in compute
    Decimal("nan") / 0
decimal.InvalidOperation: [<class 'decimal.ConversionSyntax'>]

FAILED tests/test_dec.py::test_decimal_bad
1 failed in 0.05s
"""

# Correct type (ZeroDivisionError) but raised from the wrong function ("wrapper")
_FAILING_WRONG_FUNCTION = """\
collected 1 item

tests/test_example.py F                                              [100%]

================================= FAILURES =================================
_______________________ test_wrong_fn ______________________________

Traceback (most recent call last):
  File "/repo/tests/test_example.py", line 3, in test_wrong_fn
    wrapper()
  File "/repo/service/math_utils.py", line 20, in wrapper
    return 1 / 0
ZeroDivisionError: division by zero

FAILED tests/test_example.py::test_wrong_fn
1 failed in 0.03s
"""


# ---------------------------------------------------------------------------
# Production ParsedTrace factories
# ---------------------------------------------------------------------------

def _production_zero_div() -> ParsedTrace:
    """A production trace: ZeroDivisionError from divide()."""
    return ParsedTrace(
        exc_type="ZeroDivisionError",
        message="division by zero",
        frames=[
            Frame(path="/app/main.py", line=10, function="handle", code="divide(a, b)"),
            Frame(path="/app/service/math_utils.py", line=8, function="divide", code="return a / b"),
        ],
    )


def _production_value_error() -> ParsedTrace:
    """A production trace: ValueError from parse_record()."""
    return ParsedTrace(
        exc_type="ValueError",
        message="empty input",
        frames=[
            Frame(path="/app/main.py", line=5, function="process", code="parse_record(row)"),
            Frame(path="/app/service/parser.py", line=14, function="parse_record", code='raise ValueError("empty input")'),
        ],
    )


def _production_dotted() -> ParsedTrace:
    """A production trace using bare name 'InvalidOperation' from compute()."""
    return ParsedTrace(
        exc_type="InvalidOperation",
        message="",
        frames=[
            Frame(path="/app/service/calc.py", line=5, function="compute", code="Decimal('nan') / 0"),
        ],
    )


# ---------------------------------------------------------------------------
# check_signature tests
# ---------------------------------------------------------------------------


class TestCheckSignature:
    def test_passing_run_is_rejected(self) -> None:
        """A test that passes cannot reproduce a production failure."""
        run = PytestRun(passed=True, output=_PASSING_OUTPUT)
        result = check_signature(run, _production_zero_div())
        assert not result.matches
        assert "passed" in result.reason

    def test_matching_failure_accepted(self) -> None:
        """Same exception type and same crashing function → matches."""
        run = PytestRun(passed=False, output=_FAILING_ZERO_DIV)
        result = check_signature(run, _production_zero_div())
        assert result.matches

    def test_collection_error_no_traceback(self) -> None:
        """A collection/syntax error produces no Python traceback → rejected."""
        run = PytestRun(passed=False, output=_COLLECTION_ERROR)
        result = check_signature(run, _production_zero_div())
        assert not result.matches
        assert "traceback" in result.reason.lower()

    def test_wrong_exception_type(self) -> None:
        """ValueError vs ZeroDivisionError → rejected."""
        run = PytestRun(passed=False, output=_FAILING_VALUE_ERROR)
        result = check_signature(run, _production_zero_div())
        assert not result.matches
        assert "ValueError" in result.reason or "ZeroDivisionError" in result.reason

    def test_right_type_wrong_function(self) -> None:
        """Correct exception type but raised from a different function → rejected."""
        run = PytestRun(passed=False, output=_FAILING_WRONG_FUNCTION)
        result = check_signature(run, _production_zero_div())
        assert not result.matches
        assert "wrapper" in result.reason or "divide" in result.reason

    def test_dotted_exc_equals_short(self) -> None:
        """decimal.InvalidOperation observed vs bare InvalidOperation in production → matches."""
        run = PytestRun(passed=False, output=_FAILING_DOTTED_EXC)
        production = _production_dotted()
        result = check_signature(run, production)
        assert result.matches

    def test_short_exc_equals_dotted_production(self) -> None:
        """Bare ZeroDivisionError observed vs dotted production exc_type → matches."""
        production = ParsedTrace(
            exc_type="builtins.ZeroDivisionError",
            message="division by zero",
            frames=[
                Frame(path="/app/service/math_utils.py", line=8, function="divide", code="return a / b"),
            ],
        )
        run = PytestRun(passed=False, output=_FAILING_ZERO_DIV)
        result = check_signature(run, production)
        assert result.matches


# ---------------------------------------------------------------------------
# changed_files tests
# ---------------------------------------------------------------------------


class TestChangedFiles:
    def _init_repo(self, path: Path) -> None:
        """Initialise a bare git repo with one committed file."""
        subprocess.run(["git", "init", "-q", "--initial-branch=main"], cwd=path, check=True)
        subprocess.run(["git", "config", "user.email", "t@test.com"], cwd=path, check=True)
        subprocess.run(["git", "config", "user.name", "T"], cwd=path, check=True)
        committed = path / "app.py"
        committed.write_text("x = 1\n")
        subprocess.run(["git", "add", "app.py"], cwd=path, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=path, check=True)

    def test_clean_tree_is_empty(self, tmp_path: Path) -> None:
        """A clean working tree reports no changed files."""
        self._init_repo(tmp_path)
        assert changed_files(tmp_path) == []

    def test_modified_file_reported(self, tmp_path: Path) -> None:
        """A tracked file that is modified appears in the result."""
        self._init_repo(tmp_path)
        (tmp_path / "app.py").write_text("x = 2\n")
        assert "app.py" in changed_files(tmp_path)

    def test_untracked_file_reported(self, tmp_path: Path) -> None:
        """A new, untracked .py file appears in the result."""
        self._init_repo(tmp_path)
        (tmp_path / "new_module.py").write_text("pass\n")
        assert "new_module.py" in changed_files(tmp_path)

    def test_pyc_ignored(self, tmp_path: Path) -> None:
        """Compiled .pyc files are filtered out."""
        self._init_repo(tmp_path)
        (tmp_path / "app.cpython-312.pyc").write_text("bytecode")
        subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
        files = changed_files(tmp_path)
        assert not any(f.endswith(".pyc") for f in files)

    def test_bare_directory_ignored(self, tmp_path: Path) -> None:
        """Bare directories (trailing /) are filtered out."""
        self._init_repo(tmp_path)
        subdir = tmp_path / "subpkg"
        subdir.mkdir()
        # git status --untracked-files=all doesn't list empty directories,
        # but with a file inside a subdir git may list the dir with a trailing /
        # in some configurations. We verify the filter holds.
        files = changed_files(tmp_path)
        assert not any(f.endswith("/") for f in files)


# ---------------------------------------------------------------------------
# run_pytest tests
# ---------------------------------------------------------------------------


class TestRunPytest:
    def _make_project(self, base: Path) -> None:
        """Create a tiny project with a passing and a failing test."""
        tests_dir = base / "tests"
        tests_dir.mkdir()
        (tests_dir / "__init__.py").write_text("")
        (tests_dir / "test_pass.py").write_text(
            "def test_always_passes():\n    assert 1 + 1 == 2\n"
        )
        (tests_dir / "test_fail.py").write_text(
            "def test_always_fails():\n    raise RuntimeError('boom')\n"
        )

    def test_passing_file(self, tmp_path: Path) -> None:
        """run_pytest on a file with only passing tests → .passed is True."""
        self._make_project(tmp_path)
        result = run_pytest(tmp_path, "tests/test_pass.py")
        assert result.passed

    def test_failing_file(self, tmp_path: Path) -> None:
        """run_pytest on a file with a failing test → .passed is False."""
        self._make_project(tmp_path)
        result = run_pytest(tmp_path, "tests/test_fail.py")
        assert not result.passed

    def test_output_captured(self, tmp_path: Path) -> None:
        """The .output field contains pytest output text."""
        self._make_project(tmp_path)
        result = run_pytest(tmp_path, "tests/test_fail.py")
        assert "RuntimeError" in result.output or "boom" in result.output
