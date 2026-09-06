import argparse
import asyncio
import logging
import os
import signal
from pathlib import Path
from typing import Any

import paho.mqtt.client as mqtt
from dotenv import load_dotenv
from kasa import Discover, Module


PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")

LOGGER = logging.getLogger(__name__)
LIGHT_TOPIC = "/home/office/light"


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

    async def connect(self) -> None:
        self.device = await Discover.discover_single(
            self.device_ip,
            username=self.username,
            password=self.password,
        )
        if self.device is None:
            raise RuntimeError(f"Could not discover a device at {self.device_ip}")
        LOGGER.info("Connected to %s (%s)", self.device_ip, self.device.model)

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

    async def set_power(self, desired: bool) -> None:
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
        await self.get_light_module().set_brightness(brightness)

    async def change_color(self, hue: int, saturation: int, brightness: int) -> None:
        await self.get_light_module().set_hsv(hue, saturation, brightness)


class MqttLightService:
    def __init__(
        self,
        broker: str,
        port: int,
        topic: str,
        controller: LightController,
        ca_path: Path,
    ) -> None:
        self.topic = topic
        self.controller = controller
        self._command_lock = asyncio.Lock()
        self._loop = asyncio.get_running_loop()
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.client.tls_set(ca_certs=str(ca_path))
        self.client.connect(broker, port)

    def start(self) -> None:
        LOGGER.info("Subscribing to MQTT topic %s", self.topic)
        self.client.loop_start()

    async def stop(self) -> None:
        self.client.disconnect()
        self.client.loop_stop()

    def _on_connect(self, client, userdata, flags, reason_code, properties) -> None:
        if reason_code.is_failure:
            LOGGER.error("MQTT connection failed: %s", reason_code)
            return
        LOGGER.info("Connected to MQTT broker; subscribing to %s", self.topic)
        client.subscribe(self.topic)

    def _on_message(self, client, userdata, message) -> None:
        command = message.payload.decode("utf-8", errors="replace")
        if command not in {"on", "off"}:
            LOGGER.warning("Ignoring unsupported payload on %s: %r", message.topic, command)
            return
        task = asyncio.run_coroutine_threadsafe(
            self._process_command(command == "on"), self._loop
        )
        task.add_done_callback(self._log_command_result)

    async def _process_command(self, desired: bool) -> None:
        async with self._command_lock:
            await self.controller.set_power(desired)

    def _log_command_result(self, future) -> None:
        try:
            future.result()
        except Exception:
            LOGGER.exception("Failed to process MQTT light command")


def required_environment(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Missing environment variable: {name}")
    return value


def resolve_ca_path(value: str) -> Path:
    ca_path = Path(value)
    if not ca_path.is_absolute():
        ca_path = PROJECT_ROOT / ca_path
    if not ca_path.is_file():
        raise RuntimeError(f"MQTT CA file does not exist: {ca_path}")
    return ca_path


async def main() -> None:
    args = parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    broker = required_environment("MQTT_BROKER")
    port = int(os.environ.get("MQTT_PORT", "30883"))
    topic = os.environ.get("MQTT_TOPIC", LIGHT_TOPIC)
    ca_path = resolve_ca_path(required_environment("MQTT_CA_PATH"))
    controller = LightController(
        required_environment("DEVICE_IP"),
        required_environment("TAPO_USER"),
        required_environment("TAPO_PASS"),
    )
    service = None
    try:
        await controller.connect()
        service = MqttLightService(broker, port, topic, controller, ca_path)
        service.start()
        stop_event = asyncio.Event()
        loop = asyncio.get_running_loop()
        for shutdown_signal in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(shutdown_signal, stop_event.set)
        await stop_event.wait()
    finally:
        if service is not None:
            await service.stop()
        await controller.disconnect()


if __name__ == "__main__":
    asyncio.run(main())