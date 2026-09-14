from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field


class RequirementsRequirement(BaseModel):
    id: str = Field(..., description="Unique requirement ID (e.g., REQ-01, REQ-02)")
    title: str = Field(..., description="Short descriptive title of requirement")
    description: str = Field(..., description="Detailed specification of what must be implemented")
    category: str = Field(default="functional", description="functional | non_functional")
    priority: str = Field(default="must_have", description="must_have | should_have | nice_to_have")
    acceptance_criteria: List[str] = Field(default_factory=list, description="Verifiable acceptance criteria")
    source_sections: List[str] = Field(default_factory=list, description="Source document section IDs for traceability")


class RequirementsPersona(BaseModel):
    role: str = Field(..., description="Target user role or persona")
    description: str = Field(..., description="Background description of this persona")
    goals: List[str] = Field(default_factory=list, description="Primary goals for this persona")


class RequirementsStructuredDoc(BaseModel):
    project_name: str = Field(..., description="Name of the project")
    overview: str = Field(..., description="Executive summary and system scope")
    goals: List[str] = Field(default_factory=list, description="High-level business and technical goals")
    personas: List[RequirementsPersona] = Field(default_factory=list, description="Key target user personas")
    functional_requirements: List[RequirementsRequirement] = Field(default_factory=list, description="Core functional capabilities")
    non_functional_requirements: List[RequirementsRequirement] = Field(default_factory=list, description="Performance, security, and scalability requirements")
    constraints: List[str] = Field(default_factory=list, description="Technical, architectural, and business constraints")
    out_of_scope: List[str] = Field(default_factory=list, description="Explicitly excluded features")
    open_questions: List[str] = Field(default_factory=list, description="Resolved or remaining items")
    traceability_mapping: Dict[str, List[str]] = Field(default_factory=dict, description="Map of requirement ID to document section IDs")


class ClarificationQuestionItem(BaseModel):
    id: str = Field(..., description="Unique question identifier (e.g. q1, q2)")
    question: str = Field(..., description="Targeted clarification question")
    context: str = Field(default="", description="Why this clarification is necessary")


class GapAnalysisResult(BaseModel):
    has_critical_gaps: bool = Field(default=False, description="True if critical ambiguities or missing constraints exist")
    summary: str = Field(default="", description="Summary of completeness evaluation")
    gaps_identified: List[str] = Field(default_factory=list, description="Identified missing requirements or ambiguities")
    clarification_questions: List[ClarificationQuestionItem] = Field(default_factory=list, description="Targeted questions for the user")
