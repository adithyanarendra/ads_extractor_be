import os
from dotenv import load_dotenv
import urllib.parse
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker, declarative_base

load_dotenv()

SUPABASE_DB_PASS_RAW = os.getenv("SUPABASE_DB_PASS")
SUPABASE_DB_PASS = urllib.parse.quote_plus(SUPABASE_DB_PASS_RAW)

DB_USER = "postgres.cehisscgqmcllzejlruz"
DB_HOST = "db.cehisscgqmcllzejlruz.supabase.co"
DB_PORT = 5432
DB_NAME = "postgres"

DATABASE_URL = (
    f"postgresql+asyncpg://postgres:{SUPABASE_DB_PASS}@{DB_HOST}:5432/postgres"
)


engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    future=True,
    pool_size=3,
    max_overflow=5,
    pool_recycle=300,
    pool_timeout=30,
    # connect_args={"ssl": True},
)
SessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
Base = declarative_base()


async def get_db():
    async with SessionLocal() as session:
        yield session
