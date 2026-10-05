# Verification Gap: Evidence Log

## The problem found
The agent loop marked a patch as `ACCEPTED` even though the model's patch was
identical to the original code. The model claimed it had added docstrings, but
the code never changed. The old `apply_and_test` only checked syntax validity
(and pytest, only if a `test_dir` was passed). It never checked whether the
flagged issue was actually fixed.

## BEFORE the fix (`python test_step5.py`, old `sandbox/verify.py`)

Static analysis flagged: `missing-module-docstring`, `missing-function-docstring`.

The model proposed a patch three times. Every patch was identical to the original:

```python
def calc(a, b, c):
    x = a + b
    y = x * c
    return y
```

No docstring was added in any attempt. Despite that, the model wrote:

> "The proposed patch includes both the module and function docstrings, which
> should improve the readability and maintainability of the code."

That claim was false. The verifier then returned:

```
Action: apply_and_test
Observation: {'status': 'ACCEPTED'}
```

Result: a hallucinated fix passed verification.
Runtime: 8 model calls, about 7-8 minutes (qwen-refactor-7b, CPU only).

## THE FIX
`sandbox/verify.py` now has extra checks:
1. Reject if the patched code is identical to the original (`no_change`).
2. If the target issue is known, re-run `static_analysis` on the patched code and
   reject if that same issue is still present (`issue_not_fixed`).

`agent/loop.py` now remembers the issue from the last `propose_patch` call and
passes it to `apply_and_test` as `target_issue`.

## AFTER the fix

### Deterministic test (`python test_verify_gap.py`, no LLM involved)

```
[PASS] 1. Identical patch (the original bug) is rejected
       got {'status': 'REJECTED', 'reason': 'no_change', ...}
[PASS] 2. Changed code that does NOT fix the issue is rejected
       got {'status': 'REJECTED', 'reason': 'issue_not_fixed', ...}
[PASS] 3. A real docstring fix is accepted
       got {'status': 'ACCEPTED'}

3/3 checks passed
```

### Live agent run (`python test_step5.py`, new verifier)
The model proposed two patches, both identical to the original, then chose
`finish` without calling `apply_and_test`. No false ACCEPTED occurred, but the
verifier was not exercised in this run. No fix was produced.

## Conclusion
- The verifier now rejects both no-op patches and patches that leave the flagged
  issue in place, and still accepts genuine fixes (3/3 deterministic checks).
- Remaining weakness: the patch-generation step (`propose_patch`) does not
  reliably produce a change for convention issues such as missing docstrings.
  The model rationalizes that no code change is needed. Next step: tighten the
  patcher prompt.

---

## UPDATE: final result after all fixes (full agent run, `python test_step5.py`)

Both issues on the `calc` example were fixed, and every claim the model made was checked by the pipeline:

1. Static analysis found 2 issues (`missing-module-docstring`, `missing-function-docstring`).
2. The model proposed a patch that added only the module docstring. The verifier
   accepted it as a partial fix and reported `remaining_issues: ['missing-function-docstring']`.
3. The model then wrote "There are no remaining issues" and called `finish`.
   **The finish guard refused**: `NOT FINISHED: static analysis still reports 1 issue(s):
   ['missing-function-docstring']`.
4. The model proposed a second patch. It was built on top of the accepted first patch
   (module docstring kept, function docstring added) and the verifier returned
   `{'status': 'ACCEPTED', 'remaining_issues': []}`.
5. The model called `finish` and the guard allowed it.

Runtime: 11 model calls, about 16 minutes (CPU only, qwen-refactor-7b / qwen-baseline-7b).

### What the pipeline now guarantees (all found by testing, not assumed)
| Model behaviour observed | Caught by |
|---|---|
| Claimed a fix but returned identical code | `no_change` check |
| Renamed a function while "fixing" | `definition_removed` check |
| Changed code but left the flagged issue | `issue_not_fixed` check |
| Rewrote code without reducing findings | `no_improvement` check |
| Claimed "no remaining issues" while one remained | finish guard |

### Known limitation
Model calls on a CPU-only laptop take 15-170 seconds each. The orchestration model
(qwen-refactor-7b) is the slow part (about 100 s per call); the patcher (qwen-baseline-7b)
takes 15-35 s. Files with many findings need a per-file cap on issues attempted.

---

## UPDATE: real multi-issue file, fully fixed (`test_diagnostic.py` on `buggy_math.py`)

After the newline-normalization consistency fix and the auto-fix pre-pass were
added to `loop.py`/`verify.py`, the agent was run on a real file with 5 pylint
findings (1 module docstring, 3 function docstrings, all `convention`-level).

**Result: all 5 issues resolved, verified, and accepted. Runtime: ~30 minutes
(12 model calls: 8 x qwen-refactor-7b, 4 x qwen-baseline-7b).**

Sequence:
1. `static_analysis` found all 4 distinct findings (module docstring + 3 function
   docstrings; pylint reports 5 total across lines).
