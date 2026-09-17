"""One push-to-talk turn: transcription, ADK tools, optional spoken reply."""

import base64
import json
import logging
import os

from google.adk.agents import LlmAgent
from google.adk.agents.run_config import RunConfig
from google.adk.models.lite_llm import LiteLlm
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from openai import AsyncOpenAI

from home import HomeService

LOGGER = logging.getLogger(__name__)


class HomeAgent:
    def __init__(self, home: HomeService):
        self.home = home
        self.audio = AsyncOpenAI(timeout=60, max_retries=0)
        self.sessions = InMemorySessionService()
        self.runner = Runner(
            app_name="smart_home", session_service=self.sessions,
            agent=LlmAgent(
                name="home_assistant",
                model=LiteLlm(model=os.getenv("AGENT_MODEL", "openai/gpt-4o-mini")),
                instruction=(
                    "You control the configured home lights. Use tools to make changes. "
                    "Never claim a change succeeded unless the tool returned status ok. "
                    "This is a stateless request-response assistant: do not ask follow-up "
                    "questions. Infer the intended action and target and proceed. "
                    "Resolve targets in this order: explicit room/device name or ID, a "
                    "unique match in the inventory, the selected room/device, then the "
                    "first configured light. The selected room/device is context, never "
                    "a restriction; an explicit target in the request always takes precedence. "
                    "Use only IDs in the inventory. If several targets remain, choose the "
                    "most likely one and state which target you used in the reply. "
                    "Do not infer device state from the inventory. Keep replies concise. "
                    "HSV brightness is value, in percent; use turn_off for zero brightness. "
                    "Inventory: " + home.home.model_dump_json()
                ),
                tools=[home.turn_on, home.turn_off, home.change_color, home.change_brightness],
            ),
        )

    async def reply(self, message: str, room_id: str | None = None,
                    device_id: str | None = None) -> str:
        if device_id is not None:
            self.home.device(room_id, device_id)
        elif room_id is not None and not any(r.id == room_id for r in self.home.home.rooms):
            raise LookupError("Unknown room")
        # ponytail: independent turns; persist user-owned sessions when follow-ups are needed.
        session = await self.sessions.create_session(app_name="smart_home", user_id="local")
        try:
            final = ""
            content = json.dumps({"selected_room_id": room_id,
                                  "selected_device_id": device_id, "message": message})
            async for event in self.runner.run_async(
                user_id="local", session_id=session.id,
                new_message=types.Content(role="user", parts=[types.Part(text=content)]),
                run_config=RunConfig(max_llm_calls=8),
            ):
                if event.is_final_response() and event.content:
                    final = "".join(part.text or "" for part in event.content.parts or [])
            if not final:
                raise RuntimeError("The agent did not return a reply")
            return final
        finally:
            await self.sessions.delete_session(
                app_name="smart_home", user_id="local", session_id=session.id,
            )

    async def voice(self, data: bytes, extension: str, speak: bool,
                    room_id: str | None, device_id: str | None) -> dict:
        transcription = await self.audio.audio.transcriptions.create(
            model=os.getenv("TRANSCRIPTION_MODEL", "gpt-4o-mini-transcribe"),
            file=(f"recording.{extension}", data),
        )
        transcript = transcription.text.strip()
        if not transcript:
            raise ValueError("No speech was transcribed")
        reply = await self.reply(transcript, room_id, device_id)
        result = {"transcript": transcript, "reply": reply}
        if speak:
            try:
                speech = await self.audio.audio.speech.create(
                    model=os.getenv("TTS_MODEL", "gpt-4o-mini-tts"),
                    voice=os.getenv("TTS_VOICE", "alloy"), input=reply,
                    response_format="mp3",
                )
                result.update(audio_base64=base64.b64encode(speech.content).decode(),
                              audio_type="audio/mpeg")
            except Exception:
                LOGGER.exception("Speech generation failed after the agent completed")
                result["audio_error"] = "Speech unavailable; the command was already processed."
        return result

    async def close(self):
        await self.audio.close()
