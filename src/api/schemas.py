from typing import Optional, List, Dict, Any, Union
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: Optional[Any] = None


class ErrorEnvelope(BaseModel):
    error: ErrorDetail


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in_minutes: int


class LoginRequest(BaseModel):
    username: str = Field(..., json_schema_extra={"example": "admin"})
    password: str = Field(..., json_schema_extra={"example": "password123"})


class RegisterRequest(BaseModel):
    username: str = Field(..., json_schema_extra={"example": "admin"})
    password: str = Field(..., json_schema_extra={"example": "password123"})


class ProjectCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255, json_schema_extra={"example": "E-Commerce Agent"})
    description: Optional[str] = Field(default="", json_schema_extra={"example": "Agentic system for e-commerce inventory"})


class ProjectUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = None
    status: Optional[str] = Field(default=None, json_schema_extra={"example": "ready"})


class ProjectResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: Optional[str] = ""
    status: str
    created_at: datetime
    updated_at: datetime


class ProjectListResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    projects: List[ProjectResponse]
    total: int


class DocumentUploadResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    document_id: str
    project_id: str
    filename: str
    status: str
    file_size_bytes: int
    content_hash: str
    status_url: str


class DocumentStatusResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    filename: str
    content_type: str
    status: str  # pending, parsing, ready, failed
    section_count: int
    chunk_count: int
    file_size_bytes: int
    error_message: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class DocumentSectionItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    section_id: str
    title: str
    level: int
    page_number: Optional[int] = None
    chunk_index: int


class DocumentOutlineResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    document_id: str
    project_id: str
    filename: str
    total_sections: int
    sections: List[DocumentSectionItem]


# ==========================================
# Milestone 2: Agentic Design Patterns Schemas
# ==========================================

class PatternCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, json_schema_extra={"example": "ReAct"})
    intent: str = Field(..., min_length=10, json_schema_extra={"example": "Interleaves reasoning with action execution against tools."})
    structure: str = Field(..., min_length=10, json_schema_extra={"example": "Loop of Thought -> Action -> Observation."})
    when_to_use: str = Field(..., min_length=5, json_schema_extra={"example": "Dynamic tool-use, multi-step problem solving."})
    when_not_to_use: str = Field(..., min_length=5, json_schema_extra={"example": "Static single-shot workflows."})
    prerequisites: List[str] = Field(default_factory=list, json_schema_extra={"example": ["Tool calling interface", "Scratchpad memory"]})
    references: List[str] = Field(default_factory=list, json_schema_extra={"example": ["https://arxiv.org/abs/2210.03629"]})
    tags: List[str] = Field(default_factory=list, json_schema_extra={"example": ["single-agent", "tool-use", "reasoning"]})


class PatternUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    intent: Optional[str] = None
    structure: Optional[str] = None
    when_to_use: Optional[str] = None
    when_not_to_use: Optional[str] = None
    prerequisites: Optional[List[str]] = None
    references: Optional[List[str]] = None
    tags: Optional[List[str]] = None


class PatternResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    intent: str
    structure: str
    when_to_use: str
    when_not_to_use: str
    prerequisites: List[str]
    references: List[str]
    tags: List[str]
    created_at: datetime
    updated_at: datetime


class PatternListResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    patterns: List[PatternResponse]
    total: int


class PatternSearchRequest(BaseModel):
    query: str = Field(..., min_length=1, json_schema_extra={"example": "Need an agent that can query external APIs and reason over tool outputs"})
    tags: Optional[List[str]] = Field(default=None, json_schema_extra={"example": ["tool-use", "reasoning"]})
    top_k: int = Field(default=8, ge=1, le=50, json_schema_extra={"example": 8})


class PatternSearchResultItem(BaseModel):
    id: str
    name: str
    similarity_score: float
    matched_fields: List[str] = Field(default_factory=lambda: ["intent", "when_to_use", "structure"])
    pattern: PatternResponse


class PatternSearchResponse(BaseModel):
    query: str
    total_matched: int
    results: List[PatternSearchResultItem]


class HealthCheckResponse(BaseModel):
    status: str
    app_name: str
    version: str
    sqlite_healthy: bool
    chromadb_healthy: bool
    filestore_healthy: bool
