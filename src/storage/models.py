import uuid
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from sqlalchemy import (
    Column, String, Text, Integer, Float, Boolean, DateTime, ForeignKey, JSON
)
from sqlalchemy.orm import relationship
from src.storage.database import Base


def utc_now():
    return datetime.now(timezone.utc)


class Project(Base):
    __tablename__ = "projects"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True, default="")
    status = Column(String(50), nullable=False, default="draft")  # draft, ready, running, archived
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    documents = relationship("Document", back_populates="project", cascade="all, delete-orphan")
    sections = relationship("DocumentSection", back_populates="project", cascade="all, delete-orphan")
    runs = relationship("Run", back_populates="project", cascade="all, delete-orphan")
    usages = relationship("Usage", back_populates="project", cascade="all, delete-orphan")
    audit_logs = relationship("AuditLog", back_populates="project", cascade="all, delete-orphan")
    events = relationship("RunEvent", back_populates="project", cascade="all, delete-orphan")
    tasks = relationship("Task", back_populates="project", cascade="all, delete-orphan")


class Document(Base):
    __tablename__ = "documents"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    filename = Column(String(255), nullable=False)
    content_type = Column(String(100), nullable=False)
    file_path = Column(String(512), nullable=False)
    file_size_bytes = Column(Integer, nullable=False, default=0)
    content_hash = Column(String(64), nullable=False, index=True)
    status = Column(String(50), nullable=False, default="pending")  # pending, parsing, ready, failed
    section_count = Column(Integer, nullable=False, default=0)
    chunk_count = Column(Integer, nullable=False, default=0)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    project = relationship("Project", back_populates="documents")
    sections = relationship("DocumentSection", back_populates="document", cascade="all, delete-orphan")


class DocumentSection(Base):
    __tablename__ = "document_sections"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    document_id = Column(String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    section_id = Column(String(100), nullable=False)  # e.g., "page_1", "sec_01"
    title = Column(String(255), nullable=False)
    level = Column(Integer, nullable=False, default=1)
    page_number = Column(Integer, nullable=True)
    content = Column(Text, nullable=False)
    chunk_index = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=utc_now)

    project = relationship("Project", back_populates="sections")
    document = relationship("Document", back_populates="sections")


class Pattern(Base):
    __tablename__ = "patterns"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(100), unique=True, nullable=False, index=True)
    intent = Column(Text, nullable=False)
    structure = Column(Text, nullable=False)
    when_to_use = Column(Text, nullable=False)
    when_not_to_use = Column(Text, nullable=False)
    prerequisites = Column(JSON, nullable=False, default=list)
    references = Column(JSON, nullable=False, default=list)
    tags = Column(JSON, nullable=False, default=list)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)


class Run(Base):
    __tablename__ = "runs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    workflow_name = Column(String(50), nullable=False)  # requirements, planning, codegen
    status = Column(String(50), nullable=False, default="pending")  # pending, running, paused, completed, failed
    current_node = Column(String(100), nullable=True)
    snapshotted_patterns = Column(JSON, nullable=True)
    input_data = Column(JSON, nullable=True)
    output_data = Column(JSON, nullable=True)
    error_message = Column(Text, nullable=True)
    started_at = Column(DateTime, default=utc_now)
    completed_at = Column(DateTime, nullable=True)

    project = relationship("Project", back_populates="runs")
    usages = relationship("Usage", back_populates="run", cascade="all, delete-orphan")
    events = relationship("RunEvent", back_populates="run", cascade="all, delete-orphan")
    tasks = relationship("Task", back_populates="run", cascade="all, delete-orphan")


class Usage(Base):
    __tablename__ = "usage"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    run_id = Column(String(36), ForeignKey("runs.id", ondelete="CASCADE"), nullable=True, index=True)
    node_name = Column(String(100), nullable=False)
    tool_name = Column(String(100), nullable=True)
    provider = Column(String(50), nullable=False)
    model = Column(String(100), nullable=False)
    tokens_in = Column(Integer, nullable=False, default=0)
    tokens_out = Column(Integer, nullable=False, default=0)
    cost_usd = Column(Float, nullable=False, default=0.0)
    latency_ms = Column(Float, nullable=False, default=0.0)
    created_at = Column(DateTime, default=utc_now)

    project = relationship("Project", back_populates="usages")
    run = relationship("Run", back_populates="usages")


class RunEvent(Base):
    __tablename__ = "run_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    run_id = Column(String(36), ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, index=True)
    event_type = Column(String(100), nullable=False)  # node_started, node_completed, clarification_requested, approval_requested, error, run_completed
    data = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=utc_now)

    project = relationship("Project", back_populates="events")
    run = relationship("Run", back_populates="events")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    actor = Column(String(100), nullable=False, default="system")
    action = Column(String(100), nullable=False)  # e.g., "project_created", "run_started", "approved"
    details = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=utc_now)

    project = relationship("Project", back_populates="audit_logs")


class Task(Base):
    __tablename__ = "tasks"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    run_id = Column(String(36), ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, index=True)
    task_id = Column(String(50), nullable=False)  # e.g., "TASK-01"
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=False)
    target_files = Column(JSON, nullable=False, default=list)
    acceptance_criteria = Column(JSON, nullable=False, default=list)
    dependencies = Column(JSON, nullable=False, default=list)
    pattern_refs = Column(JSON, nullable=False, default=list)
    requirement_refs = Column(JSON, nullable=False, default=list)
    order_index = Column(Integer, nullable=False, default=0)
    status = Column(String(50), nullable=False, default="pending")  # pending, in_progress, completed, failed
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    project = relationship("Project", back_populates="tasks")
    run = relationship("Run", back_populates="tasks")
