from typing import List, Dict, Any, Optional, Literal
from pydantic import BaseModel, Field


class PatternRecommendation(BaseModel):
    pattern_name: str = Field(..., description="Name of the selected agentic design pattern from the KB")
    rationale: str = Field(..., description="Why this pattern was chosen and why it is necessary")
    requirements_addressed: List[str] = Field(default_factory=list, description="IDs of requirements addressed by this pattern")
    fit_score: float = Field(1.0, description="Fit confidence score between 0.0 and 1.0")


class PatternSelectionReport(BaseModel):
    selected_patterns: List[PatternRecommendation] = Field(default_factory=list)
    summary: str = Field("", description="Executive summary of selected agent patterns")


class ResearchCitation(BaseModel):
    source_type: Literal["doc", "kb", "web", "llm"] = Field(..., description="Source type")
    citation_tag: str = Field(..., description="Citation tag formatted as [doc:...], [kb:...], [web:...], or [llm]")
    claim: str = Field(..., description="The factual or architectural claim being made")
    evidence: str = Field("", description="Supporting quote or excerpt from the source")


class ResearchReport(BaseModel):
    citations: List[ResearchCitation] = Field(default_factory=list)
    summary: str = Field("", description="Synthesis of multi-source research findings")


class ArchitectureComponent(BaseModel):
    name: str = Field(..., description="Name of the component or subsystem")
    responsibility: str = Field(..., description="Single responsibility of this component")
    associated_patterns: List[str] = Field(default_factory=list, description="Agentic design patterns utilized by this component")
    interfaces: List[str] = Field(default_factory=list, description="Public APIs, schemas, or protocols exposed")


class SystemArchitecture(BaseModel):
    project_name: str = Field(..., description="Project name")
    system_overview: str = Field(..., description="High-level architecture overview")
    components: List[ArchitectureComponent] = Field(default_factory=list)
    data_flow: List[str] = Field(default_factory=list, description="Step-by-step description of data movement through the system")
    agent_topology: str = Field(..., description="Agent graph shape (Orchestrator-Worker, ReAct loop, etc.)")
    tool_inventory: List[Dict[str, str]] = Field(default_factory=list, description="Tools used by agents with description")
    deployment_considerations: List[str] = Field(default_factory=list)
    identified_risks: List[str] = Field(default_factory=list)
    citations: List[str] = Field(default_factory=list, description="List of citation tags used throughout the architecture")


class TaskItem(BaseModel):
    task_id: str = Field(..., description="Stable task identifier (e.g. TASK-01)")
    title: str = Field(..., description="Clear, action-oriented title")
    description: str = Field(..., description="Precise implementation guide for an autonomous coding agent")
    target_files: List[str] = Field(default_factory=list, description="File paths to create or modify")
    acceptance_criteria: List[str] = Field(default_factory=list, description="Measurable pass/fail criteria")
    dependencies: List[str] = Field(default_factory=list, description="List of prior task IDs that must complete before this task")
    pattern_refs: List[str] = Field(default_factory=list, description="Agentic design patterns guiding this task")
    requirement_refs: List[str] = Field(default_factory=list, description="Requirement IDs mapped to this task for full traceability")
    order_index: int = Field(0, description="1-indexed topological order")


class TaskPlan(BaseModel):
    tasks: List[TaskItem] = Field(default_factory=list)


class CriticRubric(BaseModel):
    coverage_score: float = Field(..., description="Coverage of requirements (0.0 to 2.5)")
    ordering_score: float = Field(..., description="Dependency ordering and lack of forward dependencies (0.0 to 2.5)")
    fidelity_score: float = Field(..., description="Pattern fidelity in task definitions (0.0 to 2.5)")
    atomicity_score: float = Field(..., description="Atomicity and independent implementability of tasks (0.0 to 2.5)")
    total_score: float = Field(..., description="Sum of all 4 sub-scores (0.0 to 10.0)")
    is_passing: bool = Field(..., description="True if total_score >= 8.0")
    feedback: str = Field("", description="Actionable critique for the Planner if not passing")
    warnings: List[str] = Field(default_factory=list, description="Non-blocking observations or warnings")


class FeedbackClassification(BaseModel):
    target: Literal["architect", "planner"] = Field(..., description="Re-entry node for user feedback")
    reasoning: str = Field(..., description="Justification for the chosen target node")
