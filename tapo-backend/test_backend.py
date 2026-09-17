"""Offline checks: uv run python -m unittest -v test_backend."""

import asyncio
import base64
import os
import socket
import subprocess
import sys
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx

from api import MAX_AUDIO_BYTES, app
from home import Home, HomeService
from tapo_control import Module


class BackendTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.home = HomeService(Home.model_validate({"rooms": [
            {"id": "office", "name": "Office", "devices": [
                {"id": "light", "name": "Desk", "host": "192.0.2.1"},
                {"id": "other", "name": "Other", "host": "192.0.2.2"},
            ]},
            {"id": "bedroom", "name": "Bedroom", "devices": [
                {"id": "light", "name": "Bed", "host": "192.0.2.3"},
            ]},
        ]}), "fake", "fake")
        self.owner_thread = threading.get_ident()
        self.calls = []
        self.active = 0
        self.max_active = 0

        async def record(operation, *args):
            self.assertEqual(threading.get_ident(), self.owner_thread)
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            await asyncio.sleep(0.005)
            self.calls.append((operation, args))
            self.active -= 1

        async def on():
            await record("on")
            self.device.is_on = True

        async def off():
            await record("off")
            self.device.is_on = False

        self.light = SimpleNamespace(
            set_brightness=AsyncMock(side_effect=lambda value: None), set_hsv=AsyncMock(),
            has_feature=lambda name: True, brightness=40, color_temp=0,
            hsv=SimpleNamespace(hue=180, saturation=90, value=40),
        )
        async def set_brightness(value):
            await record("brightness", value)
        async def set_hsv(*args):
            await record("color", *args)
        self.light.set_brightness.side_effect = set_brightness
        self.light.set_hsv.side_effect = set_hsv
        self.device = SimpleNamespace(
            is_on=False, update=AsyncMock(), turn_on=AsyncMock(side_effect=on),
            turn_off=AsyncMock(side_effect=off), modules={Module.Light: self.light},
        )
        self.home.device("office", "light").device = self.device
        app.state.home = self.home
        app.state.agent = None
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://test",
        )

    async def asyncTearDown(self):
        await self.client.aclose()

    async def test_inventory_controls_and_validation(self):
        self.assertEqual((await self.client.get("/rooms")).status_code, 200)
        inventory = (await self.client.get("/rooms")).json()
        self.assertEqual(len(inventory["rooms"]), 2)
        self.assertNotIn("host", str(inventory))
        path = "/rooms/office/devices/light"
        for suffix, body in [("on", None), ("off", None),
                             ("brightness", {"brightness": 40}),
                             ("color", {"hue": 180, "saturation": 90, "brightness": 80})]:
            response = await self.client.post(f"{path}/{suffix}", json=body)
            self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.calls, [("on", ()), ("off", ()), ("brightness", (40,)),
                                      ("color", (180, 90, 80))])
        for value in [0, 101, True, 1.5, "50"]:
            self.assertEqual((await self.client.post(path + "/brightness", json={"brightness": value})).status_code, 422)
        self.assertEqual((await self.client.post(path + "/color", json={
            "hue": 361, "saturation": 80, "brightness": 50,
        })).status_code, 422)
        self.assertEqual((await self.client.post("/rooms/no/devices/light/on")).status_code, 404)
        self.light.set_brightness.side_effect = RuntimeError("private upstream detail")
        failed = await self.client.post(path + "/brightness", json={"brightness": 40})
        self.assertEqual(failed.status_code, 502)
        self.assertNotIn("private upstream detail", failed.text)

    async def test_live_status(self):
        path = "/rooms/office/devices/light/status"
        async def refresh():
            self.assertEqual(threading.get_ident(), self.owner_thread)
            self.device.is_on = True
            self.light.brightness = 75
            self.light.hsv.value = 75
        self.device.update.side_effect = refresh
        response = await self.client.get(path)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(response.json(), {
            "status": "ok", "room_id": "office", "device_id": "light", "is_on": True,
            "brightness": 75, "hsv": {"hue": 180, "saturation": 90, "value": 75},
            "color_temp": 0,
        })
        self.device.update.assert_awaited_once()
        self.device.turn_on.assert_not_awaited()
        self.device.update.side_effect = None
        self.device.is_on = False
        self.light.has_feature = lambda name: name == "brightness"
        state = (await self.client.get(path)).json()
        self.assertFalse(state["is_on"])
        self.assertEqual(state["brightness"], 75)
        self.assertIsNone(state["hsv"])
        self.assertIsNone(state["color_temp"])
        controller = self.home.device("office", "light")
        controller.device = None
        async def connect():
            controller.device = self.device
        with patch.object(controller, "connect", AsyncMock(side_effect=connect)) as discover:
            self.assertEqual((await self.client.get(path)).status_code, 200)
            discover.assert_awaited_once()
        self.assertEqual((await self.client.get("/rooms/missing/devices/light/status")).status_code, 404)
        self.device.update.side_effect = RuntimeError("device unreachable")
        with self.assertLogs("api", level="ERROR"):
            response = await self.client.get(path)
        self.assertEqual(response.status_code, 502)
        self.assertNotIn("is_on", response.json())

    async def test_backend_thread_startup_and_shutdown(self):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        env = dict(os.environ, OPENAI_API_KEY="",
                   HOME_CONFIG="home.json", TAPO_USER="fake", TAPO_PASS="fake",
                   API_HOST="127.0.0.1", API_PORT=str(port))
        process = subprocess.Popen([sys.executable, "backend.py"], env=env,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        try:
            async with httpx.AsyncClient(timeout=1) as client:
                for _ in range(100):
                    try:
                        response = await client.get(f"http://127.0.0.1:{port}/rooms")
                        break
                    except httpx.ConnectError:
                        if process.poll() is not None:
                            self.fail(process.stderr.read().decode())
                        await asyncio.sleep(0.1)
                else:
                    self.fail("Backend failed to start")
            self.assertEqual(response.status_code, 200)
        finally:
            process.terminate()
            try:
                _, errors = await asyncio.to_thread(process.communicate, timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                await asyncio.to_thread(process.communicate)
                self.fail("Backend failed to shut down")
        self.assertEqual(process.returncode, 0, errors.decode())

    async def test_voice_transport(self):
        self.assertEqual((await self.client.post("/agent/message", json={"message": "hello"})).status_code, 503)
        agent = SimpleNamespace(voice=AsyncMock(return_value={"transcript": "hello", "reply": "Hi"}),
                                reply=AsyncMock(return_value="Hi"))
        app.state.agent = agent
        response = await self.client.post("/agent/voice?room_id=office&device_id=light&speak=true",
                                          content=b"fake-audio", headers={"Content-Type": "audio/webm;codecs=opus"})
        self.assertEqual(response.status_code, 200)
        agent.voice.assert_awaited_once_with(b"fake-audio", "webm", True, "office", "light")
        for data, mime, expected in [(b"", "audio/webm", 422), (b"x", "text/plain", 415),
                                      (b"x" * (MAX_AUDIO_BYTES + 1), "audio/webm", 413)]:
            response = await self.client.post("/agent/voice", content=data, headers={"Content-Type": mime})
            self.assertEqual(response.status_code, expected)
        self.assertEqual((await self.client.post("/agent/voice?device_id=light",
                         content=b"x", headers={"Content-Type": "audio/webm"})).status_code, 422)
        self.assertEqual((await self.client.post("/agent/message", json={"message": " "})).status_code, 422)

    async def test_adk_tool_roundtrip_and_audio_pipeline(self):
        # Real ADK runner, with a scripted model: no API charges or physical bulb access.
        from agent import HomeAgent
        from google.adk.models.base_llm import BaseLlm
        from google.adk.models.llm_response import LlmResponse
        from google.genai import types

        class ScriptedModel(BaseLlm):
            model: str = "offline"
            async def generate_content_async(self, llm_request, stream=False):
                has_result = any(p.function_response for c in llm_request.contents for p in c.parts or [])
                part = (types.Part(text="Light turned on.") if has_result else
                        types.Part(function_call=types.FunctionCall(name="turn_on", args={
                            "room_id": "office", "device_id": "light",
                        })))
                yield LlmResponse(content=types.Content(role="model", parts=[part]))

        with patch.dict(os.environ, {"OPENAI_API_KEY": "offline-test"}):
            agent = HomeAgent(self.home)
        self.assertIn("do not ask follow-up questions", agent.runner.agent.instruction)
        self.assertIn("selected room/device is context, never a restriction", agent.runner.agent.instruction)
        agent.runner.agent.model = ScriptedModel()
        try:
            self.assertEqual(await agent.reply("Turn on office light"), "Light turned on.")
            self.assertIn(("on", ()), self.calls)
            sessions = await agent.sessions.list_sessions(app_name="smart_home", user_id="local")
            self.assertEqual(sessions.sessions, [])
            with patch.object(agent.audio.audio.transcriptions, "create", AsyncMock(
                return_value=SimpleNamespace(text="Turn on office light"),
            )), patch.object(agent.audio.audio.speech, "create", AsyncMock(
                return_value=SimpleNamespace(content=b"mp3"),
            )) as speech:
                result = await agent.voice(b"audio", "webm", True, "office", "light")
                self.assertEqual(base64.b64decode(result["audio_base64"]), b"mp3")
                speech.side_effect = RuntimeError("TTS offline")
                result = await agent.voice(b"audio", "webm", True, "office", "light")
                self.assertEqual(result["reply"], "Light turned on.")
                self.assertIn("audio_error", result)
        finally:
            await agent.close()


if __name__ == "__main__":
    unittest.main()
