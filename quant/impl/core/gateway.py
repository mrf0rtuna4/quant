from __future__ import annotations

import sys
import enum
import time
import zlib
from typing import (
    Dict,
    TypeVar,
    List,
    TYPE_CHECKING
)
import asyncio
from traceback import print_exception

import json
import attrs
import aiohttp

if TYPE_CHECKING:
    from quant.impl.core.client import Client
    from quant.entities.snowflake import Snowflake

from quant.impl.events.bot.raw_event import RawDispatchEvent
from quant.entities.activity import Activity, ActivityStatus
from quant.impl.core.route import Gateway as gateway_route
from quant.entities.intents import Intents
from quant.utils import logger

_ZLIB_SUFFIX = b"\x00\x00\xff\xff"

WSMessageT = TypeVar("WSMessageT", bound=str | bytes)


class OpCode(enum.IntEnum):
    DISPATCH = 0
    HEARTBEAT = 1
    IDENTIFY = 2
    PRESENCE_UPDATE = 3
    VOICE_STATE_UPDATE = 4
    RESUME = 6
    RECONNECT = 7
    REQUEST_GUILD_MEMBERS = 8
    INVALID_SESSION = 9
    HELLO = 10
    HEARTBEAT_ACK = 11


@attrs.define
class IdentifyProperties:
    os: str = attrs.field()
    browser: str = attrs.field()
    device: str = attrs.field(default="quant")


@attrs.define
class IdentifyPayload:
    token: str = attrs.field()
    properties: IdentifyProperties = attrs.field()
    shard: List[int] = attrs.field()
    large_threshold: int = attrs.field()
    intents: Intents = attrs.field(default=Intents.ALL_PRIVILEGED)


class Gateway:
    def __init__(
        self,
        intents: Intents,
        client: Client,
        shard_id: int = 0,
        num_shards: int = 1,
        session: aiohttp.ClientSession | None = None,
        mobile: bool = False
    ) -> None:
        self.client = client
        self.loop = client.loop
        self.session = session
        self.websocket: aiohttp.ClientWebSocketResponse | None = None
        self.identify = IdentifyPayload(
            token=client.token,
            properties=IdentifyProperties(
                os=sys.platform,
                browser="Discord iOS" if mobile else f"quant[{sys.platform}]"
            ),
            shard=[shard_id, num_shards],
            large_threshold=250,
            intents=intents
        )
        self._buffer = bytearray()
        self._inflator = zlib.decompressobj()

        self._sequence: int | None = None
        self._interval: float | None = None
        self._session_id: int | None = None
        self._heartbeat = 0

    async def connect(self) -> None:
        ws_url = gateway_route.DISCORD_WS_URL.uri.url_string.format(10)

        self.session = aiohttp.ClientSession()
        self.websocket = await self.session.ws_connect(url=ws_url)

        logger.info(
            "Connecting to shard with ID %s (total shard count: %s)",
            self.identify.shard[0],
            len(self.client.shards) or 1
        )

        await self._send_identify()

        while not self.websocket.closed:
            await self._websocket_read()
            await self._keep_alive()

    async def close(self, code: int = 4000):
        logger.info("Connection closing, code: %s", code)

        if not self.websocket:
            return

        await self.websocket.close(code=code)

        self._buffer.clear()

    def on_websocket_message(self, message: WSMessageT) -> dict | None:
        self._buffer.extend(message)

        if len(message) < 4 or message[-4:] != _ZLIB_SUFFIX:
            return

        message = self._inflator.decompress(self._buffer)
        try:
            self._buffer = bytearray()
            return json.loads(message.decode("utf8"))
        except zlib.error:
            return

    async def opcode_validator(self, message: WSMessageT) -> None:
        performed_message = self.on_websocket_message(message)

        if performed_message is None:
            return

        self._sequence = performed_message.get("s")
        opcode, data = (
            performed_message.get("op"),
            performed_message.get("d")
        )

        await self.client.event_controller.dispatch(RawDispatchEvent(data=performed_message))

        match opcode:
            case OpCode.DISPATCH:
                received_event_type = performed_message.get("t")
                event_details = data

                self.client.event_factory.cache_item(received_event_type, **event_details)
                await self.client.event_controller.dispatch(received_event_type, event_details)
            case OpCode.INVALID_SESSION:
                await self.websocket.close(code=4000)
                await self.reconnect(code=4000)
            case OpCode.HELLO:
                await self._send_hello(data.get("heartbeat_interval"))
            case OpCode.RECONNECT:
                await self.close(code=1012)

    async def _websocket_read(self) -> None:
        async for message in self.websocket:
            try:
                await self.opcode_validator(message.data)
            except Exception as e:
                print_exception(e)

            close_code = self.websocket.close_code
            if close_code is not None:
                logger.error("Gateway received close code: %s", close_code)
                break

    async def _send(self, data) -> None:
        await self.websocket.send_str(data)

    async def _send_heartbeat(self, interval: float) -> None:
        payload = self.payload(opcode=OpCode.HEARTBEAT, sequence=self._sequence)

        self._heartbeat = time.perf_counter()

        await self._send(payload)
        await asyncio.sleep(interval)

        self.loop.create_task(self._send_heartbeat(interval))

    async def _send_hello(self, heartbeat_interval: float) -> None:
        seconds_interval = heartbeat_interval / 1000
        await asyncio.sleep((seconds_interval - 2000) / 1000)

        self.loop.create_task(self._send_heartbeat(seconds_interval))

        self._buffer.clear()

    async def _send_identify(self) -> None:
        await self._send(self.payload(
            opcode=OpCode.IDENTIFY,
            data=attrs.asdict(self.identify)  # type: ignore
        ))

    async def _send_resume(self) -> None:
        payload = self.payload(
            opcode=OpCode.RESUME,
            data={
                "token": self.client.token,
                "session_id": self._session_id,
                "seq": self._sequence
            }
        )
        await self._send(payload)

    async def _keep_alive(self) -> None:
        await asyncio.sleep(20)

        if (self._heartbeat + float(60)) < time.perf_counter():
            await self.reconnect(code=4000)

    async def send_presence(
        self,
        activity: Activity | None = None,
        status: ActivityStatus | None = None,
        since: int | None = None,
        afk: bool = False
    ) -> None:
        presence = {
            "activities": [
                {
                    "name": activity.name,
                    "type": activity.type.value,
                    "url": activity.url
                }
            ],
            "status": status.value,
            "since": since,
            "afk": afk
        }
        payload = self.payload(
            opcode=OpCode.PRESENCE_UPDATE,
            data=presence
        )
        await self._send(payload)

    async def reconnect(self, code: int) -> None:
        logger.info("Reconnecting (code: %s)", code)

        await self.close(code=code)

        if code == 4000:
            await self._send_resume()
            return

        await self.connect()

    async def voice_connect(
        self,
        guild_id: Snowflake | int,
        channel_id: Snowflake | int,
        self_mute: bool = False,
        self_deaf: bool = False
    ) -> None:
        payload = self.payload(
            opcode=OpCode.VOICE_STATE_UPDATE,
            data={
                "guild_id": guild_id,
                "channel_id": channel_id,
                "self_mute": self_mute,
                "self_deaf": self_deaf
            }
        )

        await self._send(payload)

    @staticmethod
    def payload(
        opcode: OpCode | int,
        data: dict | str | None = None,
        sequence: int | None = None,
        event_name: str | None = None
    ) -> str | None:
        payload = {"op": opcode if isinstance(opcode, int) else opcode.value, "d": data}
        if opcode == OpCode.DISPATCH:
            payload.update({"s": sequence, "t": event_name})

        return json.dumps(payload)
