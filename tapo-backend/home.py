"""Configured rooms and bulbs, shared by HTTP controls and the agent."""

import asyncio
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from tapo_control import PROJECT_ROOT, LightController, required_environment

Id = Annotated[str, Field(pattern=r"^[a-zA-Z0-9_-]+$", max_length=64)]
Percent = Annotated[int, Field(strict=True, ge=1, le=100)]


class Brightness(BaseModel):
    model_config = ConfigDict(extra="forbid")
    brightness: Percent


class Color(Brightness):
    hue: Annotated[int, Field(strict=True, ge=0, le=360)]
    saturation: Annotated[int, Field(strict=True, ge=0, le=100)]


class Bulb(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: Id
    name: str = Field(min_length=1)
    type: Literal["light"] = "light"
    host: str = Field(min_length=1, exclude=True)


class Room(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: Id
    name: str = Field(min_length=1)
    devices: list[Bulb]


class Home(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rooms: list[Room]

    @model_validator(mode="after")
    def unique_devices(self):
        if len({room.id for room in self.rooms}) != len(self.rooms):
            raise ValueError("Room IDs must be unique")
        hosts = set()
        for room in self.rooms:
            if len({device.id for device in room.devices}) != len(room.devices):
                raise ValueError(f"Device IDs must be unique within {room.id}")
            for device in room.devices:
                if device.host in hosts:
                    raise ValueError("Each bulb host must occur only once")
                hosts.add(device.host)
        return self

    @classmethod
    def from_environment(cls):
        path = Path(required_environment("HOME_CONFIG"))
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        return cls.model_validate_json(path.read_text(encoding="utf-8"))


class HomeService:
    def __init__(self, home: Home, username: str, password: str):
        self.home = home
        self.loop = asyncio.get_running_loop()
        self.controllers = {
            (room.id, device.id): LightController(device.host, username, password)
            for room in home.rooms for device in room.devices
        }

    def device(self, room_id: str, device_id: str) -> LightController:
        try:
            return self.controllers[room_id, device_id]
        except KeyError:
            raise LookupError("Unknown room or device") from None

    async def _command(self, room_id, device_id, operation, *args):
        controller = self.device(room_id, device_id)
        command = getattr(controller, operation)(*args)
        # Device sessions and locks belong to the backend loop, never the HTTP thread.
        if asyncio.get_running_loop() is self.loop:
            result = await command
        else:
            result = await asyncio.wrap_future(asyncio.run_coroutine_threadsafe(command, self.loop))
        return {"status": "ok", "room_id": room_id, "device_id": device_id, **(result or {})}

    async def get_status(self, room_id: str, device_id: str) -> dict:
        """Read fresh state from a configured bulb."""
        return await self._command(room_id, device_id, "get_status")

    async def turn_on(self, room_id: str, device_id: str) -> dict:
        """Turn on a light identified by its room ID and device ID."""
        return await self._command(room_id, device_id, "set_power", True)

    async def turn_off(self, room_id: str, device_id: str) -> dict:
        """Turn off a light identified by its room ID and device ID."""
        return await self._command(room_id, device_id, "set_power", False)

    async def change_brightness(self, room_id: str, device_id: str, brightness: int) -> dict:
        """Set light brightness to an integer percentage from 1 to 100."""
        value = Brightness(brightness=brightness)
        return await self._command(room_id, device_id, "change_brightness", value.brightness)

    async def change_color(self, room_id: str, device_id: str, hue: int,
                           saturation: int, brightness: int) -> dict:
        """Set HSV: hue 0–360 degrees, saturation 0–100%, brightness/value 1–100%."""
        value = Color(hue=hue, saturation=saturation, brightness=brightness)
        return await self._command(room_id, device_id, "change_color",
            value.hue, value.saturation, value.brightness,
        )
