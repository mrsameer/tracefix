"""Prompts TraceFix sends to IBM Bob. Each one carries the incident brief."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tracefix.pipeline import Incident


PYTEST = f"{sys.executable} -m pytest"


def incident_brief(incident: Incident) -> str:
    """Render the deterministic analysis as context for Bob."""
    trace = incident.trace
    lines = [
        f"Production exception: {trace.exc_type}: {trace.message}",
        "",
        "Stack frames (outermost first) mapped to this repository:",
    ]
    for mapped in incident.frames:
        frame = mapped.frame
        where = mapped.repo_path or f"{frame.path} (outside repo)"
        lines.append(f"- {where}:{frame.line} in {frame.function}()")
        if mapped.context:
            lines.append(_indent(mapped.context))
    if incident.suspects:
        lines += ["", "Suspect commits from git blame on the crash lines:"]
        for hit, score in incident.suspects[:3]:
            lines.append(
                f'- {hit.sha[:8]} "{hit.summary}" by {hit.author} ({score:.0f}% of blame weight)'
            )
    return "\n".join(lines)


def repro_prompt(incident: Incident, test_path: str) -> str:
    """Ask Bob to write a failing regression test that mirrors production."""
    return f"""You are the reproduction stage of TraceFix, an incident-response tool.

{incident_brief(incident)}

Your job: create `{test_path}` containing ONE pytest test that reproduces this
production failure through the outermost in-repo entry point (not by calling the
crashing line directly), using realistic input that explains what the user did.

Rules:
- Do NOT modify any file other than `{test_path}`. Do not fix the bug.
- The test must FAIL today by raising {incident.trace.exc_type} from
  `{incident.trace.frames[-1].function}()`. Do not catch the exception or use
  pytest.raises: the test should assert the correct, desired behaviour so it will
  pass once the bug is fixed.
- Name the test after the behaviour, and add a docstring explaining the scenario and
  referencing incident {incident.incident_id}.
- Run `{PYTEST} -q {test_path}` yourself to confirm it fails the right way.
Finish with a two-sentence summary of the root cause you believe caused this."""


def fix_prompt(incident: Incident, test_path: str) -> str:
    """Ask Bob to fix the root cause without touching the regression test."""
    return f"""You are the fix stage of TraceFix, an incident-response tool.

{incident_brief(incident)}

A verified reproduction lives in `{test_path}` and currently fails exactly like
production. Fix the ROOT CAUSE in the application code so that:
- `{test_path}` passes (you must NOT edit it),
- the whole existing test suite still passes (`{PYTEST} -q`),
- the change is minimal and matches the surrounding code style; keep the intent of
  the suspect commit (e.g. if it was a performance change, keep it and guard the edge
  case rather than reverting it wholesale).
Run the full suite yourself before finishing. Finish with a two-sentence summary
of the fix suitable for a pull request description."""


def retry_prompt(detail: str) -> str:
    """Feed a failed verification back to Bob."""
    return f"""TraceFix verification REJECTED your last change:

{detail[:4000]}

Please correct it and verify again."""


def _indent(text: str) -> str:
    return "\n".join(f"    {line}" for line in text.splitlines())
