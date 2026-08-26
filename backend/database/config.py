import os
from dotenv import load_dotenv
from sqlalchemy.pool import NullPool

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase


load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise ValueError("Variável DATABASE_URL não encontrada no arquivo .env!")

engine = create_async_engine(DATABASE_URL, poolclass=NullPool, echo=False)

async_session_env = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

class Base(DeclarativeBase):
    pass

async def get_db():
    async with async_session_env() as session:
        try:
            yield session
        finally: 
            await session.close()