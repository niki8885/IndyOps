from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core import config
from app.core.database import engine, Base
from app.api.auth_router import router as auth_router
from app.api.projects_router import router as projects_router
from app.api.organisations_router import router as organisations_router

from app.tasks.scheduler import scheduler


Base.metadata.create_all(bind=engine)

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


app.include_router(auth_router,    prefix="/api/v1",         tags=["Authentication"])
app.include_router(projects_router,     prefix="/api/v1",         tags=["Projects Management"])
app.include_router(organisations_router,     prefix="/api/v1",         tags=["Organisations Management"])


@app.get("/", tags=["Health"])
async def health_check():
    return {
        "status": "online",
        "app": config.API_TITLE,
        "version": config.API_VERSION,
    }