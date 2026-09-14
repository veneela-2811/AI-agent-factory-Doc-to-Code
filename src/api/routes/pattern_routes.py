import uuid
import yaml
import json
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from src.storage.database import get_db
from src.storage.models import Pattern
from src.storage.vector_store import vector_store
from src.auth.dependencies import get_current_user
from src.api.schemas import (
    PatternCreate, PatternUpdate, PatternResponse,
    PatternListResponse, PatternSearchRequest, PatternSearchResponse, PatternSearchResultItem
)

router = APIRouter(prefix="/patterns", tags=["Pattern Knowledge Base"])


@router.post("", response_model=PatternResponse, status_code=status.HTTP_201_CREATED, summary="Create an agentic design pattern")
async def create_pattern(
    req: PatternCreate,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    res = await db.execute(select(Pattern).where(Pattern.name == req.name.strip()))
    if res.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": {"code": "PATTERN_EXISTS", "message": f"Pattern with name '{req.name}' already exists", "details": None}}
        )

    pattern_id = str(uuid.uuid4())
    pattern = Pattern(
        id=pattern_id,
        name=req.name.strip(),
        intent=req.intent.strip(),
        structure=req.structure.strip(),
        when_to_use=req.when_to_use.strip(),
        when_not_to_use=req.when_not_to_use.strip(),
        prerequisites=req.prerequisites,
        references=req.references,
        tags=req.tags
    )
    db.add(pattern)
    await db.commit()
    await db.refresh(pattern)

    vector_store.upsert_pattern(
        pattern_id=pattern_id,
        name=pattern.name,
        intent=pattern.intent,
        structure=pattern.structure,
        when_to_use=pattern.when_to_use,
        when_not_to_use=pattern.when_not_to_use,
        tags=pattern.tags
    )

    return PatternResponse.model_validate(pattern)


@router.post("/bulk", response_model=PatternListResponse, status_code=status.HTTP_201_CREATED, summary="Bulk upload patterns via JSON array or YAML/JSON file")
async def bulk_upload_patterns(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    content_type = request.headers.get("content-type", "")
    raw_patterns = []

    if "multipart/form-data" in content_type:
        form = await request.form()
        file = form.get("file")
        if file and hasattr(file, "read"):
            content = await file.read()
            filename = getattr(file, "filename", "").lower()
            if filename.endswith(".yaml") or filename.endswith(".yml"):
                parsed = yaml.safe_load(content) or {}
            else:
                parsed = json.loads(content.decode("utf-8"))
            
            if isinstance(parsed, dict):
                raw_patterns = parsed.get("patterns", [])
            elif isinstance(parsed, list):
                raw_patterns = parsed
    else:
        try:
            body_bytes = await request.body()
            if body_bytes:
                text_content = body_bytes.decode("utf-8")
                try:
                    parsed = json.loads(text_content)
                except Exception:
                    parsed = yaml.safe_load(text_content)
                
                if isinstance(parsed, dict):
                    raw_patterns = parsed.get("patterns", [])
                elif isinstance(parsed, list):
                    raw_patterns = parsed
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"error": {"code": "INVALID_BODY", "message": f"Failed parsing request body: {str(e)}", "details": None}}
            )

    if not raw_patterns or not isinstance(raw_patterns, list):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": {"code": "EMPTY_PAYLOAD", "message": "No valid list of patterns found in bulk payload", "details": None}}
        )

    created_patterns = []
    for item in raw_patterns:
        if not isinstance(item, dict):
            continue
        name = item.get("name", "").strip()
        if not name:
            continue

        res = await db.execute(select(Pattern).where(Pattern.name == name))
        existing = res.scalar_one_or_none()

        if existing:
            existing.intent = item.get("intent", existing.intent)
            existing.structure = item.get("structure", existing.structure)
            existing.when_to_use = item.get("when_to_use", existing.when_to_use)
            existing.when_not_to_use = item.get("when_not_to_use", existing.when_not_to_use)
            existing.prerequisites = item.get("prerequisites", existing.prerequisites)
            existing.references = item.get("references", existing.references)
            existing.tags = item.get("tags", existing.tags)
            
            vector_store.upsert_pattern(
                pattern_id=existing.id,
                name=existing.name,
                intent=existing.intent,
                structure=existing.structure,
                when_to_use=existing.when_to_use,
                when_not_to_use=existing.when_not_to_use,
                tags=existing.tags
            )
            created_patterns.append(existing)
        else:
            p_id = str(uuid.uuid4())
            new_p = Pattern(
                id=p_id,
                name=name,
                intent=item.get("intent", ""),
                structure=item.get("structure", ""),
                when_to_use=item.get("when_to_use", ""),
                when_not_to_use=item.get("when_not_to_use", ""),
                prerequisites=item.get("prerequisites", []),
                references=item.get("references", []),
                tags=item.get("tags", [])
            )
            db.add(new_p)
            vector_store.upsert_pattern(
                pattern_id=p_id,
                name=name,
                intent=new_p.intent,
                structure=new_p.structure,
                when_to_use=new_p.when_to_use,
                when_not_to_use=new_p.when_not_to_use,
                tags=new_p.tags
            )
            created_patterns.append(new_p)

    await db.commit()
    for p in created_patterns:
        await db.refresh(p)

    return PatternListResponse(
        patterns=[PatternResponse.model_validate(p) for p in created_patterns],
        total=len(created_patterns)
    )


