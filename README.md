# AI Agent Factory v2: Document-Driven, Pattern-Aware Code Generator

A production-grade, backend-only AI Agent Factory that ingests business and technical specifications (BRD / PRD / TRD in PDF, DOCX, PPTX, XLSX, MD, TXT) and autonomously drives three sequential agentic workflows to produce a working, pattern-aware codebase.

Powered by an **Adaptive Multi-LLM Routing Engine** that decouples business logic from model providers and optimizes for zero-cost development while enabling target frontier backbones (GPT-5.4 / GPT-5.5) in production.

---

## Architecture Overview

The system consists of three sequential LangGraph workflows:

1. Requirements Gathering
2. Project & Code Planning
3. Code Generation

Each workflow is checkpointed using SQLite and supports Human-in-the-Loop (HITL) through WebSocket.

---

## Workflow 1: Requirements Gathering

```text
                    ┌──────────────────────┐
                    │  Business / Technical│
                    │      Documents       │
                    └──────────┬───────────┘
                               │
                               ▼
                    ┌──────────────────────┐
                    │  Document Processing  │
                    │ PDF / DOCX / PPTX /   │
                    │ XLSX / MD / TXT       │
                    └──────────┬───────────┘
                               │
                               ▼
                    ┌──────────────────────┐
                    │   Content Extraction  │
                    │   + Chunking + RAG    │
                    └──────────┬───────────┘
                               │
                               ▼
                    ┌──────────────────────┐
                    │ Requirements Analyzer│
                    │  & Gap Identification │
                    └──────────┬───────────┘
                               │
                    ┌──────────┴──────────┐
                    │                     │
              Gaps Found?              No Gaps
                    │                     │
                   Yes                    │
                    ▼                     │
          ┌────────────────────┐          │
          │  HITL Clarification│          │
          │    via WebSocket   │          │
          └──────────┬─────────┘          │
                     │                    │
                     └────────┬───────────┘
                              ▼
                   ┌──────────────────────┐
                   │ Canonical Requirements│
                   │     JSON + Markdown   │
                   └──────────┬───────────┘
                              │
                              ▼
                   ┌──────────────────────┐
                   │   Human Approval     │
                   │      via WebSocket   │
                   └──────────┬───────────┘
                              │
                              ▼
                   Requirements Approved

---


## Workflow 2: Project & Code Planning

                 Approved Requirements
                          │
                          ▼
                ┌─────────────────────┐
                │   Pattern Selector  │
                │ Global Pattern KB   │
                └──────────┬──────────┘
                           │
                           ▼
                ┌─────────────────────┐
                │   Research Phase    │
                │                     │
                │ ┌─────────────────┐ │
                │ │ Project Docs RAG │ │
                │ ├─────────────────┤ │
                │ │ Pattern KB RAG   │ │
                │ ├─────────────────┤ │
                │ │ Web Search       │ │
                │ └─────────────────┘ │
                └──────────┬──────────┘
                           │
                           ▼
                ┌─────────────────────┐
                │  Architecture Agent │
                │  Architecture JSON  │
                │     + Markdown      │
                └──────────┬──────────┘
                           │
                           ▼
                ┌─────────────────────┐
                │   Task Planner      │
                │                     │
                │ Ordered Code Tasks  │
                │ Dependencies        │
                │ Target Files        │
                │ Acceptance Criteria │
                │ Pattern References  │
                └──────────┬──────────┘
                           │
                           ▼
                ┌─────────────────────┐
                │   Critic / Validator│
                │                     │
                │ Coverage            │
                │ Ordering            │
                │ Pattern Fidelity    │
                │ Task Atomicity      │
                └──────────┬──────────┘
                           │
                     Valid Plan?
                    ┌──────┴──────┐
                   No             Yes
                   │               │
                   ▼               ▼
             Revise Plan      HITL Approval
                   │           via WebSocket
                   └──────┐        │
                          │        ▼
                          └──► Approved Plan

## Workflow 2 Research

                    Research Request
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
        Project Docs    Pattern KB    Web Search
            RAG             RAG           │
              │              │            │
              └──────────────┼────────────┘
                             ▼
                    ┌─────────────────┐
                    │ Research Results│
                    │ + Citations     │
                    └─────────────────┘

## Workflow 3: Code Generation

                    Approved Task Plan
                           │
                           ▼
                ┌─────────────────────┐
                │ Developer Orchestrator│
                └──────────┬──────────┘
                           │
                           ▼
                 Execute Tasks Sequentially
                           │
                           ▼
                ┌─────────────────────┐
                │  Current Task       │
                │                     │
                │ Read dependency     │
                │ files + workspace   │
                │ context             │
                └──────────┬──────────┘
                           │
                           ▼
                ┌─────────────────────┐
                │ Dynamic Task Graph  │
                │ based on patterns   │
                └──────────┬──────────┘
                           │
                           ▼
                ┌─────────────────────┐
                │   Developer Agent   │
                │   Generate Code     │
                └──────────┬──────────┘
                           │
                           ▼
              ┌───────────────────────────┐
              │   Parallel Reviewers      │
              │                           │
              │ ┌───────────────────────┐ │
              │ │ Workflow Reviewer     │ │
              │ ├───────────────────────┤ │
              │ │ Prompt Reviewer       │ │
              │ ├───────────────────────┤ │
              │ │ Security Reviewer     │ │
              │ └───────────────────────┘ │
              └─────────────┬─────────────┘
                            │
                            ▼
                   ┌──────────────────┐
                   │ Review Aggregator│
                   └────────┬─────────┘
                            │
                     Pass or Fail?
                    ┌───────┴────────┐
                   Pass              Fail
                    │                  │
                    │                  ▼
                    │           Retry with Feedback
                    │                  │
                    │             Retry Limit?
                    │             ┌─────┴─────┐
                    │            No           Yes
                    │             │             │
                    │             └──► Review   ▼
                    │                    HITL Escalation
                    │
                    ▼
             Execute Next Task
                    │
                    ▼
              All Tasks Done?
                    │
                    ▼
             ┌──────────────────┐
             │ Final Validation │
             └────────┬─────────┘
                      │
                      ▼
               Human Approval
                via WebSocket
                      │
                      ▼
             ┌──────────────────┐
             │  ZIP Code Bundle │
             │ + MANIFEST.json  │
             └──────────────────┘


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

---

