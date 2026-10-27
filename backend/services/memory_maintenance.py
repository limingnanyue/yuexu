"""记忆库维护任务：热度衰减、自动去重、冷记忆淘汰、向量 GC、索引重建。

维护原则：
- 全量任务按 (created_at, id) 游标分批遍历，不一次性载入全表；
- O(n²) 相似度计算放入工作线程，批间让出事件循环，不阻塞在线对话；
- 索引重建「先 upsert 后清理孤儿」，无清空空窗，中途失败不丢索引。
"""

from __future__ import annotations

import asyncio
import re
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from backend.common.logger import get_logger
from backend.common.utils import chunked
from backend.repositories.memory_repo import MemoryRepo
from backend.repositories.vector_store import VectorStore
from backend.services.memory_support import metadata_from_entry, similarity

logger = get_logger("yuexu.memory.maintenance")

_DATE_PREFIX = re.compile(r"^记录日期 (\d{4}-\d{2}-\d{2})[：:]")


async def decay_hot(repo: MemoryRepo, factor: float) -> int:
    count = await repo.decay_hot(factor)
    logger.info("记忆热度衰减完成：%s 条（factor=%s）", count, factor)
    return count


def _record_date(content: str, category: str) -> str | None:
    matched = _DATE_PREFIX.match(content or "")
    return matched.group(1) if matched and category in {"emotion", "experience"} else None


def _compute_duplicates(
    groups: dict[tuple, list[tuple[str, str, str, bool]]]
) -> list[str]:
    """纯函数（线程内执行）：组内两两相似度查重，返回待删除 id。"""
    duplicate_ids: list[str] = []
    for group in groups.values():
        kept: list[tuple[str, str]] = []
        for entry_id, content, _category, rejected in group:
            if rejected:
                continue
            # threshold 只做剪枝：Jaccard 已达标或长度上界不足时跳过昂贵的
            # SequenceMatcher，判定结果与不传 threshold 完全一致（已由
            # memory_algorithm_upgrade_test 的剪枝一致性用例覆盖）。
            if any(
                similarity(content, other, threshold=0.92) >= 0.92
                for _other_id, other in kept
            ):
                duplicate_ids.append(entry_id)
            else:
                kept.append((entry_id, content))
    return duplicate_ids


async def dedupe(repo: MemoryRepo, vector: VectorStore, batch: int = 500) -> int:
    """全量按组去重：游标分批遍历所有记忆，相似计算放入线程。"""
    batch = max(50, int(batch))
    groups: dict[tuple, list[tuple[str, str, str, bool]]] = defaultdict(list)
    total = 0
    async for rows in repo.iter_entries(batch):
        for entry in rows:
            groups[
                (
                    entry.bot_id,
                    entry.target_type,
                    entry.target_id,
                    entry.user_id,
                    entry.group_id,
                    _record_date(entry.content, entry.category),
                )
            ].append((entry.id, entry.content or "", entry.category, bool(entry.rejected)))
        total += len(rows)
        await asyncio.sleep(0)
    if not total:
        return 0
    duplicate_ids = await asyncio.to_thread(_compute_duplicates, groups)
    if not duplicate_ids:
        return 0
    for ids in chunked(duplicate_ids, 500):
        try:
            await vector.delete(list(ids))
        except Exception:  # noqa: BLE001
            logger.warning("去重时向量删除失败", exc_info=True)
    count = await repo.delete_ids(duplicate_ids)
    logger.info("记忆自动去重：扫描 %s 条，删除 %s 条", total, count)
    return count


async def purge_cold(
    repo: MemoryRepo,
    vector: VectorStore,
    *,
    enabled: bool,
    days: int,
    hot_below: float,
    batch: int = 500,
    force: bool = False,
) -> int:
    if not force and not enabled:
        return 0
    ids = await repo.purge_cold(
        before=datetime.now() - timedelta(days=max(1, days)),
        hot_below=hot_below,
        limit=batch,
    )
    if not ids:
        return 0
    try:
        await vector.delete(ids)
    except Exception:  # noqa: BLE001
        logger.warning("冷记忆淘汰时向量删除失败", exc_info=True)
    count = await repo.delete_ids(ids)
    logger.info("冷记忆淘汰：%s 条（>%s 天且热度<%s）", count, days, hot_below)
    return count


async def gc_vectors(repo: MemoryRepo, vector: VectorStore) -> int:
    try:
        ids = await vector.list_ids()
    except Exception:  # noqa: BLE001
        logger.debug("向量 GC 跳过（后端不支持 list_ids）", exc_info=True)
        return 0
    orphans: list[str] = []
    for chunk in chunked(ids, 500):
        existing = await repo.get_many(list(chunk))
        existing_ids = {entry.id for entry in existing}
        orphans.extend(item for item in chunk if item not in existing_ids)
    if orphans:
        await vector.delete(orphans)
        logger.info("向量库 GC：清理孤儿向量 %s 条", len(orphans))
    return len(orphans)


async def rebuild_index(
    repo: MemoryRepo, vector: VectorStore, *, bot_id: str | None = None, batch: int = 100
) -> int:
    """全量重建向量索引：先分批 upsert，再删除孤儿向量，全程不清空索引。

    完成后更新集合的 embedding 签名，结束「待重建」状态。
    """
    if vector.name == "keyword":
        return 0
    total = 0
    db_ids: list[str] = []
    async for rows in repo.iter_entries(batch, bot_id=bot_id):
        await vector.add(
            [entry.id for entry in rows],
            [entry.content for entry in rows],
            [metadata_from_entry(entry) for entry in rows],
        )
        db_ids.extend(entry.id for entry in rows)
        total += len(rows)
        await asyncio.sleep(0)
    # 清理数据库已删除但向量库残留的孤儿（bot 范围内比对）
    try:
        indexed_ids = await vector.list_ids(
            {"bot_id": bot_id} if bot_id else None
        )
        db_id_set = set(db_ids)  # 提到循环外：写在推导式里是 O(n²)，大库重建会卡死事件循环
        orphans = [item for item in indexed_ids if item not in db_id_set]
        for chunk in chunked(orphans, 500):
            await vector.delete(list(chunk))
    except Exception:  # noqa: BLE001
        logger.warning("重建后清理孤儿向量失败", exc_info=True)
    mark = getattr(vector, "mark_reindexed", None)
    if mark is not None:
        try:
            await mark()
        except Exception:  # noqa: BLE001
            logger.warning("更新向量库 embedding 签名失败", exc_info=True)
    logger.info("记忆向量重建完成：%s 条", total)
    return total


def maintenance_summary(counts: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in counts.items() if value is not None}


__all__ = [
    "decay_hot",
    "dedupe",
    "gc_vectors",
    "purge_cold",
    "rebuild_index",
    "maintenance_summary",
]
