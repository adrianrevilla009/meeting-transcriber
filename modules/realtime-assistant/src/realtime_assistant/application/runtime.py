"""Dependencias ya cableadas que recibe el adaptador de entrada (API). Se construye en bootstrap."""

from collections.abc import Callable
from dataclasses import dataclass

from realtime_assistant.application.assistant import MeetingAssistant
from realtime_assistant.application.ports import EventStorePort


@dataclass
class Runtime:
    assistant: MeetingAssistant
    store: EventStorePort
    health: Callable[[], dict[str, object]]
