from fastapi import APIRouter

from app.modules.tournaments.routes import (
    tournaments,
    versions,
    stages,
    teams,
    rosters,
    matches,
    public,
)


router = APIRouter()

router.include_router(tournaments.router, prefix="/tournaments", tags=["tournaments"])
router.include_router(versions.router, prefix="/tournaments", tags=["tournaments"])
router.include_router(stages.router, prefix="/tournaments", tags=["tournaments"])
router.include_router(teams.router, prefix="/tournaments", tags=["tournaments"])
router.include_router(rosters.router, prefix="/tournaments", tags=["tournaments"])
router.include_router(matches.router, prefix="/tournaments", tags=["tournaments"])
router.include_router(public.router, prefix="/tournaments", tags=["tournaments"])
