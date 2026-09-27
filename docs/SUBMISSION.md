# TraceFix — lablab.ai submission kit

## Project title
TraceFix — Paste a stack trace. Get a proven fix.

## Short description
TraceFix turns a production stack trace into a verified failing regression test, the
suspect commit, and a verified fix in under a minute. IBM Bob writes the code;
deterministic pytest gates prove every change before it is accepted.

## Technology & category tags
IBM Bob · Agent Client Protocol · Python · pytest · git · Developer Tools · Debugging ·
Testing · Incident Response · AI Agents

## Links
- Repository: https://github.com/mrsameer/tracefix
- Application (live site): https://mrsameer.github.io/tracefix/
- Real run replay: https://mrsameer.github.io/tracefix/demo.html
- Incident report: https://mrsameer.github.io/tracefix/report.html
- Demo platform: Web (GitHub Pages) + CLI (macOS/Linux, Python 3.11)

---

## Problem & Solution Statement

**The problem.** When a production service throws, the on-call engineer usually starts
with nothing but a stack trace. Turning it into a fix is slow, manual work. You map
paths like `/srv/app/shopcart/loyalty.py` to files in the repository, work out which
recent commit introduced the regression, write a test that reproduces the failure, and
only then write and verify a fix, often at 3 a.m. and under pressure. The reproduction
step is the one most often skipped. Without it, the fix is a guess, nothing stops the
bug from returning, and the incident takes longer than it should. AI assistants can
suggest fixes, but a fix nobody has verified is a new risk in production.

**The solution.** TraceFix is a command-line tool that automates the whole path from
stack trace to proven fix: `tracefix run trace.txt --repo ./service`. It combines
deterministic analysis with IBM Bob, and it never accepts Bob's output without proof:

1. **Parse and map.** It finds the traceback in noisy logs (chained exceptions,
   Python 3.11 caret lines) and maps every frame to a tracked file, with code context.
2. **Blame.** It runs `git blame` around the crash lines and ranks the commits most
   likely to have caused the regression.
3. **Reproduce (Bob).** Bob writes a pytest regression test through the public entry
   point. TraceFix accepts it only if it fails with the *same exception type* raised
   from the *same function* as production, and no other file was touched.
4. **Fix (Bob).** A fresh Bob session fixes the root cause. TraceFix accepts the fix
   only if the reproduction now passes, the full existing suite stays green, and the
   test was not edited.
5. **Ship.** It creates an incident branch with two commits (test, then fix), plus
   HTML, Markdown and JSON reports. The Markdown doubles as the pull request
   description.

When a gate rejects a change, the exact pytest evidence goes back to the same Bob
session for another attempt. With `--agents N`, TraceFix races several Bob agents in
isolated git worktrees with different strategies. The first verified patch wins and
the remaining sessions are cancelled.

**Impact.** On the demo service, TraceFix went from stack trace to verified fix in
**36 seconds** for a `ZeroDivisionError` introduced by a performance commit, and in
**47 seconds** for a `KeyError` in a new stacked-coupons feature, with two agents
racing. In both cases the true regression commit ranked first. Bob's fixes were
minimal and kept the intent of the original change (the optimisation stayed and the
edge case was guarded). Every incident leaves behind a regression test built from the
real production failure. Because every AI-written change passes machine-checked gates,
TraceFix makes AI help something a team can trust, review and audit. That means
shorter incidents, fewer repeat bugs and safer adoption of AI in production work.

---

## IBM Bob Usage Statement

We used IBM Bob in two roles: as a **developer that built TraceFix**, and as the
**engine that runs inside TraceFix**.

**Bob as builder.** We wrote precise task prompts (committed in `bob_prompts/`) and
sent them to Bob in Agent mode, with the repository as context. Bob planned each task
with its todo list, read our design document, wrote code, ran the tests itself and
fixed its own failures. Three Bob task sessions produced a large part of the codebase:

- **Session 01 (demo service):** Bob wrote `examples/build_demo_repo.py`, which
  generates a realistic e-commerce service with a five-commit git history, several
  authors, and a regression introduced by a performance commit. Bob also wrote the
  production traceback and checked its line numbers by reproducing the crash
  (34 tool calls).
- **Session 02 (analysis core):** Bob implemented the traceback parser (chained
  exceptions, Python 3.11 carets, log noise), the repository mapper (longest path-suffix
  matching against `git ls-files`), and the `git blame --porcelain` parser with weighted
  suspect ranking, plus 38 tests. Along the way it found and fixed a bug in its own
  parser.
- **Session 03 (test suite):** Bob wrote 47 unit tests for our verification gates,
  report generation and prompts, bringing the suite to 85 passing tests.

The full event stream of every session is committed in `bob_sessions/`, and the
screenshots show each session's summary in Bob Shell, including tokens and Bobcoin
cost.

**Bob as engine.** TraceFix drives Bob Shell programmatically over the **Agent Client
Protocol** (`bob acp`). We wrote a small ACP client, so no API key is needed; it reuses
the developer's Bob SSO login. For each incident TraceFix opens Bob sessions with full
repository context. In the reproduction stage Bob explores the code and existing tests,
writes `tests/test_tracefix_repro.py`, and runs pytest itself. In the fix stage a fresh
session applies a minimal diff and re-runs the whole suite. TraceFix streams Bob's tool
calls live and then independently checks the result with deterministic gates. If a gate
rejects the work, the evidence is sent back to the same Bob session to correct it. In
our first run, Bob's reproduction was rejected for touching extra files, and Bob fixed
it on the next attempt.

We also used Bob's ability to run **parallel tasks**. With `--agents N`, TraceFix
starts several Bob sessions at once, each in its own git worktree with a different
strategy hint. The first verified result wins, and the others are stopped with ACP
`session/cancel`.

Bob was essential to both building and running TraceFix. Bob does the creative
engineering work, and TraceFix supplies the proof.
