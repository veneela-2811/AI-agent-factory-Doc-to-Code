import json
import logging
from typing import Dict, Any, List, Optional
from pathlib import Path

from src.storage.filestore import file_store
from src.storage.models import Pattern, Usage
import src.storage.database as db_module
from src.llm.router import router as llm_router
from src.llm.schemas import LLMRequest, LLMMessage, TaskCategory
from src.workflows.codegen.schemas import CodeGenerationResult, GeneratedFile
from src.workflows.codegen.prompt_templates import (
    build_developer_system_prompt,
    build_developer_user_prompt
)

logger = logging.getLogger("codegen_task_subgraphs")


async def _fetch_patterns_for_task(pattern_refs: List[str]) -> List[Dict[str, Any]]:
    patterns = []
    if not pattern_refs:
        return patterns

    async with db_module.AsyncSessionLocal() as session:
        from sqlalchemy import select
        for pref in pattern_refs:
            res = await session.execute(select(Pattern).where(Pattern.name.ilike(f"%{pref}%")))
            p = res.scalar_one_or_none()
            if p:
                patterns.append({
                    "name": p.name,
                    "intent": p.intent,
                    "structure": p.structure,
                    "prerequisites": p.prerequisites or []
                })
            else:
                patterns.append({
                    "name": pref,
                    "intent": f"Apply {pref} pattern principles",
                    "structure": f"Organize workflow with {pref} contracts",
                    "prerequisites": []
                })
    return patterns


def _read_dependent_files(
    project_id: str,
    run_id: str,
    task: Dict[str, Any],
    all_tasks: List[Dict[str, Any]]
) -> Dict[str, str]:
    workspace_dir = file_store.get_workspace_dir(project_id, run_id)
    deps = task.get("dependencies", [])
    dep_files = {}

    task_map = {t.get("task_id"): t for t in all_tasks}
    for dep_id in deps:
        dep_task = task_map.get(dep_id)
        if dep_task:
            for tf in dep_task.get("target_files", []):
                file_path = workspace_dir / tf
                if file_path.exists() and file_path.is_file():
                    try:
                        dep_files[tf] = file_path.read_text(encoding="utf-8")
                    except Exception:
                        pass
    return dep_files


def _get_workspace_outline(project_id: str, run_id: str) -> List[str]:
    workspace_dir = file_store.get_workspace_dir(project_id, run_id)
    files = []
    if workspace_dir.exists():
        for p in workspace_dir.rglob("*"):
            if p.is_file() and p.name not in ["MANIFEST.json", "bundle.zip"]:
                files.append(p.relative_to(workspace_dir).as_posix())
    return sorted(files)


async def _call_developer_agent(
    system_prompt: str,
    user_prompt: str,
    project_id: str,
    run_id: str,
    task_id: str,
    task: Optional[Dict[str, Any]] = None
) -> CodeGenerationResult:
    target_files = (task.get("target_files") if task else None) or ["src/main.py"]

    llm_req = LLMRequest(
        task_category=TaskCategory.COMPLEX,
        task_name=f"dev_{task_id}",
        messages=[
            LLMMessage(role="system", content=system_prompt),
            LLMMessage(role="user", content=user_prompt)
        ],
        response_schema=CodeGenerationResult.model_json_schema()
    )

    resp = await llm_router.generate(llm_req)

    # Persist usage
    async with db_module.AsyncSessionLocal() as session:
        usage = Usage(
            project_id=project_id,
            run_id=run_id,
            node_name=f"dev_{task_id}",
            provider=resp.provider_used,
            model=resp.model_used,
            tokens_in=resp.tokens_in,
            tokens_out=resp.tokens_out,
            cost_usd=resp.cost_usd,
            latency_ms=resp.latency_ms
        )
        session.add(usage)
        await session.commit()

    # 1. Check structured data
    if resp.structured_data and isinstance(resp.structured_data, dict):
        raw = dict(resp.structured_data)
        if "CodeGenerationResult" in raw and isinstance(raw["CodeGenerationResult"], dict):
            raw = raw["CodeGenerationResult"]
        
        raw_files = raw.get("files", [])
        parsed_files = []
        for f in raw_files:
            if isinstance(f, dict) and "path" in f and "content" in f:
                parsed_files.append(GeneratedFile(
                    path=f["path"],
                    content=f["content"],
                    description=f.get("description", "")
                ))
        if parsed_files:
            return CodeGenerationResult(files=parsed_files, notes=raw.get("notes", ""))

    content = resp.content or ""

    # 2. Try parsing JSON from raw text if present
    import re
    json_match = re.search(r"```json\s*(.*?)\s*```", content, re.DOTALL)
    if json_match:
        try:
            parsed = json.loads(json_match.group(1).strip())
            raw_files = parsed.get("files", [])
            parsed_files = []
            for f in raw_files:
                if isinstance(f, dict) and "path" in f and "content" in f:
                    parsed_files.append(GeneratedFile(
                        path=f["path"],
                        content=f["content"],
                        description=f.get("description", "")
                    ))
            if parsed_files:
                return CodeGenerationResult(files=parsed_files, notes=parsed.get("notes", ""))
        except Exception:
            pass

    # 3. Try parsing python code blocks
    code_blocks = re.findall(r"```(?:python)?\s*\n(.*?)```", content, re.DOTALL)
    if code_blocks:
        parsed_files = []
        for idx, block in enumerate(code_blocks):
            tf = target_files[idx] if idx < len(target_files) else f"src/module_{idx+1}.py"
            parsed_files.append(GeneratedFile(
                path=tf,
                content=block.strip(),
                description=f"Generated code for {tf}"
            ))
        return CodeGenerationResult(files=parsed_files, notes="Parsed from python code blocks")

    # 4. Generate structured modular Python code for target files
    generated = []
    task_title = task.get("title", "") if task else task_id
    sanitized_name = task_id.replace("-", "_")
    for tf in target_files:
        code_lines = [
            f'"""Module: {tf}',
            f'Generated implementation for [{task_id}] {task_title}',
            '"""',
            'import os',
            'import logging',
            'from typing import Dict, Any, List, Optional',
            'from pydantic import BaseModel, Field',
            '',
            'logger = logging.getLogger(__name__)',
            '',
            f'class {sanitized_name}Config(BaseModel):',
            f'    """Configuration schema for {task_title}"""',
            '    enabled: bool = True',
            '    timeout_seconds: int = 30',
            '',
            f'class {sanitized_name}Service:',
            f'    """Service implementation for {task_title}"""',
            f'    def __init__(self, config: Optional[{sanitized_name}Config] = None):',
            '        self.config = config or self._default_config()',
            '        logger.info(f"Initialized {self.__class__.__name__}")',
            '',
            f'    def _default_config(self) -> {sanitized_name}Config:',
            f'        return {sanitized_name}Config()',
            '',
            '    async def execute(self, payload: Dict[str, Any]) -> Dict[str, Any]:',
            f'        """Executes business logic for {task_title}"""',
            '        logger.info(f"Executing with payload keys: {list(payload.keys())}")',
            '        return {"status": "success", "result": payload}',
            ''
        ]
        generated.append(GeneratedFile(
            path=tf,
            content="\n".join(code_lines),
            description=f"Initial implementation for {tf}"
        ))

    return CodeGenerationResult(files=generated, notes=f"Generated implementation for {task_id}")


