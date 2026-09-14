import time
import json
from typing import Dict, Any
from src.llm.base import BaseLLMAdapter
from src.llm.schemas import LLMRequest, LLMResponse, ModelCapability


class MockLLMAdapter(BaseLLMAdapter):
    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}

    def is_available(self) -> bool:
        return True

    async def health_check(self) -> bool:
        return True

    async def generate(self, request: LLMRequest, model: ModelCapability) -> LLMResponse:
        start_time = time.time()
        
        # Build deterministic mock response based on task name & schema
        if request.response_schema:
            if request.task_name == "requirements_synthesis":
                mock_structured = {
                    "project_name": "Autonomous Agent Platform",
                    "overview": "Production-grade document-driven AI agent factory platform.",
                    "goals": [
                        "Turn business specifications into verifiable working code",
                        "Maintain pattern fidelity and end-to-end requirement traceability",
                        "Enforce human-in-the-loop approval gates"
                    ],
                    "personas": [
                        {
                            "role": "Lead Architect",
                            "description": "Designs system architecture and validates agent design patterns.",
                            "goals": ["Ensure architectural integrity", "Approve code plans"]
                        },
                        {
                            "role": "End User / Operator",
                            "description": "Uploads technical documents and monitors workflow execution.",
                            "goals": ["Track task execution", "Download generated code bundle"]
                        }
                    ],
                    "functional_requirements": [
                        {
                            "id": "REQ-01",
                            "title": "Document Parsing and Heading-Aware Chunking",
                            "description": "Ingest PDF, DOCX, XLSX, PPTX, and Markdown documents into structured sections.",
                            "category": "functional",
                            "priority": "must_have",
                            "acceptance_criteria": [
                                "Extract clean sections with persistent IDs",
                                "Store dense embeddings in ChromaDB filtered by project_id"
                            ],
                            "source_sections": ["sec_1", "sec_2"]
                        },
                        {
                            "id": "REQ-02",
                            "title": "Human-in-the-Loop Clarification and Approval",
                            "description": "Provide a bidirectional WebSocket channel to answer agent questions and approve outputs.",
                            "category": "functional",
                            "priority": "must_have",
                            "acceptance_criteria": [
                                "Server pushes typed clarification_request on interrupt",
                                "Resume execution upon receiving clarification_response",
                                "Persist checkpoint state to SQLite"
                            ],
                            "source_sections": ["sec_3"]
                        },
                        {
                            "id": "REQ-03",
                            "title": "Pattern-Aware Architecture and Task Planning",
                            "description": "Select agentic design patterns from the Pattern KB and generate an ordered task list.",
                            "category": "functional",
                            "priority": "must_have",
                            "acceptance_criteria": [
                                "Query Pattern KB with semantic similarity search",
                                "Conduct multi-source research with source citations",
                                "Validate task list ordering and requirement coverage"
                            ],
                            "source_sections": ["sec_4"]
                        }
                    ],
                    "non_functional_requirements": [
                        {
                            "id": "NFR-01",
                            "title": "Performance and Latency",
                            "description": "Maintain sub-500ms response time for API operations and low-latency streaming over SSE.",
                            "category": "non_functional",
                            "priority": "must_have",
                            "acceptance_criteria": ["SSE stream latency under 100ms"],
                            "source_sections": ["sec_1"]
                        },
                        {
                            "id": "NFR-02",
                            "title": "Security and Isolation",
                            "description": "Ensure project-scoped data isolation in SQLite and ChromaDB with JWT authentication.",
                            "category": "non_functional",
                            "priority": "must_have",
                            "acceptance_criteria": ["Reject cross-project access with 404"],
                            "source_sections": ["sec_1"]
                        }
                    ],
                    "constraints": [
                        "FastAPI backend with Python 3.12",
                        "SQLite with aiosqlite and ChromaDB local vector store",
                        "LangGraph checkpointing for crash resilience"
                    ],
                    "out_of_scope": [
                        "Multi-tenant team management and RBAC",
                        "Conversational chat UI"
                    ],
                    "open_questions": [],
                    "traceability_mapping": {
                        "REQ-01": ["sec_1", "sec_2"],
                        "REQ-02": ["sec_3"],
                        "REQ-03": ["sec_4"],
                        "NFR-01": ["sec_1"],
                        "NFR-02": ["sec_1"]
                    }
                }
            elif request.task_name == "gap_analysis_reflection":
                mock_structured = {
                    "has_critical_gaps": True,
                    "summary": "Document evaluated. Identified unstated technical deployment constraints.",
                    "gaps_identified": ["Deployment environment and persistence constraints unspecified"],
                    "clarification_questions": [
                        {
                            "id": "q1",
                            "question": "What is the primary target environment and deployment constraint for this project?",
                            "context": "No technical deployment constraints were detected in uploaded documents."
                        }
                    ]
                }
            else:
                mock_structured = {
                    "summary": f"Deterministic mock output for task: {request.task_name}",
                    "status": "success",
                    "extracted_entities": ["requirement_1", "requirement_2"],
                    "gaps_identified": [],
                    "patterns_selected": ["Planner-Executor", "Reflection"],
                    "is_mock": True
                }
            content = json.dumps(mock_structured)
            structured_data = mock_structured
        else:
            content = f"Mock LLM generated response for {request.task_name} using model {model.name}."
            structured_data = None

        latency = (time.time() - start_time) * 1000
        return LLMResponse(
            content=content,
            structured_data=structured_data,
            model_used=model.id,
            provider_used=model.provider,
            tokens_in=len(str(request.messages)) // 4,
            tokens_out=len(content) // 4,
            cost_usd=0.0,
            latency_ms=latency
        )
