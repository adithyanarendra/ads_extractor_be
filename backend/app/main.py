from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .core.database import engine, Base
from .api.users import routes as users_routes
from .api.invoices import routes as invoices_routes
from .api.companies import routes as companies_routes

app = FastAPI(title="FastAPI Invoice OCR")

origins = [
    "http://localhost:5173",  # your frontend URL (Vite default)
    "http://127.0.0.1:5173",
    "http://localhost:3000",  # React default dev server
    "http://127.0.0.1:3000",
    "https://ads-extractor-fe.onrender.com",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,  # or ["*"] to allow all
    allow_credentials=True,
    allow_methods=["*"],  # GET, POST, PUT, DELETE etc.
    allow_headers=["*"],  # Allow all headers
)

app.include_router(users_routes.router)
app.include_router(invoices_routes.router)
app.include_router(companies_routes.router)


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
    # Create DB tables if they don't exist
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
