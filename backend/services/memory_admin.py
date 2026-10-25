"""记忆库后台管理：导出与统计（与召回 / 写入链路解耦）。"""

from __future__ import annotations

from typing import Any, Callable

from backend.database.models import MemoryEntry
from backend.repositories.memory_repo import MemoryRepo


async def export_entries(
    repo: MemoryRepo,
    bot_id: str,
    user_id: str | None,
    tier_fn: Callable[[MemoryEntry], str],
    *,
    scope_type: str | None = None,
    group_id: str | None = None,
    keyword: str | None = None,
    memory_type: str | None = None,
    rejected: bool | None = None,
) -> list[dict[str, Any]]:
    entries, _ = await repo.list_for_user(
        bot_id, user_id, scope_type=scope_type, group_id=group_id,
        keyword=keyword, memory_type=memory_type, rejected=rejected, limit=None,
    )
    return [
        {
            "id": entry.id,
            "bot_id": entry.bot_id,
            "target_type": entry.target_type,
            "target_id": entry.target_id,
            "scope_type": entry.scope_type,
            "group_id": entry.group_id,
            "user_id": entry.user_id,
            "content": entry.content,
            "category": entry.category,
            "memory_type": entry.memory_type,
            "confidence": entry.confidence,
            "fuzzy_weight": entry.fuzzy_weight,
            "hot_score": entry.hot_score,
            "tag_keywords": entry.tag_keywords or [],
            "rejected": entry.rejected,
            "tier": tier_fn(entry),
            "created_at": entry.created_at.isoformat(timespec="seconds"),
            "last_hit_at": entry.last_hit_at.isoformat(timespec="seconds")
            if entry.last_hit_at else None,
        }
        for entry in entries
    ]


async def memory_stats(
    repo: MemoryRepo,
    *,
    bot_id: str | None,
    tier_fn: Callable[[MemoryEntry], str],
    backend: str,
    fuzzy_enabled: bool,
    precise_threshold: float,
    fuzzy_threshold: float,
) -> dict[str, Any]:
    entries = await repo.all(bot_id=bot_id) if bot_id else await repo.all()
    tiers = {"hot": 0, "warm": 0, "cold": 0}
    by_type: dict[str, int] = {}
    by_category: dict[str, int] = {}
    rejected = 0
    for entry in entries:
        tier = tier_fn(entry)
        tiers[tier] = tiers.get(tier, 0) + 1
        by_type[entry.memory_type] = by_type.get(entry.memory_type, 0) + 1
        by_category[entry.category] = by_category.get(entry.category, 0) + 1
        if entry.rejected:
            rejected += 1
    return {
        "total": len(entries),
        "rejected": rejected,
        "tiers": tiers,
        "by_type": by_type,
        "by_category": by_category,
        "backend": backend,
        "fuzzy_enabled": fuzzy_enabled,
        "thresholds": {
            "precise": precise_threshold,
            "fuzzy": fuzzy_threshold,
        },
    }
