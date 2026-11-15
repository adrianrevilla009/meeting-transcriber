import uuid
from typing import NewType

SessionId = NewType("SessionId", str)


def new_session_id() -> SessionId:
    return SessionId(uuid.uuid4().hex)
