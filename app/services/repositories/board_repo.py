"""Board repository — CRUD for Board."""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.models.domain import Board


class BoardRepo:
    async def list_boards(self, session: AsyncSession, active_only: bool = True) -> list[Board]:
        stmt = select(Board)
        if active_only:
            stmt = stmt.where(Board.is_active == True)
        stmt = stmt.order_by(Board.display_order, Board.id)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def get_board_by_slug(self, session: AsyncSession, slug: str) -> Board | None:
        stmt = select(Board).where(Board.slug == slug)
        result = await session.execute(stmt)
        return result.scalars().first()

    async def get_board_by_id(self, session: AsyncSession, board_id: int) -> Board | None:
        stmt = select(Board).where(Board.id == board_id)
        result = await session.execute(stmt)
        return result.scalars().first()

    async def get_default_board(self, session: AsyncSession) -> Board | None:
        stmt = select(Board).where(Board.is_default == True).limit(1)
        result = await session.execute(stmt)
        board = result.scalars().first()
        if board:
            return board
        stmt = select(Board).where(Board.is_active == True).order_by(Board.display_order, Board.id).limit(1)
        result = await session.execute(stmt)
        return result.scalars().first()

    async def create_board(
        self,
        session: AsyncSession,
        slug: str,
        name: str,
        icon: str = "",
        description: str = "",
        system_prompt: str = "",
        source_type: str = "rss",
        source_config: dict | None = None,
        display_order: int = 0,
        schedule: str = "",
        notify_channels: str = "",
        perspectives: dict | None = None,
        prompt_key: str = "daily_briefing",
        output_language: str = "auto",
    ) -> Board:
        board = Board(
            slug=slug,
            name=name,
            icon=icon,
            description=description,
            system_prompt=system_prompt,
            source_type=source_type,
            source_config=source_config,
            display_order=display_order,
            schedule=schedule,
            notify_channels=notify_channels,
            perspectives=perspectives,
            prompt_key=prompt_key,
            output_language=output_language,
        )
        session.add(board)
        await session.commit()
        await session.refresh(board)
        return board

    async def update_board(
        self, session: AsyncSession, slug: str, updates: dict
    ) -> Board | None:
        board = await self.get_board_by_slug(session, slug)
        if not board:
            return None
        allowed = {
            "name", "icon", "description", "system_prompt",
            "source_type", "source_config", "display_order", "is_active",
            "schedule", "notify_channels", "perspectives", "prompt_key",
            "output_language"
        }
        for key, value in updates.items():
            if key in allowed and value is not None:
                setattr(board, key, value)
        await session.commit()
        await session.refresh(board)
        return board

    async def delete_board(self, session: AsyncSession, slug: str) -> bool:
        board = await self.get_board_by_slug(session, slug)
        if not board or board.is_default:
            return False
        board.is_active = False
        await session.commit()
        return True
