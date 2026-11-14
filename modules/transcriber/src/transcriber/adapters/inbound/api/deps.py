import hmac

from collections.abc import Iterator

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from transcriber.application.runtime import Runtime
from transcriber.config import UNSET_TOKEN, get_settings


def require_token(authorization: str = Header(default="")) -> None:
    expected = get_settings().api_token
    if not expected or expected == UNSET_TOKEN:
        # Fallo cerrado: nunca se acepta el token por defecto, que es público.
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "MT_API_TOKEN no está configurado")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not hmac.compare_digest(token, expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token inválido")


Auth = Depends(require_token)


def get_runtime(request: Request) -> Runtime:
    rt: Runtime = request.app.state.runtime
    return rt


def get_session(rt: Runtime = Depends(get_runtime)) -> Iterator[Session]:
    with rt.session() as session:
        yield session
