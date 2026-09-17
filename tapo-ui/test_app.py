"""Offline UI checks: uv run python -m unittest -v test_app."""

import base64
import io
import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import requests
from streamlit.testing.v1 import AppTest

os.environ.setdefault("TAPO_API_URL", "http://localhost:8000")
from app import MAX_AUDIO_BYTES, api, send_voice


class UiTest(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.offline = False
        self.state = {"is_on": False, "brightness": 40,
                      "hsv": {"hue": 180, "saturation": 90, "value": 40}, "color_temp": 0}
        self.inventory = {"rooms": [
            {"id": "office", "name": "Office", "devices": [
                {"id": "light", "name": "Desk", "type": "light"}]},
            {"id": "bedroom", "name": "Bedroom", "devices": [
                {"id": "bed", "name": "Bed light", "type": "light"}]},
        ]}
        self.mock = patch("requests.request", side_effect=self.respond)
        self.mock.start()
        self.addCleanup(self.mock.stop)

    def respond(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if self.offline:
            raise requests.ConnectionError("offline")
        if url.endswith("/rooms"):
            data = self.inventory
        elif url.endswith("/status"):
            data = self.state.copy()
        elif "/agent/" in url:
            data = {"transcript": "Turn it on", "reply": "Light is on.",
                    "audio_base64": base64.b64encode(b"fake-mp3").decode(), "audio_type": "audio/mpeg"}
        else:
            action = url.rsplit("/", 1)[-1]
            if action in ("on", "off"):
                self.state["is_on"] = action == "on"
            elif action == "brightness":
                self.state["brightness"] = kwargs["json"]["brightness"]
            data = {"status": "ok"}
        return SimpleNamespace(ok=True, status_code=200, json=lambda: data)

    def app(self):
        return AppTest.from_file(str(Path(__file__).with_name("app.py")), default_timeout=15).run()

    def button(self, app, label):
        return next(button for button in app.button if button.label == label)

    def posts(self):
        return [call for call in self.calls if call[0] == "POST"]

    def test_selection_controls_and_reruns(self):
        app = self.app()
        self.assertFalse(app.exception)
        self.assertEqual(app.metric[0].value, "Off")
        self.assertFalse(self.posts())
        self.button(app, "Turn on").click().run()
        self.assertEqual(app.metric[0].value, "On")
        app.run()
        self.assertEqual(len(self.posts()), 1)
        app.slider(key="brightness").set_value(65)
        self.button(app, "Apply brightness").click().run()
        self.assertEqual(self.posts()[-1][2]["json"], {"brightness": 65})
        app.slider(key="hue").set_value(240)
        app.slider(key="saturation").set_value(80)
        app.slider(key="value").set_value(60)
        self.button(app, "Apply color").click().run()
        self.assertEqual(self.posts()[-1][2]["json"], {"hue": 240, "saturation": 80, "brightness": 60})
        app.selectbox[0].select("bedroom").run()
        self.button(app, "Turn off").click().run()
        self.assertTrue(self.posts()[-1][1].endswith("/rooms/bedroom/devices/bed/off"))
        self.assertFalse(app.exception)

    def test_text_and_voice_send_once(self):
        app = self.app()
        app.text_area[0].set_value("Turn on this light")
        self.button(app, "Send message").click().run()
        self.assertEqual(self.posts()[-1][2]["json"], {
            "message": "Turn on this light", "room_id": "office", "device_id": "light",
        })
        app.run()
        self.assertEqual(len(self.posts()), 1)
        # AppTest has no microphone driver; supply the same BytesIO interface as audio_input.
        with patch("streamlit.audio_input", return_value=io.BytesIO(b"wav-recording")):
            app.run()
            self.button(app, "Send recording").click().run()
            voice = self.posts()[-1]
            self.assertTrue(voice[1].endswith("/agent/voice"))
            self.assertEqual(voice[2]["data"], b"wav-recording")
            self.assertEqual(voice[2]["headers"], {"Content-Type": "audio/wav"})
            self.assertEqual(voice[2]["params"], {"room_id": "office", "device_id": "light", "speak": "true"})
            app.run()
            self.assertEqual(len(self.posts()), 2)
        self.assertFalse(app.exception)

    def test_empty_and_unavailable_home(self):
        self.inventory = {"rooms": []}
        app = self.app()
        self.assertIn("No rooms", app.info[0].value)
        self.offline = True
        app.run()
        self.assertIn("Cannot reach", app.error[0].value)
        self.assertFalse(app.exception)
        self.assertFalse(self.posts())

    def test_voice_limits_and_api_errors(self):
        for data in (b"", b"x" * (MAX_AUDIO_BYTES + 1)):
            with self.assertRaises(RuntimeError):
                send_voice(io.BytesIO(data), "office", "light", False)
        self.assertFalse(self.calls)
        with patch("requests.request", return_value=SimpleNamespace(
            ok=False, status_code=422, json=lambda: {"detail": [{"msg": "Invalid brightness"}]},
        )):
            with self.assertRaisesRegex(RuntimeError, "Invalid brightness"):
                api("POST", "/test")
        self.offline = True
        with self.assertRaisesRegex(RuntimeError, "may have run"):
            api("POST", "/test")
        self.assertEqual(len(self.posts()), 1)

    def test_device_recovery_and_failed_voice_not_replayed(self):
        original = self.respond
        def unavailable(method, url, **kwargs):
            if url.endswith("/status"):
                raise requests.ConnectionError("bulb offline")
            return original(method, url, **kwargs)
        with patch("requests.request", side_effect=unavailable):
            app = self.app()
            self.assertIn("Device status unavailable", app.error[0].value)
            self.assertEqual(len(app.slider), 0)
        self.button(app, "Refresh status").click().run()
        self.assertEqual(len(app.slider), 4)
        self.assertFalse(app.exception)
        voice_calls = []
        def voice_failure(method, url, **kwargs):
            if url.endswith("/agent/voice"):
                voice_calls.append(url)
                raise requests.Timeout("voice timed out")
            return original(method, url, **kwargs)
        with patch("requests.request", side_effect=voice_failure), patch(
            "streamlit.audio_input", return_value=io.BytesIO(b"wav"),
        ):
            app.run()
            self.button(app, "Send recording").click().run()
            self.assertIn("may have run", app.error[0].value)
            app.run()
            self.assertEqual(len(voice_calls), 1)
            self.assertFalse(app.exception)


if __name__ == "__main__":
    unittest.main()
