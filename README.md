# AI Agent Factory v2: Document-Driven, Pattern-Aware Code Generator

A production-grade, backend-only AI Agent Factory that ingests business and technical specifications (BRD / PRD / TRD in PDF, DOCX, PPTX, XLSX, MD, TXT) and autonomously drives three sequential agentic workflows to produce a working, pattern-aware codebase.

Powered by an **Adaptive Multi-LLM Routing Engine** that decouples business logic from model providers and optimizes for zero-cost development while enabling target frontier backbones (GPT-5.4 / GPT-5.5) in production.

---

## Architecture Overview

```
[Business Documents] (PDF, DOCX, XLSX, PPTX, MD, TXT)
       │
       ▼
┌────────────────────────────────────────────────────────┐
│ Document Ingestion & Parsers                           │
│  - Heading-Aware Structured Section Extraction         │
│  - Project-Isolated Vector Embeddings (ChromaDB)       │
└──────────────────────────┬─────────────────────────────┘
                           ▼
┌────────────────────────────────────────────────────────┐
│ Pattern Knowledge Base (Global Curated Library)        │
│  - 10 Canonical Patterns Seeded on Startup             │
│  - Semantic Vector Search + Similarity Scores          │
└──────────────────────────┬─────────────────────────────┘
                           ▼
┌────────────────────────────────────────────────────────┐
│ Adaptive Multi-LLM Router                              │
│  - Task Capability Classifier                          │
│  - Provider Registry (OpenAI, Gemini, Groq, Ollama)   │
│  - Capability-Aware Fallback & Cooldown Engine         │
└──────────────────────────┬─────────────────────────────┘
                           ▼
┌────────────────────────────────────────────────────────┐
│ 3 Autonomous Agentic Workflows                         │
│  1. Requirements Gathering (Reflection + HITL WS)      │
│  2. Combined Planning (RAG + Research + Critic Loop)   │
│  3. Code Generation (Dynamic Subgraphs + Reviewers)    │
└────────────────────────────────────────────────────────┘
```

---

## Quickstart Guide

### 1. Environment Setup
```powershell
cd C:/Users/venee/OneDrive/Desktop/HashedIn/agent_factory
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 2. Run Test Suite
```powershell
.\.venv\Scripts\pytest.exe -v
```

### 3. Start Application Server
```powershell
.\.venv\Scripts\uvicorn.exe src.main:app --host 127.0.0.1 --port 8000 --reload
```
Interactive Swagger documentation is available at: **http://127.0.0.1:8000/docs**
