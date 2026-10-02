import sys
sys.path.insert(0, ".")
import asyncio
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from src.workflows.codegen.graph import build_codegen_graph

async def main():
    project_id = "efcec30a-d5c2-4081-9d90-1b1cb6e47965"
    run_id = "a0e931d6-7a60-4f99-b69f-4b87874da783"
    config = {"configurable": {"thread_id": f"{project_id}_{run_id}", "project_id": project_id, "run_id": run_id}}
    
    async with AsyncSqliteSaver.from_conn_string("data/checkpoints.sqlite") as cp:
        graph = build_codegen_graph().compile(checkpointer=cp)
        try:
            async for chunk in graph.astream(None, config, stream_mode="values"):
                print("CHUNK CURRENT NODE:", chunk.get("current_node"))
                print("CHUNK TASK INDEX:", chunk.get("current_task_index"))
                print("CHUNK TASK REVIEW:", chunk.get("current_task_review"))
        except Exception as e:
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
