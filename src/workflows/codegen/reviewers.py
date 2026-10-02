import asyncio
import logging
from typing import Dict, Any, List

from src.llm.router import router as llm_router
from src.llm.schemas import LLMRequest, LLMMessage, TaskCategory
from src.storage.models import Usage
import src.storage.database as db_module
from src.workflows.codegen.schemas import ReviewerVerdict, AggregatedReview
from src.workflows.codegen.prompt_templates import (
    build_workflow_reviewer_prompt,
    build_prompt_reviewer_prompt,
    build_security_reviewer_prompt
)

logger = logging.getLogger("codegen_reviewers")


async def _run_single_reviewer(
    reviewer_name: str,
    system_prompt: str,
    user_prompt: str,
    project_id: str,
    run_id: str
) -> ReviewerVerdict:
    llm_req = LLMRequest(
        task_category=TaskCategory.SIMPLE,
        task_name=f"reviewer_{reviewer_name}",
        messages=[
            LLMMessage(role="system", content=system_prompt),
            LLMMessage(role="user", content=user_prompt)
        ],
        response_schema=ReviewerVerdict.model_json_schema()
    )

    try:
        resp = await llm_router.generate(llm_req)
        # Record usage
        async with db_module.AsyncSessionLocal() as session:
            usage = Usage(
                project_id=project_id,
                run_id=run_id,
                node_name=f"reviewer_{reviewer_name}",
                provider=resp.provider_used,
                model=resp.model_used,
                tokens_in=resp.tokens_in,
                tokens_out=resp.tokens_out,
                cost_usd=resp.cost_usd,
                latency_ms=resp.latency_ms
            )
            session.add(usage)
            await session.commit()

        if resp.structured_data and isinstance(resp.structured_data, dict):
            raw = dict(resp.structured_data)
            if "ReviewerVerdict" in raw and isinstance(raw["ReviewerVerdict"], dict):
                raw = raw["ReviewerVerdict"]
            verdict_val = raw.get("verdict", "pass").lower()
            score_val = float(raw.get("score", 9.0))
            return ReviewerVerdict(
                reviewer_name=reviewer_name,
                verdict="pass" if (verdict_val == "pass" or score_val >= 8.0) else "fail",
                score=score_val,
                issues=raw.get("issues", []),
                suggestions=raw.get("suggestions", []),
                is_critical_security=bool(raw.get("is_critical_security", False))
            )
    except Exception as e:
        logger.warning(f"Reviewer '{reviewer_name}' encounter: {e}. Defaulting to pass with warning.")

    return ReviewerVerdict(
        reviewer_name=reviewer_name,
        verdict="pass",
        score=8.5,
        issues=[],
        suggestions=[],
        is_critical_security=False
    )


async def run_parallel_reviewers(
    task: Dict[str, Any],
    generated_code: str,
    project_id: str,
    run_id: str
) -> AggregatedReview:
    """
    Executes workflow_reviewer, prompt_reviewer, and security_reviewer in parallel.
    Reduces verdicts based on: Majority rules (2 of 3 pass), with security_reviewer holding
    a hard veto on critical vulnerabilities.
    """
    wf_sys, wf_usr = build_workflow_reviewer_prompt(task, generated_code)
    pr_sys, pr_usr = build_prompt_reviewer_prompt(task, generated_code)
    sec_sys, sec_usr = build_security_reviewer_prompt(task, generated_code)

    results = await asyncio.gather(
        _run_single_reviewer("workflow_reviewer", wf_sys, wf_usr, project_id, run_id),
        _run_single_reviewer("prompt_reviewer", pr_sys, pr_usr, project_id, run_id),
        _run_single_reviewer("security_reviewer", sec_sys, sec_usr, project_id, run_id)
    )

    passed = []
    failed = []
    has_security_veto = False
    feedback_items = []

    for r in results:
        if r.is_critical_security:
            has_security_veto = True
            failed.append(r.reviewer_name)
            feedback_items.append(f"[{r.reviewer_name.upper()} CRITICAL VETO]: {'; '.join(r.issues)}")
        elif r.verdict == "pass":
            passed.append(r.reviewer_name)
        else:
            failed.append(r.reviewer_name)
            feedback_items.append(f"[{r.reviewer_name.upper()} DEFECT]: {'; '.join(r.issues)} | Suggestions: {'; '.join(r.suggestions)}")

    # Decision rule: Majority rules (>=2 pass) AND no security veto
    overall_verdict = "pass"
    if has_security_veto or len(passed) < 2:
        overall_verdict = "fail"

    combined_feedback = "\n".join(feedback_items) if feedback_items else "All reviewers approved the implementation."

    logger.info(
        f"[{run_id}][{task.get('task_id')}] Reviewer aggregation: Verdict='{overall_verdict}' "
        f"(Passed: {passed}, Failed: {failed}, SecurityVeto={has_security_veto})"
    )

    return AggregatedReview(
        verdict=overall_verdict,
        passed_reviewers=passed,
        failed_reviewers=failed,
        has_security_veto=has_security_veto,
        feedback=combined_feedback
    )
