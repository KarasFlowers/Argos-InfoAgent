from sqlalchemy.future import select

from app.core.db import AsyncSessionLocal
from app.models.domain import ChatMessage


async def save_chat_message(article_url: str, role: str, content: str):
    """Save a single chat message to the database."""
    async with AsyncSessionLocal() as session:
        message = ChatMessage(article_url=article_url, role=role, content=content)
        session.add(message)
        await session.commit()


async def get_chat_history(article_url: str) -> list[ChatMessage]:
    """Retrieve all chat messages for a given article, ordered by timestamp."""
    async with AsyncSessionLocal() as session:
        statement = select(ChatMessage).where(ChatMessage.article_url == article_url).order_by(ChatMessage.timestamp)
        result = await session.execute(statement)
        return result.scalars().all()
