import os
import uuid
import yaml
import logging
from pathlib import Path
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from src.storage.models import Pattern
from src.storage.vector_store import vector_store

logger = logging.getLogger("pattern_seed")
SEED_FILE_PATH = Path("seeds/patterns.yaml")


def get_deterministic_pattern_id(name: str) -> str:
    # Stable deterministic UUID for canonical seed patterns
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, f"pattern_seed_{name.strip().lower()}"))


async def seed_patterns_if_needed(db: AsyncSession) -> int:
    if not SEED_FILE_PATH.exists():
        logger.warning(f"Seed file {SEED_FILE_PATH} not found.")
        return 0

    with open(SEED_FILE_PATH, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    patterns_list = data.get("patterns", [])
    seeded_count = 0

    for p_data in patterns_list:
        name = p_data.get("name", "").strip()
        if not name:
            continue

        pattern_id = get_deterministic_pattern_id(name)

        # Check if already exists in SQLite (preserve user edits if exists)
        res = await db.execute(select(Pattern).where(Pattern.name == name))
        existing = res.scalar_one_or_none()

        if existing:
            # Pattern exists; ensure ChromaDB is synced with existing DB record
            vector_store.upsert_pattern(
                pattern_id=existing.id,
                name=existing.name,
                intent=existing.intent,
                structure=existing.structure,
                when_to_use=existing.when_to_use,
                when_not_to_use=existing.when_not_to_use,
                tags=existing.tags or []
            )
            continue

        # Insert new seed pattern with stable deterministic ID
        new_pattern = Pattern(
            id=pattern_id,
            name=name,
            intent=p_data.get("intent", ""),
            structure=p_data.get("structure", ""),
            when_to_use=p_data.get("when_to_use", ""),
            when_not_to_use=p_data.get("when_not_to_use", ""),
            prerequisites=p_data.get("prerequisites", []),
            references=p_data.get("references", []),
            tags=p_data.get("tags", [])
        )
        db.add(new_pattern)
        
        # Upsert embedding into ChromaDB
        vector_store.upsert_pattern(
            pattern_id=pattern_id,
            name=name,
            intent=new_pattern.intent,
            structure=new_pattern.structure,
            when_to_use=new_pattern.when_to_use,
            when_not_to_use=new_pattern.when_not_to_use,
            tags=new_pattern.tags or []
        )
        seeded_count += 1

    if seeded_count > 0:
        await db.commit()
        logger.info(f"Seeded {seeded_count} new canonical patterns into Pattern KB.")

    return seeded_count
