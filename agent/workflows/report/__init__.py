"""Report-generation workflow.

A 12-stage DAG that mirrors the existing publication workflow but replaces
the rule-driven template with role-specialized LLM agents.

Entry point:
    from agent.workflows.report.pipeline import run_report
    ctx = run_report({"recipient": "Egypt", "start_date": "2024-01-01",
                      "end_date": "2024-03-31", "influencer": "China"})
"""

from agent.workflows.report.pipeline import REPORT_PIPELINE, run_report

__all__ = ["REPORT_PIPELINE", "run_report"]
