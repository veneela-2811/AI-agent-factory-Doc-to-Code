import os
import json
import zipfile
from pathlib import Path
from typing import Dict, Any, List
from datetime import datetime, timezone

from src.storage.filestore import file_store
from src.workflows.codegen.schemas import ManifestDoc, ManifestTaskEntry


def generate_manifest_and_bundle(
    project_id: str,
    run_id: str,
    completed_tasks: List[Dict[str, Any]]
) -> Dict[str, Any]:
    workspace_dir = file_store.get_workspace_dir(project_id, run_id)
    runs_dir = file_store.get_runs_dir(project_id, run_id)

    # 1. Collect all files in workspace
    all_files = []
    if workspace_dir.exists():
        for root, _, files in os.walk(workspace_dir):
            for file in files:
                if file in ["MANIFEST.json", "bundle.zip"]:
                    continue
                full_path = Path(root) / file
                rel_path = full_path.relative_to(workspace_dir).as_posix()
                all_files.append(rel_path)

    all_files.sort()

    # 2. Build task entries
    task_entries = []
    for t in completed_tasks:
        rev = t.get("review") or {}
        task_entries.append(
            ManifestTaskEntry(
                task_id=t.get("task_id", ""),
                title=t.get("title", ""),
                status=t.get("status", "completed"),
                target_files=t.get("target_files", []),
                pattern_refs=t.get("pattern_refs", []),
                iterations=t.get("iterations", 1),
                review_verdict=rev.get("verdict", "pass"),
                reviewers_passed=rev.get("passed_reviewers", []),
                reviewers_failed=rev.get("failed_reviewers", [])
            )
        )

    manifest_doc = ManifestDoc(
        project_id=project_id,
        run_id=run_id,
        generated_at=datetime.now(timezone.utc).isoformat(),
        task_count=len(completed_tasks),
        total_files=len(all_files),
        files=all_files,
        tasks=task_entries
    )

    manifest_json = manifest_doc.model_dump()

    # Write MANIFEST.json to run dir and workspace
    manifest_path_runs = runs_dir / "MANIFEST.json"
    manifest_path_ws = workspace_dir / "MANIFEST.json"
    with open(manifest_path_runs, "w", encoding="utf-8") as f:
        json.dump(manifest_json, f, indent=2)
    with open(manifest_path_ws, "w", encoding="utf-8") as f:
        json.dump(manifest_json, f, indent=2)

    # 3. Zip workspace into bundle.zip
    bundle_zip_path = runs_dir / "bundle.zip"
    with zipfile.ZipFile(bundle_zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
        if workspace_dir.exists():
            for root, _, files in os.walk(workspace_dir):
                for file in files:
                    if file == "bundle.zip":
                        continue
                    full_path = Path(root) / file
                    arcname = full_path.relative_to(workspace_dir).as_posix()
                    zipf.write(full_path, arcname=arcname)

    return {
        "manifest": manifest_json,
        "bundle_path": str(bundle_zip_path.resolve()),
        "manifest_path": str(manifest_path_runs.resolve()),
        "total_files": len(all_files),
        "bundle_size_bytes": bundle_zip_path.stat().st_size if bundle_zip_path.exists() else 0
    }
