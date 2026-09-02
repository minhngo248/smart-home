import asyncio
import argparse
import os
from pathlib import Path

from dotenv import load_dotenv
from kasa import Discover, Module


PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Control a Tapo L530E bulb")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("turn-off", help="Turn the bulb off")
    subparsers.add_parser("turn-on", help="Turn the bulb on")

    brightness = subparsers.add_parser("brightness", help="Set brightness from 1 to 100")
    brightness.add_argument("value", type=int, choices=range(1, 101))

    color = subparsers.add_parser("color", help="Set HSV color and brightness")
    color.add_argument("hue", type=int, choices=range(0, 361))
    color.add_argument("saturation", type=int, choices=range(0, 101))
    color.add_argument("brightness", type=int, choices=range(1, 101))
    return parser.parse_args()


async def turn_off(device) -> None:
    await device.turn_off()


async def turn_on(device) -> None:
    await device.turn_on()


def get_light_module(device):
    light = device.modules.get(Module.Light)
    if light is None:
        raise RuntimeError("The discovered device does not expose a light module")
    return light


async def change_brightness(device, brightness: int) -> None:
    await get_light_module(device).set_brightness(brightness)


async def change_color(device, hue: int, saturation: int, brightness: int) -> None:
    await get_light_module(device).set_hsv(hue, saturation, brightness)


async def verify_light_state(device) -> None:
    await device.update()
    light = get_light_module(device)
    print(f"Verified bulb state: is_on={device.is_on}")
    print(f"Light state: {light.state}")


async def main() -> None:
    args = parse_args()
    device_ip = os.environ.get("DEVICE_IP")
    tapo_user = os.environ.get("TAPO_USER")
    tapo_pass = os.environ.get("TAPO_PASS")

    missing = [
        name
        for name, value in (
            ("DEVICE_IP", device_ip),
            ("TAPO_USER", tapo_user),
            ("TAPO_PASS", tapo_pass),
        )
        if not value
    ]
    if missing:
        raise RuntimeError(f"Missing environment variables: {', '.join(missing)}")

    device = await Discover.discover_single(
        device_ip,
        username=tapo_user,
        password=tapo_pass,
    )
    if device is None:
        raise RuntimeError(f"Could not discover a device at {device_ip}")

    try:
        print(f"Connected to {device_ip} ({device.model})")
        await device.update()
        if args.command == "turn-off":
            await turn_off(device)
        elif args.command == "turn-on":
            await turn_on(device)
        elif args.command == "brightness":
            await change_brightness(device, args.value)
        elif args.command == "color":
            await change_color(device, args.hue, args.saturation, args.brightness)
        print(f"Command completed: {args.command}")
        await verify_light_state(device)
    finally:
        await device.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
