import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import errors
from .api import admin, agent, feeds, internal, live, me, reports, sensors, system, zones
from .config import get_settings
from .services import classifier

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

API_PREFIX = "/api/v1"


@asynccontextmanager
async def lifespan(app: FastAPI):
    classifier.load()  # once at start-up (architecture.md §5.2)
    yield


app = FastAPI(title="HUDA API", version="0.1.0", lifespan=lifespan,
              docs_url=f"{API_PREFIX}/docs", openapi_url=f"{API_PREFIX}/openapi.json")

origins = get_settings().allowed_origins
if "http://localhost:5173" not in origins:
    origins = origins + ["http://localhost:5173"]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=False,
                   allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
                   allow_headers=["Authorization", "Content-Type"], expose_headers=["X-Request-ID"])
errors.install(app)

for module in (system, me, live, zones, feeds, admin, sensors, reports, agent, internal):
    app.include_router(module.router, prefix=API_PREFIX)


@app.get("/")
def root():
    return {"name": "HUDA API", "docs": f"{API_PREFIX}/docs", "health": f"{API_PREFIX}/health"}
