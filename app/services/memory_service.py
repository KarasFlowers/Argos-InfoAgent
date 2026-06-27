"""
Memory Service: Persistent factual memory for prompt enrichment.

Manages UserMemory entries — structured key-value facts about the user
(e.g. preferred language, recent research topics, professional context)
that are injected into RAG and LLM prompts for personalized responses.

Distinct from UserPersona (interest filtering) and UserFeedback (semantic
preference centroids): UserMemory is for explicit factual recall.
"""

import json
import logging
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.core.db import AsyncSessionLocal
from app.models.domain import ChatMessage, UserMemory

logger = logging.getLogger(__name__)


async def save_memory(
    key: str,
    value: str,
    category: str = "fact",
    source: str = "auto",
) -> UserMemory:
    """Upsert a memory entry by key. Returns the saved UserMemory."""
    async with AsyncSessionLocal() as session:
        stmt = select(UserMemory).where(UserMemory.key == key)
        result = await session.execute(stmt)
        existing = result.scalars().first()

        if existing:
            existing.value = value
            existing.category = category
            existing.source = source
            existing.updated_at = datetime.now(UTC)
            if not existing.is_active:
                existing.is_active = True
        else:
            existing = UserMemory(
                key=key,
                value=value,
                category=category,
                source=source,
            )
            session.add(existing)

        await session.commit()
        await session.refresh(existing)
        return existing


async def get_memory(key: str) -> str | None:
    """Get the value of a memory entry by key, or None if not found."""
    async with AsyncSessionLocal() as session:
        stmt = select(UserMemory).where(
            UserMemory.key == key,
            UserMemory.is_active.is_(True),
        )
        result = await session.execute(stmt)
        entry = result.scalars().first()
        return entry.value if entry else None


async def get_memories_by_category(category: str) -> list[UserMemory]:
    """Get all active memory entries for a given category."""
    async with AsyncSessionLocal() as session:
        stmt = (
            select(UserMemory)
            .where(UserMemory.category == category, UserMemory.is_active.is_(True))
            .order_by(UserMemory.updated_at.desc())
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())


async def get_all_active_memories() -> list[UserMemory]:
    """Get all active memory entries."""
    async with AsyncSessionLocal() as session:
        stmt = select(UserMemory).where(UserMemory.is_active.is_(True)).order_by(UserMemory.category, UserMemory.key)
        result = await session.execute(stmt)
        return list(result.scalars().all())


async def build_memory_context() -> str:
    """Build a concise string of all active memories for prompt injection.

    Returns something like:
    "用户偏好中文回答；最近关注 RAG 技术；职业是 CS 学生"
    Returns empty string if no memories.
    """
    memories = await get_all_active_memories()
    if not memories:
        return ""

    parts = []
    for m in memories:
        parts.append(f"{m.key}: {m.value}")

    return "；".join(parts)


async def delete_memory(key: str) -> bool:
    """Soft-delete a memory entry (set is_active=False). Returns True if found."""
    async with AsyncSessionLocal() as session:
        stmt = select(UserMemory).where(UserMemory.key == key)
        result = await session.execute(stmt)
        entry = result.scalars().first()
        if not entry:
            return False
        entry.is_active = False
        entry.updated_at = datetime.now(UTC)
        await session.commit()
        return True


async def auto_extract_memories(session: AsyncSession) -> int:
    """
    Automatically extract key facts from recent chat messages using LLM.

    Looks at chat messages from the last 24 hours that haven't been processed
    yet, asks the LLM to extract factual preferences/interests, and saves
    them as UserMemory entries with source='chat_extract'.

    Returns the number of new memories saved.
    """
    from app.services.llm_service import llm_service

    # Get recent chat messages (last 24h)
    cutoff = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    stmt = select(ChatMessage).where(ChatMessage.timestamp >= cutoff).order_by(ChatMessage.timestamp).limit(50)
    result = await session.execute(stmt)
    messages = result.scalars().all()

    if len(messages) < 2:
        return 0

    # Build conversation text for the LLM
    conversation = []
    for m in messages[-30:]:  # cap at last 30 messages
        role = "用户" if m.role == "user" else "助手"
        conversation.append(f"{role}: {m.content[:200]}")

    conv_text = "\n".join(conversation)

    # Get existing memory keys to avoid duplicates
    existing_stmt = select(UserMemory.key).where(UserMemory.is_active.is_(True))
    existing_result = await session.execute(existing_stmt)
    existing_keys = {row[0] for row in existing_result.all()}

    prompt = f"""分析以下对话记录，提取关于用户的事实性信息（偏好、职业、兴趣方向、常用语言等）。
以 JSON 数组格式返回，每项包含 key（英文蛇形命名）和 value（简短中文描述）。
只提取明确的事实，不要推测。最多提取5条。

对话记录：
{conv_text}

返回格式示例：
[{{"key": "preferred_language", "value": "中文"}}]"""

    try:
        response = await llm_service.llm.chat(
            messages=[{"role": "user", "content": prompt}],
            max_tokens=500,
            temperature=0.1,
            response_format={"type": "json_object"},
        )

        content = response.choices[0].message.content or ""
        # Parse JSON — handle both {"memories": [...]} and [...] formats
        try:
            parsed = json.loads(content)
            if isinstance(parsed, dict):
                items = parsed.get("memories", parsed.get("items", []))
            elif isinstance(parsed, list):
                items = parsed
            else:
                items = []
        except json.JSONDecodeError:
            logger.warning("Failed to parse memory extraction JSON: %s", content[:100])
            return 0

        new_count = 0
        for item in items[:5]:
            if not isinstance(item, dict):
                continue
            key = item.get("key", "").strip()
            value = item.get("value", "").strip()
            if not key or not value:
                continue
            # Skip if already known
            if key in existing_keys:
                continue

            memory = UserMemory(
                key=key,
                value=value,
                category="preference" if "偏好" in value or "喜欢" in value else "fact",
                source="chat_extract",
            )
            session.add(memory)
            existing_keys.add(key)
            new_count += 1

        if new_count > 0:
            await session.commit()
            logger.info("Auto-extracted %d new memories from chat", new_count)

        return new_count

    except Exception:
        logger.warning("Memory auto-extraction failed", exc_info=True)
        return 0