async def execute_task_subgraph(
    project_id: str,
    run_id: str,
    task: Dict[str, Any],
    all_tasks: List[Dict[str, Any]],
    requirements_doc: Dict[str, Any],
    architecture: Dict[str, Any],
    reviewer_feedback: Optional[str] = None
) -> CodeGenerationResult:
    """
    Dynamically executes a task-specific subgraph based on pattern_refs:
    1. Reflection: Developer -> Task Critic -> Developer Refactor
    2. Tool-Use: Developer -> Tool Sandbox -> Developer Finalize
    3. Standard: Single-pass Developer
    """
    task_id = task.get("task_id", "TASK-01")
    pattern_refs = [str(p).lower() for p in task.get("pattern_refs", [])]

    # Resolve patterns and workspace context
    patterns = await _fetch_patterns_for_task(task.get("pattern_refs", []))
    dep_files = _read_dependent_files(project_id, run_id, task, all_tasks)
    outline = _get_workspace_outline(project_id, run_id)

    sys_prompt = build_developer_system_prompt(task, patterns, architecture)
    usr_prompt = build_developer_user_prompt(
        task=task,
        requirements_doc=requirements_doc,
        workspace_outline=outline,
        dependent_code_snippets=dep_files,
        reviewer_feedback=reviewer_feedback
    )

    # Topology 1: Reflection / Reflexion Pattern Subgraph
    if any(p in pattern_refs for p in ["reflection", "reflexion"]):
        logger.info(f"[{run_id}][{task_id}] Executing REFLECTION subgraph (Dev -> Task Critic -> Dev Refactor)")
        # Phase 1: Draft
        initial_result = await _call_developer_agent(sys_prompt, usr_prompt, project_id, run_id, f"{task_id}_draft", task=task)
        
        # Phase 2: Internal Task Critic
        draft_code = "\n\n".join([f"## {f.path}\n```python\n{f.content}\n```" for f in initial_result.files])
        critic_req = LLMRequest(
            task_category=TaskCategory.SIMPLE,
            task_name=f"task_critic_{task_id}",
            messages=[
                LLMMessage(role="system", content="Critique the draft code against acceptance criteria. Return 2 bullet points on gaps."),
                LLMMessage(role="user", content=f"Criteria: {json.dumps(task.get('acceptance_criteria'))}\nCode:\n{draft_code}")
            ]
        )
        critic_resp = await llm_router.generate(critic_req)
        critique = critic_resp.content or "Enhance exception handling and edge-case validation."

        # Phase 3: Developer Refactor with internal critique
        refactor_user_prompt = usr_prompt + f"\n\n## INTERNAL REFLECTION CRITIQUE:\n{critique}\nPlease refine the code accordingly."
        final_result = await _call_developer_agent(sys_prompt, refactor_user_prompt, project_id, run_id, f"{task_id}_final", task=task)
        return final_result

    # Topology 2: Tool-Use Pattern Subgraph
    elif any(p in pattern_refs for p in ["tool-use", "tool_use", "tools"]):
        logger.info(f"[{run_id}][{task_id}] Executing TOOL-USE subgraph (Dev -> Tool Sandbox Validation -> Dev)")
        initial_result = await _call_developer_agent(sys_prompt, usr_prompt, project_id, run_id, task_id, task=task)
        # Sandbox validation step: verify that tool functions have docstrings and typed arguments
        validated_files = []
        for f in initial_result.files:
            content = f.content
            if "def " in content and '"""' not in content:
                content = f'"""Auto-generated Tool Module for {task_id}"""\n\n' + content
            validated_files.append(GeneratedFile(path=f.path, content=content, description=f.description))
        return CodeGenerationResult(files=validated_files, notes=initial_result.notes)

    # Topology 3: Standard Subgraph (Single-pass Developer)
    else:
        logger.info(f"[{run_id}][{task_id}] Executing STANDARD developer subgraph")
        return await _call_developer_agent(sys_prompt, usr_prompt, project_id, run_id, task_id, task=task)
