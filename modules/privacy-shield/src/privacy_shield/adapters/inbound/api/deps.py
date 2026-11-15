import hmac

from fastapi import Depends, Header, HTTPException, Request, status

from privacy_shield.application.runtime import Runtime
from privacy_shield.config import UNSET_TOKEN


def get_runtime(request: Request) -> Runtime:
    rt: Runtime = request.app.state.runtime
    return rt


def require_token(request: Request, authorization: str = Header(default="")) -> None:
    expected: str = request.app.state.api_token
    if not expected or expected == UNSET_TOKEN:
        # Fallo cerrado: nunca se acepta el token por defecto, que es público.
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "ANON_API_TOKEN no está configurado")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not hmac.compare_digest(token, expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token inválido")


Auth = Depends(require_token)
