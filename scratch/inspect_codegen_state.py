import sys
sys.path.insert(0, ".")
import asyncio
import json
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from src.workflows.codegen.graph import build_codegen_graph

async def main():
    project_id = "efcec30a-d5c2-4081-9d90-1b1cb6e47965"
    run_id = "1d2f9cc8-53cf-4d27-b7e2-db57471877d4"
    config = {"configurable": {"thread_id": f"{project_id}_{run_id}", "project_id": project_id, "run_id": run_id}}
    
    async with AsyncSqliteSaver.from_conn_string("data/checkpoints.sqlite") as cp:
        graph = build_codegen_graph().compile(checkpointer=cp)
        state = await graph.aget_state(config)
        print("NEXT NODES:", state.next)
        print("TASKS COUNT:", len(state.tasks))
        for t in state.tasks:
            print("TASK NAME:", t.name)
            print("INTERRUPTS:", t.interrupts)
            for i in t.interrupts:
                print("INTR VALUE:", i.value)
        print("STATE VALUES KEYS:", list(state.values.keys()))
        print("CURRENT NODE:", state.values.get("current_node"))
        print("CURRENT TASK INDEX:", state.values.get("current_task_index"))
        print("CURRENT TASK ITERATION:", state.values.get("current_task_iteration"))
        print("CURRENT REVIEW:", state.values.get("current_task_review"))
        print("COMPLETED TASKS:", state.values.get("completed_tasks"))

if __name__ == "__main__":
    asyncio.run(main())
