import os
from dotenv import load_dotenv
import urllib.parse
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker, declarative_base

load_dotenv()

SUPABASE_DB_PASS_RAW = os.getenv("SUPABASE_DB_PASS")
SUPABASE_DB_PASS = urllib.parse.quote_plus(SUPABASE_DB_PASS_RAW)

DB_USER = "postgres.cehisscgqmcllzejlruz"
DB_HOST = "aws-1-ap-southeast-1.pooler.supabase.com"
DB_PORT = 5432
DB_NAME = "postgres"

DATABASE_URL = (
    f"postgresql+asyncpg://{DB_USER}:{SUPABASE_DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
)


engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    future=True,
    pool_size=5,
    max_overflow=5,
    pool_recycle=300,
    pool_timeout=10,
)
SessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
Base = declarative_base()


async def get_db():
    async with SessionLocal() as session:
        yield session
