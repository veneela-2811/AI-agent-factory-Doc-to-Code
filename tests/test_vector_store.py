import pytest
from src.storage.vector_store import ChromaVectorStore


def test_chroma_vector_store_isolation(tmp_path):
    store = ChromaVectorStore(persist_dir=str(tmp_path / "chroma"))
    proj_a = "project-aaa"
    proj_b = "project-bbb"
    doc_id = "doc-001"

    # Upsert chunks for project A
    chunks_a = [{
        "section_id": "sec_1",
        "title": "Alpha Intro",
        "page_number": 1,
        "chunk_index": 0,
        "content": "Alpha project requires low latency agent workflows.",
        "kind": "PRD"
    }]
    store.upsert_document_chunks(proj_a, doc_id, chunks_a)

    # Upsert chunks for project B
    chunks_b = [{
        "section_id": "sec_1",
        "title": "Beta Intro",
        "page_number": 1,
        "chunk_index": 0,
        "content": "Beta project requires blockchain token verification.",
        "kind": "PRD"
    }]
    store.upsert_document_chunks(proj_b, "doc-002", chunks_b)

    # Query Project A - Should ONLY return project A data
    results_a = store.query_documents(proj_a, "latency agent", top_k=5)
    assert len(results_a) == 1
    assert "Alpha project" in results_a[0]["content"]
    assert results_a[0]["metadata"]["project_id"] == proj_a

    # Query Project A for project B's keyword - Must NOT return project B data
    results_a_leak_check = store.query_documents(proj_a, "blockchain token", top_k=5)
    for r in results_a_leak_check:
        assert r["metadata"]["project_id"] == proj_a

    # Upsert & Query Pattern in Global KB
    store.upsert_pattern(
        pattern_id="react-pattern",
        name="ReAct",
        intent="ReAct interleaves reasoning and acting to solve multi-step tasks.",
        structure="Thought -> Action -> Observation loop",
        when_to_use="Dynamic tool calling and environment interaction",
        when_not_to_use="Static single-shot classification",
        tags=["tool-use", "reasoning"]
    )
    pattern_results = store.query_patterns("reasoning and acting", top_k=2)
    assert len(pattern_results) >= 1
    assert "ReAct" in pattern_results[0]["name"]
