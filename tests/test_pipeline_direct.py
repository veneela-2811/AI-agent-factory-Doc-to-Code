import pytest
from pathlib import Path
from sqlalchemy.ext.asyncio import AsyncSession
from src.storage.models import Project, Document
from src.ingestion.pipeline import ingestion_pipeline
from src.storage.vector_store import vector_store


@pytest.mark.asyncio
async def test_pipeline_execution_direct(test_db: AsyncSession, tmp_path: Path):
    proj_id = "test-pipe-proj"
    doc_id = "test-pipe-doc"

    project = Project(id=proj_id, name="Pipeline Proj")
    test_db.add(project)

    doc_file = tmp_path / "prd.md"
    doc_file.write_text("# Overview\nSystem architecture.\n\n## Goals\nHigh speed execution.", encoding="utf-8")

    doc = Document(
        id=doc_id,
        project_id=proj_id,
        filename="prd.md",
        content_type="text/markdown",
        file_path=str(doc_file),
        file_size_bytes=len(doc_file.read_bytes()),
        content_hash="mock-hash-12345",
        status="pending"
    )
    test_db.add(doc)
    await test_db.commit()

    # Process through pipeline
    await ingestion_pipeline.process_document(
        project_id=proj_id,
        document_id=doc_id,
        file_path=doc_file,
        db=test_db
    )

    # Check updated status
    await test_db.refresh(doc)
    assert doc.status == "ready"
    assert doc.section_count == 2
    assert doc.chunk_count == 2

    # Verify RAG query finds it
    results = vector_store.query_documents(proj_id, "architecture", top_k=2)
    assert len(results) >= 1
    assert "System architecture" in results[0]["content"]
