import pytest
from pathlib import Path
from src.storage.filestore import FileStore


@pytest.mark.asyncio
async def test_filestore_operations(tmp_path: Path):
    store = FileStore(root_dir=tmp_path)
    project_id = "proj-123"
    doc_id = "doc-456"
    content = b"# Sample Spec Content"

    # Save upload
    file_path = await store.save_upload(project_id, doc_id, "spec.md", content)
    assert file_path.exists()
    assert file_path.name == f"{doc_id}.md"

    # Read file
    read_back = await store.read_file(file_path)
    assert read_back == content

    # Check project directory isolation
    p_dir = store.get_project_dir(project_id)
    assert p_dir.exists()
