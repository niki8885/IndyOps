from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core import config
from app.core.database import engine, Base
from app.core.database_eve import EveBase, eve_engine
from app.api.auth_router import router as auth_router
from app.api.projects_router import router as projects_router
from app.api.organisations_router import router as organisations_router
from app.api.inventory_router import router as inventory_router
from app.api.deliveries_router import router as deliveries_router
from app.api.facilities_router import router as facilities_router
from app.api.blueprints_router import router as blueprints_router
from app.api.manufacturing_router import router as manufacturing_router
from app.api.research_router import router as research_router
from app.api.eve_router import router as eve_router
from app.api.analysis_router import router as analysis_router
from app.api.market_router import router as market_router
from app.api.tracking_router import router as tracking_router
from app.api.simulation_router import router as simulation_router
from app.api.characters_router import router as characters_router
from app.api.ore_router import router as ore_router
from app.api.trade_router import router as trade_router
from app.api.haul_router import router as haul_router
from app.api.agenda_router import router as agenda_router
from app.api.encyclopedia_router import router as encyclopedia_router

# Schema bootstrap for the API container (the worker runs jobs only and sets
# RUN_DB_BOOTSTRAP=0). Scheduled jobs live in the separate worker (app.worker).
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


app.include_router(auth_router, prefix="/api/v1", tags=["Authentication"])
app.include_router(organisations_router, prefix="/api/v1/organisations", tags=["Organisations"])
app.include_router(projects_router, prefix="/api/v1/projects", tags=["Projects"])
app.include_router(inventory_router, prefix="/api/v1/inventory", tags=["Inventory"])
app.include_router(deliveries_router, prefix="/api/v1/deliveries", tags=["Deliveries"])
app.include_router(facilities_router, prefix="/api/v1/facilities", tags=["Facilities"])
app.include_router(blueprints_router, prefix="/api/v1/blueprints", tags=["Blueprints"])
app.include_router(manufacturing_router, prefix="/api/v1/manufacturing", tags=["Manufacturing"])
app.include_router(research_router, prefix="/api/v1/manufacturing/research", tags=["Blueprint Research"])
app.include_router(eve_router, prefix="/api/v1/eve", tags=["EVE SDE"])
app.include_router(analysis_router, prefix="/api/v1/analysis", tags=["Analysis"])
app.include_router(market_router, prefix="/api/v1/market", tags=["Market Browser"])
app.include_router(tracking_router, prefix="/api/v1/tracking", tags=["Tracking"])
app.include_router(simulation_router, prefix="/api/v1/simulation", tags=["Simulation"])
app.include_router(characters_router, prefix="/api/v1/characters", tags=["Personal File"])
app.include_router(ore_router, prefix="/api/v1/ore", tags=["Ore Acquisition"])
app.include_router(trade_router, prefix="/api/v1/trade", tags=["Trade Optimizer"])
app.include_router(haul_router, prefix="/api/v1/trade", tags=["Trade Haul"])
app.include_router(agenda_router, prefix="/api/v1/agenda", tags=["Agenda"])
app.include_router(encyclopedia_router, prefix="/api/v1/encyclopedia", tags=["Encyclopedia"])


@app.get("/", tags=["Health"])
async def health_check():
    return {
        "status": "online",
        "app": config.API_TITLE,
        "version": config.API_VERSION,
    }
