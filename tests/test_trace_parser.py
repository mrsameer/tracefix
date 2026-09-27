"""Tests for tracefix.trace_parser."""

from __future__ import annotations

import pytest

from tracefix.trace_parser import Frame, ParsedTrace, parse_traceback


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SIMPLE_TB = """\
Traceback (most recent call last):
  File "/app/service/main.py", line 42, in handle
    result = compute(x)
  File "/app/service/compute.py", line 7, in compute
    return 1 / x
ZeroDivisionError: division by zero
"""

NOISY_TB = """\
2024-01-01 INFO starting
2024-01-01 INFO request received
Traceback (most recent call last):
  File "/app/service/main.py", line 42, in handle
    result = compute(x)
ZeroDivisionError: division by zero
2024-01-01 ERROR sent to Sentry
"""

CHAINED_TB = """\
Traceback (most recent call last):
  File "/app/a.py", line 1, in outer
    inner()
ValueError: original error

During handling of the above exception, another exception occurred:

Traceback (most recent call last):
  File "/app/b.py", line 5, in inner
    raise RuntimeError("wrapped") from e
RuntimeError: wrapped
"""

CHAINED_CAUSE_TB = """\
Traceback (most recent call last):
  File "/app/a.py", line 1, in outer
    inner()
ValueError: original error

The above exception was the direct cause of the following exception:

Traceback (most recent call last):
  File "/app/b.py", line 5, in inner
    raise RuntimeError("cause") from e
RuntimeError: cause
"""

MISSING_SOURCE_TB = """\
Traceback (most recent call last):
  File "/app/service/main.py", line 42, in handle
KeyError: 'missing'
"""

CARET_TB = """\
Traceback (most recent call last):
  File "/app/service/main.py", line 42, in handle
    result = compute(x)
             ^^^^^^^^^^
  File "/app/service/compute.py", line 7, in compute
    return 1 / x
           ~~~~~^
ZeroDivisionError: division by zero
"""

BARE_EXC_TB = """\
Traceback (most recent call last):
  File "/app/main.py", line 1, in run
    do_it()
SystemExit
"""

DOTTED_EXC_TB = """\
Traceback (most recent call last):
  File "/app/main.py", line 3, in run
    Decimal("nan") / 0
decimal.InvalidOperation: [<class 'decimal.ConversionSyntax'>]
"""


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSimpleTraceback:
    def test_exc_type(self) -> None:
        pt = parse_traceback(SIMPLE_TB)
        assert pt.exc_type == "ZeroDivisionError"

    def test_message(self) -> None:
        pt = parse_traceback(SIMPLE_TB)
        assert pt.message == "division by zero"

    def test_frame_count(self) -> None:
        pt = parse_traceback(SIMPLE_TB)
        assert len(pt.frames) == 2

    def test_first_frame(self) -> None:
        pt = parse_traceback(SIMPLE_TB)
        f = pt.frames[0]
        assert f.path == "/app/service/main.py"
        assert f.line == 42
        assert f.function == "handle"
        assert f.code == "result = compute(x)"

    def test_last_frame(self) -> None:
        pt = parse_traceback(SIMPLE_TB)
        f = pt.frames[-1]
        assert f.path == "/app/service/compute.py"
        assert f.line == 7
        assert f.code == "return 1 / x"


class TestNoisyLog:
    def test_noise_before_is_ignored(self) -> None:
        pt = parse_traceback(NOISY_TB)
        assert pt.exc_type == "ZeroDivisionError"
        assert len(pt.frames) == 1

    def test_noise_after_is_ignored(self) -> None:
        pt = parse_traceback(NOISY_TB)
        assert pt.message == "division by zero"


class TestChainedExceptions:
    def test_during_handling_uses_last(self) -> None:
        pt = parse_traceback(CHAINED_TB)
        assert pt.exc_type == "RuntimeError"
        assert pt.message == "wrapped"
        assert pt.frames[-1].path == "/app/b.py"

    def test_direct_cause_uses_last(self) -> None:
        pt = parse_traceback(CHAINED_CAUSE_TB)
        assert pt.exc_type == "RuntimeError"
        assert pt.message == "cause"


class TestEdgeCases:
    def test_missing_source_line(self) -> None:
        pt = parse_traceback(MISSING_SOURCE_TB)
        assert pt.frames[0].code == ""

    def test_caret_lines_skipped(self) -> None:
        pt = parse_traceback(CARET_TB)
        assert pt.exc_type == "ZeroDivisionError"
        assert len(pt.frames) == 2
        assert pt.frames[0].code == "result = compute(x)"
        assert pt.frames[1].code == "return 1 / x"

    def test_bare_exception_no_message(self) -> None:
        pt = parse_traceback(BARE_EXC_TB)
        assert pt.exc_type == "SystemExit"
        assert pt.message == ""

    def test_dotted_exc_type(self) -> None:
        pt = parse_traceback(DOTTED_EXC_TB)
        assert pt.exc_type == "decimal.InvalidOperation"

    def test_no_traceback_raises(self) -> None:
        with pytest.raises(ValueError, match="No traceback"):
            parse_traceback("just some log text\nnothing here\n")

    def test_multiple_tracebacks_uses_last(self) -> None:
        two = SIMPLE_TB + "\n" + NOISY_TB
        pt = parse_traceback(two)
        # The last traceback is from NOISY_TB which has 1 frame
        assert len(pt.frames) == 1
