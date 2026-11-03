"""Trajectory evaluation: score agent tool paths against golden expectations."""
from __future__ import annotations

from pydantic import BaseModel, Field


class TrajectoryScore(BaseModel):
    exact_match: bool
    lcs_length: int
    precision: float
    recall: float
    f1: float
    missing: list[str] = Field(default_factory=list)
    extra: list[str] = Field(default_factory=list)


class GoldenTask(BaseModel):
    id: str
    description: str = ""
    input: str
    expected_agents: list[str]
    expected_tools: list[str]
    expected_outcome: str = Field(pattern="^(resolved|escalated)$")


class EvalResult(BaseModel):
    task_id: str
    passed: bool
    tools_score: TrajectoryScore
    agents_match: bool
    outcome_match: bool
    actual_tools: list[str]
    actual_agents: list[str]
    actual_outcome: str
    notes: str = ""


class SuiteReport(BaseModel):
    total: int
    passed: int
    pass_rate: float
    results: list[EvalResult]


def _lcs_length(a: list[str], b: list[str]) -> int:
    prev = [0] * (len(b) + 1)
    for x in a:
        current = [0]
        for j, y in enumerate(b, start=1):
            if x == y:
                current.append(prev[j - 1] + 1)
            else:
                current.append(max(prev[j], current[-1]))
        prev = current
    return prev[-1]


def score_trajectory(actual: list[str], expected: list[str]) -> TrajectoryScore:
    """Compare tool-name sequences via exact match + LCS-based precision/recall."""
    lcs = _lcs_length(actual, expected)
    precision = (lcs / len(actual)) if actual else (1.0 if not expected else 0.0)
    recall = (lcs / len(expected)) if expected else 1.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    missing = [t for t in expected if t not in actual]
    extra = [t for t in actual if t not in expected]
    return TrajectoryScore(
        exact_match=actual == expected,
        lcs_length=lcs,
        precision=round(precision, 3),
        recall=round(recall, 3),
        f1=round(f1, 3),
        missing=missing,
        extra=extra,
    )


def evaluate_run(task: GoldenTask, actual_tools: list[str], actual_agents: list[str], resolved: bool, escalated: bool) -> EvalResult:
    """Score one run. Pass = trajectory F1 >= 0.8 + agents match + outcome match."""
    actual_outcome = "escalated" if escalated else ("resolved" if resolved else "unresolved")
    tools_score = score_trajectory(actual_tools, task.expected_tools)
    agents_match = actual_agents == task.expected_agents
    outcome_match = actual_outcome == task.expected_outcome
    passed = tools_score.f1 >= 0.8 and agents_match and outcome_match
    notes = []
    if tools_score.f1 < 0.8:
        notes.append(f"trajectory F1 {tools_score.f1} < 0.8 (missing={tools_score.missing}, extra={tools_score.extra})")
    if not agents_match:
        notes.append(f"agents {actual_agents} != {task.expected_agents}")
    if not outcome_match:
        notes.append(f"outcome {actual_outcome} != {task.expected_outcome}")
    return EvalResult(
        task_id=task.id, passed=passed, tools_score=tools_score,
        agents_match=agents_match, outcome_match=outcome_match,
        actual_tools=actual_tools, actual_agents=actual_agents,
        actual_outcome=actual_outcome, notes="; ".join(notes),
    )


def summarize(results: list[EvalResult]) -> SuiteReport:
    passed = sum(1 for r in results if r.passed)
    total = len(results)
    return SuiteReport(
        total=total, passed=passed,
        pass_rate=round(passed / total, 3) if total else 0.0,
        results=results,
    )
