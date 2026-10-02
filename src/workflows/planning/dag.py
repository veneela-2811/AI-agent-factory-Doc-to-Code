import logging
from typing import List, Dict, Any, Tuple, Set

logger = logging.getLogger("planning_dag")


class DAGValidationError(Exception):
    def __init__(self, message: str, errors: List[str]):
        super().__init__(message)
        self.errors = errors


def validate_task_dag(tasks: List[Dict[str, Any]]) -> Tuple[bool, List[str], List[str]]:
    """
    Validates a list of tasks for:
    1. Unique task IDs
    2. Dependency reference existence
    3. No self-dependencies
    4. No circular dependencies (DAG cycle detection via Kahn's algorithm)
    5. No forward dependencies (each dependency must appear strictly before the task in index order)
    
    Returns: (is_valid, errors, topologically_sorted_ids)
    """
    errors = []
    task_ids = set()
    id_to_index = {}

    for idx, t in enumerate(tasks):
        tid = t.get("task_id")
        if not tid:
            errors.append(f"Task at index {idx} is missing 'task_id'")
            continue
        if tid in task_ids:
            errors.append(f"Duplicate task_id detected: '{tid}'")
        task_ids.add(tid)
        id_to_index[tid] = idx

    # Check dependencies exist & no forward dependencies
    for idx, t in enumerate(tasks):
        tid = t.get("task_id")
        deps = t.get("dependencies", []) or []
        for dep in deps:
            if dep == tid:
                errors.append(f"Task '{tid}' has a self-dependency")
            elif dep not in task_ids:
                errors.append(f"Task '{tid}' depends on non-existent task '{dep}'")
            elif id_to_index.get(dep, 0) >= idx:
                errors.append(
                    f"Forward dependency violation: Task '{tid}' (index {idx}) depends on '{dep}' (index {id_to_index.get(dep)}) which appears after it."
                )

    # Kahn's algorithm for cycle detection
    in_degree = {tid: 0 for tid in task_ids}
    adj = {tid: [] for tid in task_ids}

    for t in tasks:
        tid = t.get("task_id")
        if not tid or tid not in task_ids:
            continue
        deps = t.get("dependencies", []) or []
        for dep in deps:
            if dep in task_ids and dep != tid:
                adj[dep].append(tid)
                in_degree[tid] += 1

    queue = [tid for tid, deg in in_degree.items() if deg == 0]
    sorted_ids = []

    while queue:
        u = queue.pop(0)
        sorted_ids.append(u)
        for v in adj[u]:
            in_degree[v] -= 1
            if in_degree[v] == 0:
                queue.append(v)

    if len(sorted_ids) != len(task_ids):
        unresolved = [tid for tid, deg in in_degree.items() if deg > 0]
        errors.append(f"Circular dependency cycle detected among tasks: {unresolved}")

    return len(errors) == 0, errors, sorted_ids


def split_task(
    tasks: List[Dict[str, Any]],
    target_task_id: str,
    subtasks_data: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """
    Splits target_task_id into multiple subtasks (e.g., TASK-02-A, TASK-02-B).
    Downstream tasks depending on target_task_id will now depend on the last subtask.
    """
    if not subtasks_data:
        raise ValueError("Cannot split task into empty subtask list")

    target_idx = None
    target_task = None
    for idx, t in enumerate(tasks):
        if t.get("task_id") == target_task_id:
            target_idx = idx
            target_task = t
            break

    if target_idx is None or target_task is None:
        raise ValueError(f"Task '{target_task_id}' not found in task list")

    created_subtasks = []
    base_deps = list(target_task.get("dependencies", []))
    prev_id = None

    for i, sub in enumerate(subtasks_data):
        sub_id = sub.get("task_id") or f"{target_task_id}-{chr(65 + i)}"
        deps = list(sub.get("dependencies", []))
        if i == 0 and not deps:
            deps = base_deps
        elif i > 0 and not deps and prev_id:
            deps = [prev_id]

        new_t = {
            "task_id": sub_id,
            "title": sub.get("title", f"{target_task.get('title')} (Part {i+1})"),
            "description": sub.get("description", target_task.get("description")),
            "target_files": sub.get("target_files", target_task.get("target_files", [])),
            "acceptance_criteria": sub.get("acceptance_criteria", target_task.get("acceptance_criteria", [])),
            "dependencies": deps,
            "pattern_refs": sub.get("pattern_refs", target_task.get("pattern_refs", [])),
            "requirement_refs": sub.get("requirement_refs", target_task.get("requirement_refs", [])),
            "status": "pending",
        }
        created_subtasks.append(new_t)
        prev_id = sub_id

    last_subtask_id = created_subtasks[-1]["task_id"]

    # Reassemble task list
    new_tasks = []
    for idx, t in enumerate(tasks):
        if idx == target_idx:
            new_tasks.extend(created_subtasks)
        else:
            # Update dependencies pointing to old target_task_id
            t_copy = dict(t)
            deps = t_copy.get("dependencies", []) or []
            if target_task_id in deps:
                new_deps = [d for d in deps if d != target_task_id] + [last_subtask_id]
                t_copy["dependencies"] = new_deps
            new_tasks.append(t_copy)

    # Re-index order
    for idx, t in enumerate(new_tasks):
        t["order_index"] = idx + 1

    # Validate resulting DAG
    is_valid, errs, _ = validate_task_dag(new_tasks)
    if not is_valid:
        raise DAGValidationError(f"Split resulted in invalid DAG: {', '.join(errs)}", errs)

    return new_tasks
