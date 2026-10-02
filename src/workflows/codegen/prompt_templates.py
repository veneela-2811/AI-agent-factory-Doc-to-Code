import json
from typing import List, Dict, Any, Optional


def build_developer_system_prompt(task: Dict[str, Any], patterns: List[Dict[str, Any]], architecture: Dict[str, Any]) -> str:
    pattern_sections = []
    for p in patterns:
        name = p.get("name") or p.get("pattern_name", "")
        intent = p.get("intent", "")
        structure = p.get("structure", "")
        prereqs = p.get("prerequisites", [])
        pattern_sections.append(
            f"### Pattern: {name}\n"
            f"- **Intent:** {intent}\n"
            f"- **Structure:** {structure}\n"
            f"- **Prerequisites:** {', '.join(prereqs) if prereqs else 'None'}"
        )

    patterns_text = "\n\n".join(pattern_sections) if pattern_sections else "Standard Clean Architecture (Modular Python, PEP 8, Typed)"

    tech_stack = architecture.get("tech_stack", {})
    components = architecture.get("components", [])
    arch_summary = f"Tech Stack: {json.dumps(tech_stack, indent=2)}\nComponents: {', '.join([c.get('name', '') for c in components])}" if components else "FastAPI, SQLite, LangGraph, Pydantic"

    return f"""You are a Principal Software Engineer implementing an enterprise agentic software platform.
Write real, complete, syntactically valid, production-ready Python source code.

## Architectural Context
{arch_summary}

## Agentic Design Patterns for This Task
{patterns_text}

## Coding Standards & Rules:
1. Generate complete file contents without placeholders like '# TODO: implement later' or 'pass'.
2. Use Python 3.11+ type hints, Pydantic models for data validation, and clean async/await where appropriate.
3. Handle exceptions cleanly and securely: never expose raw internal stack traces to end users.
4. Never hardcode credentials, secrets, or API keys; always load them via configuration or environment variables.
5. Return your response strictly as valid JSON matching the CodeGenerationResult schema."""


def build_developer_user_prompt(
    task: Dict[str, Any],
    requirements_doc: Dict[str, Any],
    workspace_outline: List[str],
    dependent_code_snippets: Dict[str, str],
    reviewer_feedback: Optional[str] = None
) -> str:
    task_id = task.get("task_id", "TASK-01")
    title = task.get("title", "")
    description = task.get("description", "")
    target_files = task.get("target_files", [])
    acceptance_criteria = task.get("acceptance_criteria", [])
    pattern_refs = task.get("pattern_refs", [])
    req_refs = task.get("requirement_refs", [])

    outline_str = "\n".join([f"- {f}" for f in workspace_outline]) if workspace_outline else "No files created yet."

    dep_snippets_str = ""
    if dependent_code_snippets:
        snippets = []
        for path, code in dependent_code_snippets.items():
            # Include first 1500 chars of each dependent file
            preview = code[:1500] + ("\n... [truncated]" if len(code) > 1500 else "")
            snippets.append(f"--- File: {path} ---\n{preview}")
        dep_snippets_str = "\n\n".join(snippets)
    else:
        dep_snippets_str = "None (root task)."

    feedback_section = ""
    if reviewer_feedback:
        feedback_section = f"""
## MANDATORY REVISION INSTRUCTIONS FROM CODE REVIEWERS:
{reviewer_feedback}
Resolve every issue mentioned above in your refactored code.
"""

    return f"""{feedback_section}
## Task to Implement: [{task_id}] {title}
- **Description:** {description}
- **Target Files to Generate:** {json.dumps(target_files)}
- **Acceptance Criteria:**
{json.dumps(acceptance_criteria, indent=2)}
- **Pattern References:** {json.dumps(pattern_refs)}
- **Requirement References:** {json.dumps(req_refs)}

## Existing Workspace Files (Cumulative Directory Outline):
{outline_str}

## Preceding Dependent Code Context:
{dep_snippets_str}

Please generate the complete, self-contained source code for each of the target files: {json.dumps(target_files)}.
Ensure all imports from existing workspace modules match the actual file paths. Return valid JSON matching CodeGenerationResult."""


def build_workflow_reviewer_prompt(task: Dict[str, Any], generated_code: str) -> (str, str):
    system_prompt = """You are a Senior Principal Workflow Architect.
Review the provided code to verify that agent orchestration, state management, and workflow patterns strictly adhere to requirements.
Check:
1. Does the code honor the specified agentic patterns (e.g., proper state transitions, routers, tools, reflexion)?
2. Are state graphs, nodes, and edges structured correctly with proper entry and exit conditions?
3. Are error boundaries and timeout handling in place?

Return valid JSON matching ReviewerVerdict. If issues are found, list them clearly and set verdict to 'fail' (score < 8.0). If code is sound, set verdict to 'pass' (score >= 8.0)."""

    user_prompt = f"""Evaluate the workflow and architecture implementation for Task: [{task.get('task_id')}] {task.get('title')}
Pattern References: {json.dumps(task.get('pattern_refs', []))}

Generated Code:
{generated_code}"""

    return system_prompt, user_prompt


def build_prompt_reviewer_prompt(task: Dict[str, Any], generated_code: str) -> (str, str):
    system_prompt = """You are an expert AI Prompt Engineer and Security Specialist.
Review all prompt templates, system instructions, and LLM message structures in the provided code.
Check:
1. Role Definition: Does each prompt have a clear, authoritative persona and explicit instructions?
2. Variable Interpolation: Are dynamic user inputs cleanly separated using XML tags or clear boundaries (e.g. <untrusted_input>)?
3. Injection Resistance: Does the prompt include defenses against prompt injection and jailbreaks?
4. Output Constraints: Are structured output schemas or strict formatting rules enforced?

Return valid JSON matching ReviewerVerdict. Set verdict to 'pass' (score >= 8.0) if prompts are safe and well-crafted, or 'fail' (score < 8.0) if missing or unsafe."""

    user_prompt = f"""Evaluate prompts and LLM interactions in Task: [{task.get('task_id')}] {task.get('title')}

Generated Code:
{generated_code}"""

    return system_prompt, user_prompt


def build_security_reviewer_prompt(task: Dict[str, Any], generated_code: str) -> (str, str):
    system_prompt = """You are a Principal Application Security Auditor (AppSec & OWASP Top 10).
Conduct a rigorous security analysis of the provided source code.
Check:
1. Hardcoded Secrets: Are API keys, passwords, tokens, or private credentials hardcoded anywhere? (CRITICAL VETO)
2. Injection Vulnerabilities: Are raw SQL queries formatted with f-strings instead of parameterized queries? (CRITICAL VETO)
3. Input Validation: Are external inputs validated using Pydantic or schema bounds?
4. Error Leakage: Does the code log or return raw stack traces or internal environment variables to users?

Set is_critical_security=True if hardcoded secrets or SQL injection are detected.
Return valid JSON matching ReviewerVerdict. Set verdict to 'pass' (score >= 8.0) if secure, or 'fail' (score < 8.0) if vulnerabilities exist."""

    user_prompt = f"""Evaluate security and OWASP hygiene for Task: [{task.get('task_id')}] {task.get('title')}

Generated Code:
{generated_code}"""

    return system_prompt, user_prompt
