from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select, col
import uuid
from models import ChatSession, Message

async def get_or_create_session(db: AsyncSession, session_id: uuid.UUID) -> ChatSession:
    session = await db.get(ChatSession, session_id)
    if not session:
        session = ChatSession(id=session_id)
        db.add(session)
        await db.commit()
        await db.refresh(session)
    return session

async def save_message(db: AsyncSession, session_id: uuid.UUID, role: str, content: str) -> Message:
    msg = Message(session_id=session_id, role=role, content=content)
    db.add(msg)
    await db.commit()
    await db.refresh(msg)
    return msg

async def get_recent_messages(db: AsyncSession, session_id: uuid.UUID, limit: int = 30) -> list[Message]:
    statement = select(Message).where(Message.session_id == session_id).order_by(col(Message.created_at).desc()).limit(limit)
    result = await db.execute(statement)
    messages = result.scalars().all()
    # Reverse to get chronological order
    return list(reversed(messages))
