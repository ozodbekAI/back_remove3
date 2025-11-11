from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import sessionmaker
from config import settings
from utils.logger import logger
import asyncio

_engine = None
_async_session_maker = None


def get_engine():
    """Engine yaratish yoki mavjud engine'ni qaytarish"""
    global _engine
    
    if _engine is None:
        _engine = create_async_engine(
            settings.database_url.replace("postgresql://", "postgresql+asyncpg://"),
            echo=False,
            pool_size=5,
            max_overflow=10,
            pool_pre_ping=True,
            pool_recycle=3600,
            # Celery uchun muhim
            poolclass=None  # NullPool ishlatish
        )
    
    return _engine


def get_session_maker():
    global _async_session_maker
    
    if _async_session_maker is None:
        engine = get_engine()
        _async_session_maker = async_sessionmaker(
            engine,
            class_=AsyncSession,
            expire_on_commit=False
        )
    
    return _async_session_maker


async def get_async_session():
    session_maker = get_session_maker()
    async with session_maker() as session:
        yield session


def get_new_session():
    session_maker = get_session_maker()
    return session_maker()


async def init_db():
    engine = get_engine()
    async with engine.begin() as conn:
        from .models import Base
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables created/verified")


async def close_db():
    global _engine, _async_session_maker
    
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _async_session_maker = None
    
    logger.info("Database connections closed")