"""Offline golden-trajectory eval runner (deterministic, no API key).

Usage from the project root:
    .venv/bin/python eval/run_evals.py [--tasks eval/golden_tasks.json] [--threshold 0.8]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)


async def run_one(task, loop) -> dict:
    from src.evals import evaluate_run

    result = await loop.run(task.input)
    evaluation = evaluate_run(
        task,
        actual_tools=result.tools_called,
        actual_agents=result.agents_path,
        resolved=result.resolved,
        escalated=result.escalated,
    )
    return {"task": task, "result": result, "evaluation": evaluation}


async def main_async(tasks_path: str, threshold: float) -> int:
    import tempfile

    from src.evals import GoldenTask, summarize
    from src.loop import AgentLoop, RuleBasedLLMClient
    from src.tools import db_tool, email_tool
    from src.tools.inventory_tool import reset_catalog

    with open(tasks_path, encoding="utf-8") as fh:
        tasks = [GoldenTask(**t) for t in json.load(fh)]

    evaluations = []
    with tempfile.TemporaryDirectory() as tmpdir:
        db_tool.set_db_path(os.path.join(tmpdir, "evals.db"))
        try:
            for task in tasks:
                reset_catalog()
                email_tool.clear_outbox()
                loop = AgentLoop(llm=RuleBasedLLMClient())
                result = await loop.run(task.input)
                from src.evals import evaluate_run

                evaluations.append(evaluate_run(
                    task,
                    actual_tools=result.tools_called,
                    actual_agents=result.agents_path,
                    resolved=result.resolved,
                    escalated=result.escalated,
                ))
        finally:
            db_tool.set_db_path(None)

    report = summarize(evaluations)
    print(f"\nGolden trajectory evals: {report.passed}/{report.total} passed (rate {report.pass_rate})\n")
    print(f"{'task':<22}{'pass':<6}{'F1':<6}{'agents':<8}{'outcome':<9}actual tools")
    print("-" * 110)
    for evaluation in report.results:
        print(
            f"{evaluation.task_id:<22}"
            f"{'PASS' if evaluation.passed else 'FAIL':<6}"
            f"{evaluation.tools_score.f1:<6}"
            f"{'yes' if evaluation.agents_match else 'NO':<8}"
            f"{'yes' if evaluation.outcome_match else 'NO':<9}"
            f"{' -> '.join(evaluation.actual_tools)}"
        )
        if not evaluation.passed:
            print(f"  notes: {evaluation.notes}")
    print()
    return 0 if report.pass_rate >= threshold else 1


def main() -> None:
    parser = argparse.ArgumentParser(description="Run golden trajectory evals (offline).")
    parser.add_argument("--tasks", default="eval/golden_tasks.json")
    parser.add_argument("--threshold", type=float, default=0.8)
    args = parser.parse_args()
    sys.exit(asyncio.run(main_async(args.tasks, args.threshold)))


if __name__ == "__main__":
    main()
