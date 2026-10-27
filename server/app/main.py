import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import errors
from .api import admin, agent, feeds, internal, live, me, reports, sensors, sirens, system, zones
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

errors.install(app)

# Added last so it is the outermost app middleware: every response, including a 500, gets CORS headers.
origins = get_settings().allowed_origins
for dev_origin in ("http://localhost:5173", "http://localhost:5174"):
    if dev_origin not in origins:
        origins = origins + [dev_origin]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=False,
                   allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
                   allow_headers=["Authorization", "Content-Type"], expose_headers=["X-Request-ID"])

for module in (system, me, live, zones, feeds, admin, sensors, sirens, reports, agent, internal):
    app.include_router(module.router, prefix=API_PREFIX)


@app.get("/")
def root():
    return {"name": "HUDA API", "docs": f"{API_PREFIX}/docs", "health": f"{API_PREFIX}/health"}
