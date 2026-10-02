from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
from datetime import datetime, timezone


class GeneratedFile(BaseModel):
    path: str = Field(description="Relative path of the target file inside the workspace (e.g. 'src/storage/models.py')")
    content: str = Field(description="Complete, valid, production-ready source code for the file")
    description: Optional[str] = Field(default="", description="Summary of what this file implements")


class CodeGenerationResult(BaseModel):
    files: List[GeneratedFile] = Field(default_factory=list, description="List of generated source code files for the task")
    notes: Optional[str] = Field(default="", description="Implementation notes or explanations")


class ReviewerVerdict(BaseModel):
    reviewer_name: str = Field(description="Name of reviewer: workflow_reviewer, prompt_reviewer, or security_reviewer")
    verdict: str = Field(description="'pass' or 'fail'")
    score: float = Field(default=10.0, description="Score between 0.0 and 10.0")
    issues: List[str] = Field(default_factory=list, description="Specific issues or deficiencies found")
    suggestions: List[str] = Field(default_factory=list, description="Actionable recommendations for improvement")
    is_critical_security: bool = Field(default=False, description="True if a critical security flaw / OWASP violation was identified")


class AggregatedReview(BaseModel):
    verdict: str = Field(description="'pass' or 'fail'")
    passed_reviewers: List[str] = Field(default_factory=list)
    failed_reviewers: List[str] = Field(default_factory=list)
    has_security_veto: bool = Field(default=False)
    feedback: str = Field(default="", description="Combined feedback for developer refactor")


class TaskExecutionResult(BaseModel):
    task_id: str
    title: str
    status: str  # completed, failed, paused
    generated_files: List[str] = Field(default_factory=list)
    diffs: Dict[str, str] = Field(default_factory=dict)
    iterations: int = 1
    review: Optional[AggregatedReview] = None


class ManifestTaskEntry(BaseModel):
    task_id: str
    title: str
    status: str
    target_files: List[str]
    pattern_refs: List[str]
    iterations: int
    review_verdict: str
    reviewers_passed: List[str]
    reviewers_failed: List[str]


class ManifestDoc(BaseModel):
    project_id: str
    run_id: str
    generated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    task_count: int
    total_files: int
    files: List[str]
    tasks: List[ManifestTaskEntry]
