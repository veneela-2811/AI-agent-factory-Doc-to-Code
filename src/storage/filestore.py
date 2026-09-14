import os
import shutil
import aiofiles
from pathlib import Path
from typing import Optional, BinaryIO
from config.settings import settings


class FileStore:
    def __init__(self, root_dir: Optional[Path] = None):
        self.root = root_dir or settings.DATA_ROOT / "projects"
        self.root.mkdir(parents=True, exist_ok=True)

    def get_project_dir(self, project_id: str) -> Path:
        p_dir = self.root / project_id
        p_dir.mkdir(parents=True, exist_ok=True)
        return p_dir

    def get_uploads_dir(self, project_id: str) -> Path:
        u_dir = self.get_project_dir(project_id) / "uploads"
        u_dir.mkdir(parents=True, exist_ok=True)
        return u_dir

    def get_runs_dir(self, project_id: str, run_id: str) -> Path:
        r_dir = self.get_project_dir(project_id) / "runs" / run_id
        r_dir.mkdir(parents=True, exist_ok=True)
        return r_dir

    def get_workspace_dir(self, project_id: str, run_id: str) -> Path:
        w_dir = self.get_runs_dir(project_id, run_id) / "workspace"
        w_dir.mkdir(parents=True, exist_ok=True)
        return w_dir

    async def save_upload(
        self,
        project_id: str,
        document_id: str,
        filename: str,
        content: bytes
    ) -> Path:
        ext = Path(filename).suffix.lower()
        target_path = self.get_uploads_dir(project_id) / f"{document_id}{ext}"
        async with aiofiles.open(target_path, "wb") as f:
            await f.write(content)
        return target_path

    async def read_file(self, file_path: Path) -> bytes:
        async with aiofiles.open(file_path, "rb") as f:
            return await f.read()

    def delete_project_dir(self, project_id: str) -> None:
        p_dir = self.root / project_id
        if p_dir.exists():
            shutil.rmtree(p_dir)


file_store = FileStore()
