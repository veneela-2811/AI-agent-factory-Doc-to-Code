from typing import TypedDict, List, Dict, Any, Optional


class PlanningGraphState(TypedDict, total=False):
    project_id: str
    run_id: str
    requirements_run_id: Optional[str]
    requirements_doc: Dict[str, Any]
    complexity_path: str  # "lightweight" | "heavyweight"
    selected_patterns: List[Dict[str, Any]]
    research_findings: List[Dict[str, Any]]
    architecture: Dict[str, Any]
    architecture_md: str
    tasks: List[Dict[str, Any]]
    critic_score: float
    critic_feedback: Optional[str]
    critic_warnings: List[str]
    critic_iterations: int
    approval_status: str  # "pending", "approved", "rejected"
    user_feedback: Optional[str]
    reentry_node: Optional[str]
    current_node: str
    error: Optional[str]
