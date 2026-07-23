import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models.ai_conversation import AIConversation


class AIConversationRepository:

    async def get_by_id(
        self,
        db: AsyncSession,
        conversation_id: uuid.UUID,
    ) -> AIConversation | None:

        result = await db.execute(
            select(AIConversation).where(AIConversation.id == conversation_id)
        )

        return result.scalar_one_or_none()

    async def list_by_user(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
    ) -> list[AIConversation]:

        result = await db.execute(
            select(AIConversation)
            .where(AIConversation.user_id == user_id)
            .order_by(AIConversation.created_at.desc())
        )

        return list(result.scalars().all())

    async def create(
        self,
        db: AsyncSession,
        conversation: AIConversation,
    ) -> AIConversation:

        db.add(conversation)

        await db.flush()

        await db.refresh(conversation)

        return conversation

    async def update_title(
        self,
        db: AsyncSession,
        conversation: AIConversation,
        title: str,
    ) -> AIConversation:

        conversation.title = title

        await db.flush()

        await db.refresh(conversation)

        return conversation

    async def delete(
        self,
        db: AsyncSession,
        conversation: AIConversation,
    ) -> None:

        await db.delete(conversation)

        await db.flush()


ai_conversation_repository = AIConversationRepository()
