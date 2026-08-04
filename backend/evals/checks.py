"""Deterministic checks for AI answer quality.

An LLM grading an LLM is expensive, slow, and disagrees with itself between
runs. Most of what actually goes wrong in TM1 answers can be checked
without one:

  * invented or misplaced functions — the shipped function reference knows
    every documented TM1 function and the contexts it is valid in, so this
    is a lookup, not a judgement;
  * a claim the answer must never make — a substring;
  * a term the answer must qualify rather than recommend flatly — a
    proximity check.

Only genuinely open questions ("did it explain the reasoning?") need a
judge, and those are kept separate so a regression suite can run on the
deterministic ones alone.
"""

import re

from src.tm1.functions import validate_code

# ```tm1 ... ``` / ```ti ... ``` / plain ``` ... ``` blocks.
_CODE_BLOCK = re.compile(r"```[a-zA-Z0-9_+-]*\n(.*?)```", re.DOTALL)


class CheckResult:

    __slots__ = ("name", "passed", "detail")

    def __init__(self, name: str, passed: bool, detail: str = ""):
        self.name = name
        self.passed = passed
        self.detail = detail

    def __repr__(self) -> str:
        return f"{'PASS' if self.passed else 'FAIL'} {self.name}: {self.detail}"


def extract_code(answer: str) -> str:
    """All fenced code in the answer, concatenated."""

    return "\n".join(block for block in _CODE_BLOCK.findall(answer))


def check_functions_are_real(
    answer: str,
    *,
    context: str = "TI",
    version: str | None = None,
) -> CheckResult:
    """No invented functions, none borrowed from the wrong context.

    Unknown names are reported here (unlike in drafting, where a false
    positive would block a legitimate change) because an eval failing loudly
    is cheap and a wrong answer shipped to a user is not.
    """

    code = extract_code(answer)

    if not code.strip():
        return CheckResult(
            "functions_are_real", False, "answer contains no code block"
        )

    issues = validate_code(
        code, context=context, version=version, report_unknown=True
    )

    if issues:
        detail = "; ".join(f"{i['function']}: {i['kind']}" for i in issues)
        return CheckResult("functions_are_real", False, detail)

    return CheckResult("functions_are_real", True, "")


def check_absent(answer: str, phrases: list[str]) -> CheckResult:
    """None of these claims may appear."""

    lowered = answer.lower()
    found = [p for p in phrases if p.lower() in lowered]

    if found:
        return CheckResult("absent", False, f"found forbidden: {found}")

    return CheckResult("absent", True, "")


def check_present(answer: str, phrases: list[str]) -> CheckResult:
    """Each of these must appear somewhere."""

    lowered = answer.lower()
    missing = [p for p in phrases if p.lower() not in lowered]

    if missing:
        return CheckResult("present", False, f"missing: {missing}")

    return CheckResult("present", True, "")


def check_qualified(
    answer: str,
    term: str,
    qualifiers: list[str],
    window: int = 400,
) -> CheckResult:
    """`term` may appear, but never without a nearby qualifier.

    A good answer names the thing it is warning against. What separates it
    from a bad one is whether the warning travels with the name — so this
    checks proximity rather than absence. Heuristic by construction: the
    window is characters, not sentences.
    """

    lowered = answer.lower()
    term_lower = term.lower()

    if term_lower not in lowered:
        return CheckResult(f"qualified:{term}", True, "term not mentioned")

    for match in re.finditer(re.escape(term_lower), lowered):
        start = max(0, match.start() - window)
        end = min(len(lowered), match.end() + window)
        neighbourhood = lowered[start:end]

        if not any(q.lower() in neighbourhood for q in qualifiers):
            return CheckResult(
                f"qualified:{term}",
                False,
                f"'{term}' appears with no qualifier within {window} chars",
            )

    return CheckResult(f"qualified:{term}", True, "")
