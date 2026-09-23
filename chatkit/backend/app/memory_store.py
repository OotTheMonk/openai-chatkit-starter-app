"""
Simple in-memory store compatible with the ChatKit Store interface.
A production app would implement this using a persistant database.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timezone

from chatkit.store import NotFoundError, Store
from chatkit.types import Attachment, Page, ThreadItem, ThreadMetadata

logger = logging.getLogger(__name__)


class MemoryStore(Store[dict]):
    def __init__(self, storage_path=None):
        self.threads: dict[str, ThreadMetadata] = {}
        self.items: dict[str, list[ThreadItem]] = defaultdict(list)
        from pathlib import Path
        from pydantic import TypeAdapter
        import json
        self.path=Path(storage_path) if storage_path else None
        if self.path and self.path.exists():
            data=json.loads(self.path.read_text(encoding="utf-8"))
            self.threads={k:ThreadMetadata.model_validate(v) for k,v in data["threads"].items()}
            adapter=TypeAdapter(list[ThreadItem])
            self.items.update({k:adapter.validate_python(v) for k,v in data["items"].items()})

    def persist(self):
        if not self.path:return
        import json
        self.path.parent.mkdir(parents=True,exist_ok=True)
        temp=self.path.with_suffix(".tmp")
        temp.write_text(json.dumps({"threads":{k:v.model_dump(mode="json") for k,v in self.threads.items()},"items":{k:[i.model_dump(mode="json") for i in v] for k,v in self.items.items()}}),encoding="utf-8")
        temp.replace(self.path)

    async def load_thread(self, thread_id: str, context: dict) -> ThreadMetadata:
        if thread_id not in self.threads:
            # Auto-create thread if it doesn't exist (common in ChatKit)
            logger.info(f"🆕 Auto-creating thread {thread_id}")
            thread = ThreadMetadata(
                id=thread_id,
                created_at=datetime.now(),
                metadata={}
            )
            self.threads[thread_id] = thread
            return thread
        return self.threads[thread_id]

    async def save_thread(self, thread: ThreadMetadata, context: dict) -> None:
        self.threads[thread.id] = thread
        self.persist()

    async def load_threads(
        self, limit: int, after: str | None, order: str, context: dict
    ) -> Page[ThreadMetadata]:
        threads = list(self.threads.values())
        return self._paginate(
            threads,
            after,
            limit,
            order,
            sort_key=lambda t: t.created_at.replace(tzinfo=timezone.utc) if t.created_at.tzinfo is None else t.created_at,
            cursor_key=lambda t: t.id,
        )

    async def load_thread_items(
        self, thread_id: str, after: str | None, limit: int, order: str, context: dict
    ) -> Page[ThreadItem]:
        items = self.items.get(thread_id, [])
        return self._paginate(
            items,
            after,
            limit,
            order,
            sort_key=lambda i: i.created_at.replace(tzinfo=timezone.utc) if i.created_at.tzinfo is None else i.created_at,
            cursor_key=lambda i: i.id,
        )

    async def add_thread_item(
        self, thread_id: str, item: ThreadItem, context: dict
    ) -> None:
        # Streaming can re-add payloads under a reused placeholder id; collapse on id.
        dupe=next((i for i,e in enumerate(self.items[thread_id]) if e.id==item.id),None)
        if dupe is None:self.items[thread_id].append(item)
        else:self.items[thread_id][dupe]=item
        self.persist()

    async def save_item(self, thread_id: str, item: ThreadItem, context: dict) -> None:
        items = self.items[thread_id]
        for idx, existing in enumerate(items):
            if existing.id == item.id:
                items[idx] = item
                self.persist()
                return
        items.append(item)
        self.persist()

    async def load_item(
        self, thread_id: str, item_id: str, context: dict
    ) -> ThreadItem:
        for item in self.items.get(thread_id, []):
            if item.id == item_id:
                return item
        raise NotFoundError(f"Item {item_id} not found in thread {thread_id}")

    async def delete_thread(self, thread_id: str, context: dict) -> None:
        self.threads.pop(thread_id, None)
        self.items.pop(thread_id, None)
        self.persist()

    async def delete_thread_item(
        self, thread_id: str, item_id: str, context: dict
    ) -> None:
        self.items[thread_id] = [
            item for item in self.items.get(thread_id, []) if item.id != item_id
        ]
        self.persist()

    def _paginate(
        self,
        rows: list,
        after: str | None,
        limit: int,
        order: str,
        sort_key,
        cursor_key,
    ):
        sorted_rows = sorted(rows, key=sort_key, reverse=order == "desc")
        start = 0
        if after:
            for idx, row in enumerate(sorted_rows):
                if cursor_key(row) == after:
                    start = idx + 1
                    break
        data = sorted_rows[start : start + limit]
        has_more = start + limit < len(sorted_rows)
        next_after = cursor_key(data[-1]) if has_more and data else None
        return Page(data=data, has_more=has_more, after=next_after)

    # Attachments are not implemented in the quickstart store

    async def save_attachment(self, attachment: Attachment, context: dict) -> None:
        raise NotImplementedError()

    async def load_attachment(self, attachment_id: str, context: dict) -> Attachment:
        raise NotImplementedError()

    async def delete_attachment(self, attachment_id: str, context: dict) -> None:
        raise NotImplementedError()
