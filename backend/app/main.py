from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import db
from app.config import get_settings
from app.graph import close_checkpointer, init_checkpointer
from app.routers import campaigns, cron, gmail_auth, tracking


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_pool()
    init_checkpointer()  # also runs the LangGraph checkpoint tables' setup() migration
    yield
    close_checkpointer()
    db.close_pool()


app = FastAPI(title="AI-SDR", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(campaigns.router)
app.include_router(gmail_auth.router)
app.include_router(tracking.router)
app.include_router(cron.router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
