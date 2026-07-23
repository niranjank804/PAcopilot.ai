import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models.ai_message import AIMessage


class AIMessageRepository:

    async def list_by_conversation(
        self,
        db: AsyncSession,
        conversation_id: uuid.UUID,
    ) -> list[AIMessage]:

        result = await db.execute(
            select(AIMessage)
            .where(AIMessage.conversation_id == conversation_id)
            .order_by(AIMessage.created_at)
        )

        return list(result.scalars().all())

    async def create(
        self,
        db: AsyncSession,
        message: AIMessage,
    ) -> AIMessage:

        db.add(message)

        await db.flush()

        await db.refresh(message)

        return message


ai_message_repository = AIMessageRepository()
