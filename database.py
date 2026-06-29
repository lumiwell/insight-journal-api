import os
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlmodel.ext.asyncio.session import AsyncSession

# load_dotenv is called in main.py, but we can also just rely on os.getenv if loaded early
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://lumi:123456@localhost:5432/journal")

engine = create_async_engine(DATABASE_URL, echo=False, future=True)

async_session_maker = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)

async def get_session():
    async with async_session_maker() as session:
        yield session
