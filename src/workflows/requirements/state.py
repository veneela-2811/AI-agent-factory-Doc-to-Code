from typing import TypedDict, List, Dict, Any, Optional


class RequirementsGraphState(TypedDict, total=False):
    project_id: str
    run_id: str
    document_ids: List[str]
    document_chunks: List[Dict[str, Any]]
    gap_analysis_rounds: int
    has_critical_gaps: bool
    clarification_questions: List[Dict[str, str]]
    clarification_answers: List[Dict[str, str]]
    requirements_md: str
    requirements_json: Dict[str, Any]
    approval_status: str  # pending, approved, rejected
    user_feedback: Optional[str]
    current_node: str
    error: Optional[str]
