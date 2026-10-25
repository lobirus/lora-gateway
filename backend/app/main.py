import logging

from fastapi import FastAPI
from fastapi.middleware.gzip import GZipMiddleware
from sqlalchemy import text

from .db import engine, init_db
from .routers import analytics, auth, keys, models, playground, providers, system
from .seed import seed_all

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = FastAPI(title="Lora Gateway control plane", docs_url="/api/docs", openapi_url="/api/openapi.json", redoc_url=None)
app.add_middleware(GZipMiddleware, minimum_size=1024)
for r in (auth.router, providers.router, models.router, keys.router, analytics.router, playground.router, system.router):
    app.include_router(r)


@app.on_event("startup")
def startup():
    # one worker does the seeding; a PG advisory lock serialises multiple uvicorn workers
    init_db_locked()


def init_db_locked():
    with engine.connect() as c:
        c.execute(text("SELECT pg_advisory_lock(424242)"))
        try:
            init_db()
            seed_all()
        finally:
            c.execute(text("SELECT pg_advisory_unlock(424242)"))
            c.commit()
