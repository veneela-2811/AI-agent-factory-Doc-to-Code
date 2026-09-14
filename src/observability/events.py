import asyncio
import json
import logging
from typing import Dict, Any, Optional, AsyncGenerator, List, Set
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from src.storage.models import RunEvent

logger = logging.getLogger("events_hub")


class EventHub:
    def __init__(self):
        # (project_id, run_id) -> set of asyncio.Queue
        self._subscribers: Dict[str, Set[asyncio.Queue]] = {}
        self._lock = asyncio.Lock()

    def _key(self, project_id: str, run_id: str) -> str:
        return f"{project_id}:{run_id}"

    async def publish(
        self,
        project_id: str,
        run_id: str,
        event_type: str,
        data: Dict[str, Any],
        db: Optional[AsyncSession] = None
    ) -> int:
        event_id = 0
        if db:
            event_rec = RunEvent(
                project_id=project_id,
                run_id=run_id,
                event_type=event_type,
                data=data
            )
            db.add(event_rec)
            try:
                await db.commit()
                await db.refresh(event_rec)
                event_id = event_rec.id
            except Exception as e:
                logger.error(f"Failed persisting event: {e}")

        payload = {
            "id": event_id,
            "event": event_type,
            "data": data,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

        key = self._key(project_id, run_id)
        async with self._lock:
            queues = list(self._subscribers.get(key, set()))

        for q in queues:
            try:
                q.put_nowait(payload)
            except Exception:
                pass

        return event_id

    async def subscribe(
        self,
        project_id: str,
        run_id: str,
        last_event_id: Optional[int] = None,
        db: Optional[AsyncSession] = None
    ) -> AsyncGenerator[Dict[str, Any], None]:
        # 1. Yield historical events if last_event_id is given or db provided
        if db and last_event_id is not None:
            res = await db.execute(
                select(RunEvent)
                .where(RunEvent.project_id == project_id, RunEvent.run_id == run_id, RunEvent.id > last_event_id)
                .order_by(RunEvent.id.asc())
            )
            historical = res.scalars().all()
            for h in historical:
                yield {
                    "id": h.id,
                    "event": h.event_type,
                    "data": h.data,
                    "timestamp": h.created_at.isoformat()
                }

        # 2. Subscribe for live events
        queue = asyncio.Queue()
        key = self._key(project_id, run_id)
        async with self._lock:
            if key not in self._subscribers:
                self._subscribers[key] = set()
            self._subscribers[key].add(queue)

        try:
            while True:
                msg = await queue.get()
                yield msg
        finally:
            async with self._lock:
                if key in self._subscribers:
                    self._subscribers[key].discard(queue)
                    if not self._subscribers[key]:
                        del self._subscribers[key]


event_hub = EventHub()