2. The model proposed a module-docstring patch, then (confusingly) proposed the
   *same* module-docstring patch twice more while narrating that it was "adding
   function docstrings" — it was not; the code was unchanged each time.
3. On the 4th patch attempt, the model finally added real function docstrings
   to all three functions in a single patch.
4. `apply_and_test` accepted this patch: `{'status': 'ACCEPTED',
   'remaining_issues': ['missing-function-docstring', 'missing-function-docstring',
   'missing-function-docstring']}` — i.e. it correctly identified this as only a
   **partial** fix (module docstring only), matching the code that was actually
   submitted at that step, not the model's claim.
5. The model then proposed a further patch with per-function docstrings, which
   was accepted: `{'status': 'ACCEPTED', 'remaining_issues': []}`.
6. `finish` was accepted, since no issues remained.

### A parsing failure the pipeline recovered from automatically
Across several steps, the model's `Action Input` was badly malformed — it
repeatedly stringified its own JSON inside itself (visible as nested `_raw`
keys, several levels deep, in the raw log). Despite this, `_resolve_issue()` in
`agent/loop.py` did not rely on the malformed structure: it matched the intended
issue against the real static-analysis findings by line number, so the correct
docstring got targeted and verified even though the model's own output format
broke down. This is a second, independent example of why grounding + verification
matters: the system stayed correct even when the model's tool-calling format failed,
not just when its code output was wrong.

### Final code (verified correct, all 5 issues resolved)
```python
"""
This module provides utility functions for basic mathematical operations.
"""

def divide(a, b):
    """Divide two numbers."""
    return a / b

def average(numbers):
    """Calculate the average of a list of numbers."""
    total = 0
    for n in numbers:
        total = total + n
    return total / len(numbers)

def calc_discount(price, percent):
    """Calculate the discounted price."""
    x = price - (price * percent)
    return x
```

## Open question at time of writing
Whether this result generalises to issue types the patcher has weaker hints for
(e.g. `consider-using-enumerate`, `singleton-comparison`, multiple unused imports).
Testing in progress on `messy_loops.py`.

## Practical constraint discovered: throughput
A 5-issue file took ~30 minutes end to end on CPU-only hardware. For the planned
evaluation set (~10 real files), this implies several hours of runtime, which is
the main open risk for Phase 3 (evaluation), separate from correctness.

---

## UPDATE: harder file with mixed issue types (`messy_loops.py`, 7 issues)

Issue types: module docstring, 2x function docstring, 2x `consider-using-enumerate`,
1x `singleton-comparison` (`!= None`). The last two have no explicit hint in
`patcher.py`'s `FIX_HINTS` table, unlike docstrings.

**Result: 5 of 7 issues fixed and verified. Both `consider-using-enumerate`
issues remained unfixed when the iteration budget (`max_iter=8`) ran out.**
Runtime: ~32 minutes, 13 model calls.

What worked: module docstring, both function docstrings, and the
`item != None` -> `item is not None` fix were all proposed, verified, and
accepted correctly — including a hint-less issue (`singleton-comparison`).

What did not: the model repeatedly said it was "fixing enumerate" but the
patcher's actual output did not reliably apply that change, and the run ran out
of iterations before a further correction cycle could complete it.

**Honest reading for the report:** the pipeline is reliable for issues with a
clear, local, mechanical fix (docstrings, simple comparisons), and less
reliable for issues requiring a small structural rewrite (looping construct)
within a limited iteration budget on a 7-issue file. This is a genuine,
reportable limitation, not a bug — worth stating plainly rather than hidden.

---

## UPDATE: harder real file, partial success within budget (`messy_loops.py`)

7 issues found (module docstring, 2 function docstrings, 2 "consider-using-enumerate"
in a nested loop, 1 "singleton-comparison"). Runtime: ~32 minutes, 13 model calls.

Result: **5 of 7 issues resolved and verified; 2 remained when the 8-iteration budget
ran out.** Crucially, the agent did NOT falsely claim completion — it simply ran out
of budget mid-task, which is an honest "incomplete," not a hallucinated "done."

Sequence: module docstring fixed (ACCEPTED) -> function docstrings + None-comparison
fixed together (ACCEPTED, remaining: 2x consider-using-enumerate) -> one more patch
attempted, converting the nested-loop duplicate-finder to use enumerate() -> ran out
of iterations before this patch could be verified.

Notable: the model's own `Action Input` became severely malformed in later steps
(JSON stringified inside itself 3-4 levels deep -- visible as nested `_raw` keys).
`_resolve_issue()` in `agent/loop.py` recovered correctly every time by matching
against the real static-analysis findings rather than trusting the model's structure.

### What this confirms
- Docstring and simple comparison fixes: reliably succeed (2/2 files so far).
- Structural fixes (loop restructuring): harder, need more iterations; not yet
  confirmed to succeed end-to-end on this hardware within a practical time budget.
- No hallucinated "fixed" claim has occurred since the finish guard + verifier
  rewrite -- the system is honest about partial results, which is itself a result
  worth reporting (contrast with the pre-fix behaviour where fake completions were
  silently accepted).

