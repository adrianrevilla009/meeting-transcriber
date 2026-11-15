from typing import Literal

from pydantic import BaseModel, Field

MAX_TEXT = 200_000


class AnonymizeIn(BaseModel):
    session_id: str | None = None
    text: str = Field(max_length=MAX_TEXT)


class EntityOut(BaseModel):
    type: str
    token: str
    strategy: str


class AnonymizeOut(BaseModel):
    session_id: str
    text: str
    entities: list[EntityOut]


class DeanonymizeIn(BaseModel):
    session_id: str
    text: str = Field(max_length=MAX_TEXT)


class DeanonymizeOut(BaseModel):
    text: str


class MessageIn(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str = Field(max_length=MAX_TEXT)
    name: str | None = None


class ChatIn(BaseModel):
    session_id: str | None = None
    provider: str | None = None
    model: str | None = None
    messages: list[MessageIn] = Field(min_length=1)
    stream: bool = False
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_tokens: int | None = Field(default=None, ge=1)


class MessageOut(BaseModel):
    role: Literal["assistant"] = "assistant"
    content: str


class ChatOut(BaseModel):
    session_id: str
    provider: str
    model: str
    message: MessageOut
    finish_reason: str | None
    entities: dict[str, int]
    unknown_tokens: int


class ProviderOut(BaseModel):
    name: str
    configured: bool
    leaves_machine: bool
