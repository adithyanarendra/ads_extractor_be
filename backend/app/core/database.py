import os
from dotenv import load_dotenv
import urllib.parse
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker, declarative_base

load_dotenv()

SUPABASE_DB_PASS_RAW = os.getenv("SUPABASE_DB_PASS")
SUPABASE_DB_PASS = urllib.parse.quote_plus(SUPABASE_DB_PASS_RAW)

DB_USER = "postgres.cehisscgqmcllzejlruz"
DB_PORT = 5432
DB_NAME = "postgres"

# only for render deployment - only ipv4
# DB_HOST = "aws-1-ap-southeast-1.pooler.supabase.com"
# only for non-render deployment - ipv6 support
# only for render deployment - only ipv4
# DATABASE_URL = (
#     f"postgresql+asyncpg://{DB_USER}:{SUPABASE_DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
# )
DB_HOST = "db.cehisscgqmcllzejlruz.supabase.co"
# only for non-render deployment - ipv6 support
DATABASE_URL = (
    f"postgresql+asyncpg://postgres:{SUPABASE_DB_PASS}@{DB_HOST}:5432/postgres"
)

# # LOCAL DB HOST
# LOCAL_DB_PASS = urllib.parse.quote_plus(LOCAL_DB_PASS_RAW)
# LOCAL_DB_PASS_RAW = os.getenv("LOCAL_DB_PASS")
# DB_USER = os.getenv("LOCAL_DB_USER")
# DB_HOST = os.getenv("LOCAL_DB_HOST")
# DB_PORT = os.getenv("LOCAL_DB_PORT")
# DB_NAME = os.getenv("LOCAL_DB_NAME")


# DATABASE_URL = (
#     f"postgresql+asyncpg://{DB_USER}:{LOCAL_DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
# )


engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    future=True,
    pool_size=3,
    max_overflow=2,
    pool_recycle=300,
    pool_timeout=30,
    pool_pre_ping=True,
)
SessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
Base = declarative_base()


async def get_db():
    async with SessionLocal() as session:
        yield session
