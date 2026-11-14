import hmac

from fastapi import Depends, Header, HTTPException, status

from app.config import UNSET_TOKEN, get_settings


def require_token(authorization: str = Header(default="")) -> None:
    expected = get_settings().api_token
    if not expected or expected == UNSET_TOKEN:
        # Fallo cerrado: nunca se acepta el token por defecto, que es público.
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "MT_API_TOKEN no está configurado")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not hmac.compare_digest(token, expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token inválido")


Auth = Depends(require_token)
