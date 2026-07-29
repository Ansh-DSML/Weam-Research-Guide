from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse

from app.config import settings
from app.logging_config import configure_logging, get_logger
from app.middleware import BodySizeLimitMiddleware, RequestContextMiddleware
from app.routers import companies, graph, health

FRONTEND_FILE = Path(__file__).resolve().parents[2] / "frontend" / "Weam_Research_Console.html"

configure_logging(settings.log_dir, settings.log_level)
logger = get_logger("app.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("app_startup", extra={"db_target": settings.database_url.split("@")[-1]})
    yield
    logger.info("app_shutdown")


app = FastAPI(title="Weam Research Console API", lifespan=lifespan)

app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.max_request_body_bytes)
app.add_middleware(RequestContextMiddleware)

app.include_router(health.router)
app.include_router(companies.router)
app.include_router(graph.router)


@app.get("/")
def serve_frontend():
    return FileResponse(FRONTEND_FILE)
