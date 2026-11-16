from pydantic import BaseModel, Field


class AskIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


class FollowOut(BaseModel):
    meeting_id: int
    following: bool


class StatusOut(BaseModel):
    following: bool
    questions: int
    answers: int


class QuestionOut(BaseModel):
    question_id: str
