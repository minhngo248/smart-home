import argparse
import asyncio
import logging
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from kasa import Discover, Module


PROJECT_ROOT = Path(__file__).resolve().parent
load_dotenv(PROJECT_ROOT / ".env")

LOGGER = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Control a Tapo L530E bulb")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    return parser.parse_args()


class LightController:
    def __init__(self, device_ip: str, username: str, password: str) -> None:
        self.device_ip = device_ip
        self.username = username
        self.password = password
        self.device: Any = None
        self.command_lock = asyncio.Lock()

    async def connect(self) -> None:
        try:
            self.device = await Discover.discover_single(
                self.device_ip,
                username=self.username,
                password=self.password,
            )
            if self.device is None:
                raise RuntimeError(f"Could not discover a device at {self.device_ip}")
            LOGGER.info("Connected to %s (%s)", self.device_ip, self.device.model)
        except Exception as error:
            self.device = None
            LOGGER.error("Light connection failed: %s", error)
            raise RuntimeError(f"Light connection failed for {self.device_ip}") from error

    async def disconnect(self) -> None:
        if self.device is not None:
            await self.device.disconnect()
            self.device = None

    def get_light_module(self):
        if self.device is None:
            raise RuntimeError("The light controller is not connected")
        light = self.device.modules.get(Module.Light)
        if light is None:
            raise RuntimeError("The discovered device does not expose a light module")
        return light

    async def get_status(self) -> dict:
        async with self.command_lock:
            if self.device is None:
                await self.connect()
            await self.device.update()
            light = self.get_light_module()
            hsv = light.hsv if light.has_feature("hsv") else None
            return {
                "is_on": self.device.is_on,
                "brightness": light.brightness if light.has_feature("brightness") else None,
                "hsv": {"hue": hsv.hue, "saturation": hsv.saturation,
                        "value": hsv.value} if hsv is not None else None,
                "color_temp": light.color_temp if light.has_feature("color_temp") else None,
            }

    async def set_power(self, desired: bool) -> None:
        async with self.command_lock:
            if self.device is None:
                await self.connect()
            await self._set_power(desired)

    async def _set_power(self, desired: bool) -> None:
        if self.device is None:
            raise RuntimeError("The light controller is not connected")
        await self.device.update()
        current = self.device.is_on
        state = "on" if current else "off"
        target = "on" if desired else "off"
        LOGGER.debug("Current light state is %s; requested state is %s", state, target)
        if current == desired:
            LOGGER.error("Ignoring redundant %s command: light is already %s", target, state)
            return
        if desired:
            await self.device.turn_on()
        else:
            await self.device.turn_off()
        await self.device.update()
        LOGGER.info("Light turned %s; verified is_on=%s", target, self.device.is_on)

    async def change_brightness(self, brightness: int) -> None:
        if type(brightness) is not int or not 1 <= brightness <= 100:
            raise ValueError("Brightness must be an integer from 1 to 100")
        async with self.command_lock:
            if self.device is None:
                await self.connect()
            await self.get_light_module().set_brightness(brightness)

    async def change_color(self, hue: int, saturation: int, brightness: int) -> None:
        for name, value, low, high in (
            ("Hue", hue, 0, 360), ("Saturation", saturation, 0, 100),
            ("Brightness", brightness, 1, 100),
        ):
            if type(value) is not int or not low <= value <= high:
                raise ValueError(f"{name} must be an integer from {low} to {high}")
        async with self.command_lock:
            if self.device is None:
                await self.connect()
            await self.get_light_module().set_hsv(hue, saturation, brightness)


def required_environment(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Missing environment variable: {name}")
    return value

