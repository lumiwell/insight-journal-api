from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select, col
import uuid
from models import ChatSession, Message, User
from auth import get_password_hash

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

async def get_user_by_email(db: AsyncSession, email: str) -> User | None:
    statement = select(User).where(User.email == email)
    result = await db.execute(statement)
    return result.scalars().first()

async def create_user(db: AsyncSession, email: str, password: str) -> User:
    hashed_password = get_password_hash(password)
    user = User(email=email, hashed_password=hashed_password)
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user

async def bind_session_to_user(db: AsyncSession, session_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    session = await db.get(ChatSession, session_id)
    if session and session.user_id is None:
        session.user_id = user_id
        db.add(session)
        await db.commit()
        return True
    return False
