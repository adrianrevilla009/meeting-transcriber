import hmac

from fastapi import Depends, Header, HTTPException, status

from app.config import get_settings


def require_token(authorization: str = Header(default="")) -> None:
    expected = get_settings().api_token
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not hmac.compare_digest(token, expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token inválido")


Auth = Depends(require_token)