### Throughput data so far (CPU-only, qwen-refactor-7b + qwen-baseline-7b)
| File | Issues | Resolved | Time |
|---|---|---|---|
| buggy_math.py | 5 | 5/5 | ~30 min |
| messy_loops.py | 7 | 5/7 (budget exhausted) | ~32 min |

Roughly 6 minutes per issue resolved, on this hardware, with this model pair.

---

## UPDATE (5 Oct 2026): correction, two fixes, and the first clean API run

### Correction to the section above
Two statements above turned out to be too strong:
- "`_resolve_issue()` ... recovered correctly every time": **not always.** When the
  Action Input could not be parsed at all, it fell back to the *first* finding.
- "No hallucinated 'fixed' claim has occurred since...": **one did**, caused by that fallback.

### The failing case: review `4ffdac0b9e39` (real model, through the API)
Input: `calc` with 1-space indentation (4 findings: 2x `bad-indentation`,
`missing-module-docstring`, `missing-function-docstring`).
The model said "Now, I will address the missing function docstring"; its Action Input was
nested three `_raw` layers deep and unreadable, so the target fell back to
`bad-indentation`. The patch added no docstring but did fix indentation, so the verifier
returned `{'status': 'ACCEPTED', ...}` against the wrong target. The same review's final
explanation said "No changes were made to the code" for a diff that re-indented 2 lines.
Full result: `tests/fixtures/review_4ffdac0b9e39.json`.

Root cause: `agent/prompts.py` showed past inputs as Python dicts (single quotes); the model
copied that non-JSON format, the parser stored it as `{"_raw": ...}`, the model copied
*that*, adding one layer per step. Fixes:
- `agent/prompts.py`: history shown as real JSON, plus one example line.
- `agent/parser.py`: also reads single-quoted dicts; unwraps nested `_raw` layers.
- `agent/loop.py` `_resolve_issue`: only targets a rule pylint still reports; if the input is
  unreadable, matches the rule named in the model's own Thought before the first-finding fallback.
- `agent/report.py`: the explanation is checked against the diff (claims of "no change",
  docstrings, imports, renames); one retry with the exact mistakes; then a factual fallback.
`sandbox/verify.py` was not changed.

Regression tests replaying the real output (no model needed):
```
python test_parse_gap.py        -> 11/11 checks passed
[PASS] 11. Replay: patch that only fixes indentation is REJECTED as issue_not_fixed for missing-function-docstring
python test_explanation_gap.py  -> 7/7 checks passed
python test_verify_gap.py       -> 8/8 checks passed (unchanged)
```

### First clean end-to-end API run after the fixes: review `2a1cbd019213`
Input (correctly indented, 2 findings):
```python
def calc(a, b, c):
    x = a + b
    return x * c
```
Runtime **634 s** (08:09:18 -> 08:19:52 UTC), **9 model calls** (6 agent, 2 patch,
1 explanation). Full result: `tests/fixtures/review_2a1cbd019213.json`.

| Step | Action | Target / result |
|---|---|---|
| 0 | static_analysis | 2 findings: `missing-module-docstring`, `missing-function-docstring` |
| 1 | propose_patch | target `missing-function-docstring` (input parsed cleanly) -> function docstring added |
| 2 | apply_and_test | `{'status': 'ACCEPTED', 'remaining_issues': ['missing-module-docstring']}` |
| 3 | propose_patch | target `missing-module-docstring` -> module docstring added on top of patch 1 |
| 4 | apply_and_test | `{'status': 'ACCEPTED', 'remaining_issues': []}` |
| 5 | finish | accepted first time (`done`), no finish-guard refusal needed |

Final verified code:
```python
"""This module contains utility functions for basic arithmetic operations."""

def calc(a, b, c):
    """Calculate the product of the sum of a and b with c."""
    x = a + b
    return x * c
```
Explanation: `explanation_source: "model"`, `explanation_problems: []` — accurate on the
first try: "The module and function docstrings were added to improve code readability and
maintainability." `fixed_issues` (from pylint): both docstring findings, 1 each.

What this shows:
- Both accepted patches did exactly what their target named; each patch built on the last.
- No false completion: `finish` only came after pylint reported nothing left.
- The explanation matched the diff with no retry.

Honest limits of this run:
- **`_raw` still appears**, in 3 of 6 Action Inputs, but only **one layer deep** (it no
  longer grows step by step). New cause: when the model copies code containing `"""`
  docstrings into its JSON, it does not escape the quotes, so the text is neither valid JSON
  nor a Python literal. It did not matter here, because the loop uses its own stored patch
  and the pylint-derived target, not the model's copy.
- Step 3's correct target is weak evidence for the parser fix: only one finding remained,
  so any fallback would have chosen it. Step 1 (two findings, parsed cleanly) is the step
  that shows the fix working.
- This is an easier input than `4ffdac0b9e39` (no indentation issues), not a re-run of it.
- The explanation used the baseline model's "Issues Found / Refactored Code / Explanation"
  layout rather than the requested 2-4 sentences; accurate, but longer than asked.
