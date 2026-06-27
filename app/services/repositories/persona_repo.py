"""Persona repository — CRUD for UserPersona."""

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.models.domain import UserPersona


class PersonaRepo:
    async def get_active_personas(
        self,
        session: AsyncSession,
        board_id: int | None = None,
        include_global: bool = True,
    ) -> list:
        statement = select(UserPersona).where(UserPersona.is_active.is_(True))
        if board_id is not None:
            if include_global:
                statement = statement.where((UserPersona.board_id == board_id) | (UserPersona.board_id.is_(None)))
            else:
                statement = statement.where(UserPersona.board_id == board_id)
        result = await session.execute(statement)
        return result.scalars().all()

    async def save_persona(
        self,
        session: AsyncSession,
        content: str,
        category: str = "instruction",
        board_id: int | None = None,
    ) -> None:
        db_persona = UserPersona(content=content, category=category, board_id=board_id)
        session.add(db_persona)
        await session.commit()

    async def delete_persona(self, session: AsyncSession, persona_id: int) -> None:
        statement = select(UserPersona).where(UserPersona.id == persona_id)
        result = await session.execute(statement)
        db_persona = result.scalars().first()
        if db_persona:
            await session.delete(db_persona)
            await session.commit()

    async def get_personas_by_category(
        self,
        session: AsyncSession,
        category: str,
        board_id: int | None = None,
        include_global: bool = True,
    ) -> list:
        statement = select(UserPersona).where(
            UserPersona.is_active.is_(True),
            UserPersona.category == category,
        )
        if board_id is not None:
            if include_global:
                statement = statement.where((UserPersona.board_id == board_id) | (UserPersona.board_id.is_(None)))
            else:
                statement = statement.where(UserPersona.board_id == board_id)
        result = await session.execute(statement)
        return result.scalars().all()

    async def get_explicit_preferences(
        self,
        session: AsyncSession,
        board_id: int | None = None,
        include_global: bool = True,
    ) -> dict[str, list[str]]:
        categories = ["focus_topic", "block_topic", "prefer_source", "avoid_source"]
        statement = select(UserPersona).where(
            UserPersona.is_active.is_(True),
            UserPersona.category.in_(categories),
        )
        if board_id is not None:
            if include_global:
                statement = statement.where((UserPersona.board_id == board_id) | (UserPersona.board_id.is_(None)))
            else:
                statement = statement.where(UserPersona.board_id == board_id)
        result = await session.execute(statement)
        personas = result.scalars().all()
        grouped: dict[str, list[str]] = {cat: [] for cat in categories}
        for p in personas:
            grouped[p.category].append(p.content)
        return grouped

    async def get_explicit_preferences_detailed(
        self,
        session: AsyncSession,
        board_id: int | None = None,
        include_global: bool = True,
    ) -> dict[str, list[dict]]:
        """Like get_explicit_preferences but returns full details (id, content, board_id)."""
        categories = ["focus_topic", "block_topic", "prefer_source", "avoid_source"]
        statement = select(UserPersona).where(
            UserPersona.is_active.is_(True),
            UserPersona.category.in_(categories),
        )
        if board_id is not None:
            if include_global:
                statement = statement.where((UserPersona.board_id == board_id) | (UserPersona.board_id.is_(None)))
            else:
                statement = statement.where(UserPersona.board_id == board_id)
        result = await session.execute(statement)
        personas = result.scalars().all()
        grouped: dict[str, list[dict]] = {cat: [] for cat in categories}
        for p in personas:
            grouped[p.category].append({"id": p.id, "content": p.content, "board_id": p.board_id})
        return grouped
