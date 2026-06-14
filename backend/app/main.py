from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core import config
from app.core.database import engine, Base
from app.core.database_eve import EveBase, eve_engine
from app.api.auth_router import router as auth_router
from app.api.projects_router import router as projects_router
from app.api.organisations_router import router as organisations_router
from app.api.inventory_router import router as inventory_router
from app.api.facilities_router import router as facilities_router
from app.api.manufacturing_router import router as manufacturing_router
from app.api.eve_router import router as eve_router
from app.api.analysis_router import router as analysis_router

from app.tasks.scheduler import scheduler


Base.metadata.create_all(bind=engine)
EveBase.metadata.create_all(bind=eve_engine)

app = FastAPI(
    title=config.API_TITLE,
    version=config.API_VERSION
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def start_tasks():
    if not scheduler.running:
        scheduler.start()
        print("[INFO] Scheduler started")

@app.on_event("shutdown")
def stop_tasks():
    if scheduler.running:
        scheduler.shutdown()
        print("[INFO] Background scheduler shut down.")


app.include_router(auth_router,          prefix="/api/v1",                    tags=["Authentication"])
app.include_router(organisations_router, prefix="/api/v1/organisations",      tags=["Organisations"])
app.include_router(projects_router,      prefix="/api/v1/projects",           tags=["Projects"])
app.include_router(inventory_router,     prefix="/api/v1/inventory",          tags=["Inventory"])
app.include_router(facilities_router,    prefix="/api/v1/facilities",         tags=["Facilities"])
app.include_router(manufacturing_router, prefix="/api/v1/manufacturing",      tags=["Manufacturing"])
app.include_router(eve_router,           prefix="/api/v1/eve",                tags=["EVE SDE"])
app.include_router(analysis_router,      prefix="/api/v1/analysis",           tags=["Analysis"])


@app.get("/", tags=["Health"])
async def health_check():
    return {
        "status": "online",
        "app": config.API_TITLE,
        "version": config.API_VERSION,
    }