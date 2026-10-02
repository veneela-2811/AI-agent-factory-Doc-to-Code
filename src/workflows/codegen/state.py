from typing import TypedDict, List, Dict, Any, Optional


class CodegenGraphState(TypedDict, total=False):
    project_id: str
    run_id: str
    planning_run_id: Optional[str]
    requirements_doc: Dict[str, Any]
    architecture: Dict[str, Any]
    tasks: List[Dict[str, Any]]
    current_task_index: int
    completed_tasks: List[Dict[str, Any]]
    workspace_files: List[str]
    current_task_files: List[Dict[str, Any]]
    current_task_iteration: int
    current_task_review: Optional[Dict[str, Any]]
    task_critic_feedback: Optional[str]
    approval_status: str  # pending, approved, rejected
    current_node: str
    error: Optional[str]
    manifest: Optional[Dict[str, Any]]
    bundle_path: Optional[str]
