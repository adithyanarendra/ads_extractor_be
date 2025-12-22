from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic_core import CoreSchema, core_schema
from pydantic import GetCoreSchemaHandler
from typing import Any
from app.api.quickbooks.routes import router as quickbooks_router


class AssumedAsyncSession:
    @classmethod
    def __get_pydantic_core_schema__(
        cls, source: type[Any], handler: GetCoreSchemaHandler
    ) -> CoreSchema:
        return core_schema.any_schema()


AsyncSession.__get_pydantic_core_schema__ = (
    AssumedAsyncSession.__get_pydantic_core_schema__
)


from .core.database import engine, Base
from app.api.lov.routes import router as lov_router
from .api.users import routes as users_routes
from .api.invoices import routes as invoices_routes
from .api.companies import routes as companies_routes
from app.api.batches.routes import router as batches_router
from .api.user_docs.routes import router as user_docs_router
from .api.reports.routes import router as reports_router
from app.api.quickbooks import routes as quickbooks_routes
from .api.statements.routes import router as statements_router
from .api.accounting.routes import router as accounting_router
from .api.sales.routes import router as sales_invoices_router
from .api.suppliers.routes import router as suppliers_router
from .api.payments.routes import router as payments_router


app = FastAPI(title="FastAPI Invoice OCR")

origins = [
    "http://localhost:5173",
    "http://localhost:5174",
    "http://127.0.0.1:5173",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "https://aicountant.tech",
    "49.43.169.79",
    # NGROK - payment testing - to be removed later
    "https://embrasured-tristian-draughtiest.ngrok-free.dev",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(users_routes.router)
app.include_router(invoices_routes.router)
app.include_router(companies_routes.router)
app.include_router(lov_router)
app.include_router(batches_router)
app.include_router(user_docs_router)
app.include_router(reports_router)
app.include_router(quickbooks_routes.router)
app.include_router(statements_router)
app.include_router(accounting_router)
app.include_router(sales_invoices_router)
app.include_router(suppliers_router)
app.include_router(payments_router)


@app.get("/")
async def api_home():
    return JSONResponse(
        content={
            "message": "ADS Extractor - API Home",
        }
    )


@app.get("/health")
async def health_check():
    return JSONResponse(content={"ok": True})


app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")


@app.on_event("startup")
async def startup():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


@app.on_event("shutdown")
async def shutdown():
    await engine.dispose()


app.include_router(quickbooks_router)