@router.get("", response_model=PatternListResponse, summary="List all patterns")
async def list_patterns(
    tag: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    res = await db.execute(select(Pattern).order_by(Pattern.name.asc()))
    all_patterns = res.scalars().all()

    if tag:
        tag_lower = tag.strip().lower()
        filtered = [
            p for p in all_patterns
            if any(tag_lower == t.lower() for t in (p.tags or []))
        ]
    else:
        filtered = list(all_patterns)

    return PatternListResponse(
        patterns=[PatternResponse.model_validate(p) for p in filtered],
        total=len(filtered)
    )


@router.get("/{pattern_id}", response_model=PatternResponse, summary="Get pattern by ID or Name")
async def get_pattern(
    pattern_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    res = await db.execute(
        select(Pattern).where((Pattern.id == pattern_id) | (Pattern.name == pattern_id))
    )
    pattern = res.scalar_one_or_none()
    if not pattern:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": {"code": "NOT_FOUND", "message": f"Pattern '{pattern_id}' not found", "details": None}}
        )
    return PatternResponse.model_validate(pattern)


@router.patch("/{pattern_id}", response_model=PatternResponse, summary="Update pattern")
async def update_pattern(
    pattern_id: str,
    req: PatternUpdate,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    res = await db.execute(
        select(Pattern).where((Pattern.id == pattern_id) | (Pattern.name == pattern_id))
    )
    pattern = res.scalar_one_or_none()
    if not pattern:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": {"code": "NOT_FOUND", "message": f"Pattern '{pattern_id}' not found", "details": None}}
        )

    if req.name is not None:
        pattern.name = req.name
    if req.intent is not None:
        pattern.intent = req.intent
    if req.structure is not None:
        pattern.structure = req.structure
    if req.when_to_use is not None:
        pattern.when_to_use = req.when_to_use
    if req.when_not_to_use is not None:
        pattern.when_not_to_use = req.when_not_to_use
    if req.prerequisites is not None:
        pattern.prerequisites = req.prerequisites
    if req.references is not None:
        pattern.references = req.references
    if req.tags is not None:
        pattern.tags = req.tags

    await db.commit()
    await db.refresh(pattern)

    vector_store.upsert_pattern(
        pattern_id=pattern.id,
        name=pattern.name,
        intent=pattern.intent,
        structure=pattern.structure,
        when_to_use=pattern.when_to_use,
        when_not_to_use=pattern.when_not_to_use,
        tags=pattern.tags
    )

    return PatternResponse.model_validate(pattern)


@router.delete("/{pattern_id}", status_code=status.HTTP_200_OK, summary="Delete pattern")
async def delete_pattern(
    pattern_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    res = await db.execute(
        select(Pattern).where((Pattern.id == pattern_id) | (Pattern.name == pattern_id))
    )
    pattern = res.scalar_one_or_none()
    if not pattern:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": {"code": "NOT_FOUND", "message": f"Pattern '{pattern_id}' not found", "details": None}}
        )

    p_id = pattern.id
    p_name = pattern.name
    await db.delete(pattern)
    await db.commit()

    vector_store.delete_pattern(p_id)
    return {"message": f"Pattern '{p_name}' successfully deleted", "id": p_id}


@router.post("/search", response_model=PatternSearchResponse, summary="Semantic search over Pattern Knowledge Base")
async def search_patterns(
    req: PatternSearchRequest,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    chroma_matches = vector_store.query_patterns(
        query=req.query,
        top_k=req.top_k,
        tags=req.tags
    )

    result_items = []
    seen_ids = set()

    for match in chroma_matches:
        p_id = match.get("id")
        p_name = match.get("name")
        
        res = await db.execute(
            select(Pattern).where((Pattern.id == p_id) | (Pattern.name == p_name))
        )
        pattern_row = res.scalar_one_or_none()

        if pattern_row and pattern_row.id not in seen_ids:
            seen_ids.add(pattern_row.id)
            result_items.append(PatternSearchResultItem(
                id=pattern_row.id,
                name=pattern_row.name,
                similarity_score=match.get("similarity_score", 0.0),
                matched_fields=["intent", "when_to_use", "structure", "tags"],
                pattern=PatternResponse.model_validate(pattern_row)
            ))

    return PatternSearchResponse(
        query=req.query,
        total_matched=len(result_items),
        results=result_items
    )
