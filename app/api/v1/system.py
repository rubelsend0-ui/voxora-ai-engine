from __future__ import annotations

from fastapi import APIRouter, Depends

from app.ai_engine.registry import EngineRegistry
from app.api.deps import get_current_user, get_registry_dep
from app.models.user import User
from app.schemas.misc import EngineStatusOut, MeOut

router = APIRouter(tags=["System"])


@router.get("/auth/me", response_model=MeOut, summary="Who am I? (validates an API key)")
def me(user: User = Depends(get_current_user)) -> MeOut:
    return MeOut(user_id=user.id, email=user.email, display_name=user.display_name)


@router.get(
    "/engines",
    response_model=list[EngineStatusOut],
    summary="Status of every AI engine (installed? model downloaded? device?)",
)
def engines(user: User = Depends(get_current_user), registry: EngineRegistry = Depends(get_registry_dep)):
    return [
        EngineStatusOut(
            engine=kind,
            available=st.available,
            adapter=st.adapter,
            device=st.device,
            model=st.model,
            reason=st.reason,
            hint=st.hint,
            details=st.details,
        )
        for kind, st in registry.statuses().items()
    ]
