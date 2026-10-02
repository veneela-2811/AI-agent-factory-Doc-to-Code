import io
import logging
from pathlib import Path
from fastapi import APIRouter, HTTPException, status, Response
from fastapi.responses import PlainTextResponse

from src.workflows.requirements.graph import build_requirements_graph
from src.workflows.planning.graph import build_planning_graph

logger = logging.getLogger("workflow_diagrams")
router = APIRouter(prefix="/workflows", tags=["Workflow Diagrams"])

CACHE_DIR = Path("./data/diagrams")
CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _get_graph_by_name(name: str):
    if name in ["requirements", "workflow_1", "requirements_gathering"]:
        return build_requirements_graph().compile()
    elif name in ["planning", "workflow_2", "project_planning"]:
        return build_planning_graph().compile()
    else:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": {"code": "WORKFLOW_NOT_FOUND", "message": f"Workflow '{name}' not recognized", "details": None}}
        )


@router.get(
    "/{name}/mermaid",
    summary="Get workflow diagram as Mermaid code"
)
async def get_workflow_mermaid(name: str):
    graph = _get_graph_by_name(name)
    mermaid_code = graph.get_graph().draw_mermaid()
    return PlainTextResponse(content=mermaid_code)


@router.get(
    "/{name}/graph.png",
    summary="Get workflow diagram as rendered PNG (cached on disk)"
)
async def get_workflow_graph_png(name: str):
    cache_path = CACHE_DIR / f"{name}.png"
    if cache_path.exists():
        return Response(content=cache_path.read_bytes(), media_type="image/png")

    graph = _get_graph_by_name(name)
    try:
        png_bytes = graph.get_graph().draw_mermaid_png()
        with open(cache_path, "wb") as f:
            f.write(png_bytes)
        return Response(content=png_bytes, media_type="image/png")
    except Exception as e:
        logger.warning(f"Could not render PNG via draw_mermaid_png (requires pyppeteer/graphviz): {e}")
        # Return mermaid code as svg/text fallback if png rendering engine not installed locally
        mermaid_code = graph.get_graph().draw_mermaid()
        return PlainTextResponse(
            content=f"Mermaid diagram for {name}:\n\n{mermaid_code}",
            status_code=status.HTTP_200_OK
        )
