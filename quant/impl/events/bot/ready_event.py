from __future__ import annotations

import attrs

from ..event import DiscordEvent, InternalEvent
from ..types import EventTypes


@attrs.define(kw_only=True)
class ReadyEvent(DiscordEvent):
    event_api_name: EventTypes = attrs.field(default=EventTypes.READY_EVENT)

    def emit(self, *args, **kwargs):
        return self


@attrs.define(kw_only=True)
class ShardReadyEvent(InternalEvent):
    shard_id: int = attrs.field(default=None)

    @staticmethod
    def build(event: ShardReadyEvent, *args, **kwargs) -> ShardReadyEvent:
        event.shard_id = args[0]
        return event

    def emit(self, *args, **kwargs):
        return self
