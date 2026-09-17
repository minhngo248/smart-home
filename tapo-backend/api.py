"""HTTP API for UI buttons and push-to-talk voice control."""

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

from home import Brightness, Color, Id

LOGGER = logging.getLogger(__name__)
MAX_AUDIO_BYTES = 10 * 1024 * 1024
AUDIO_TYPES = {"audio/webm": "webm", "audio/wav": "wav", "audio/x-wav": "wav",
               "audio/mpeg": "mp3", "audio/mp4": "mp4", "audio/ogg": "ogg"}


class AgentMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(min_length=1, max_length=8000)
    room_id: Id | None = None
    device_id: Id | None = None

    @model_validator(mode="after")
    def validate_selection(self):
        if not self.message.strip():
            raise ValueError("Message must not be blank")
        if self.device_id is not None and self.room_id is None:
            raise ValueError("device_id requires room_id")
        return self


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.agent = None
    try:
        if os.getenv("OPENAI_API_KEY"):
            from agent import HomeAgent
            app.state.agent = HomeAgent(app.state.home)
        yield
    finally:
        if app.state.agent is not None:
            await app.state.agent.close()


app = FastAPI(title="Smart home", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[s.strip() for s in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")
                   if s.strip()],
    allow_methods=["GET", "POST"], allow_headers=["Content-Type"],
)


@app.exception_handler(LookupError)
async def not_found(request, error):
    return JSONResponse(status_code=404, content={"detail": str(error)})


@app.exception_handler(ValueError)
async def invalid_value(request, error):
    return JSONResponse(status_code=422, content={"detail": "Invalid command values"})


@app.exception_handler(Exception)
async def upstream_failure(request, error):
    LOGGER.error("Request failed", exc_info=(type(error), error, error.__traceback__))
    return JSONResponse(status_code=502, content={
        "detail": "Device or AI service failed. A command may already have run; do not retry automatically.",
    })


@app.get("/rooms")
async def rooms(request: Request):
    return request.app.state.home.home.model_dump()


@app.get("/rooms/{room_id}/devices/{device_id}/status")
async def device_status(request: Request, response: Response, room_id: str, device_id: str):
    response.headers["Cache-Control"] = "no-store"
    return await request.app.state.home.get_status(room_id, device_id)


@app.post("/rooms/{room_id}/devices/{device_id}/on")
async def turn_on(request: Request, room_id: str, device_id: str):
    return await request.app.state.home.turn_on(room_id, device_id)


@app.post("/rooms/{room_id}/devices/{device_id}/off")
async def turn_off(request: Request, room_id: str, device_id: str):
    return await request.app.state.home.turn_off(room_id, device_id)


@app.post("/rooms/{room_id}/devices/{device_id}/color")
async def color(request: Request, room_id: str, device_id: str, body: Color):
    return await request.app.state.home.change_color(room_id, device_id, **body.model_dump())


@app.post("/rooms/{room_id}/devices/{device_id}/brightness")
async def brightness(request: Request, room_id: str, device_id: str, body: Brightness):
    return await request.app.state.home.change_brightness(room_id, device_id, body.brightness)


def agent_for(request: Request):
    if request.app.state.agent is None:
        raise HTTPException(503, "Set OPENAI_API_KEY to enable the agent")
    return request.app.state.agent


@app.post("/agent/message")
async def message(request: Request, body: AgentMessage):
    agent = agent_for(request)
    return {"reply": await agent.reply(body.message, body.room_id, body.device_id)}


@app.post("/agent/voice")
async def voice(request: Request, room_id: Id | None = None,
                device_id: Id | None = None, speak: bool = False):
    agent = agent_for(request)
    if device_id is not None:
        if room_id is None:
            raise HTTPException(422, "device_id requires room_id")
        request.app.state.home.device(room_id, device_id)
    elif room_id is not None and not any(r.id == room_id for r in request.app.state.home.home.rooms):
        raise HTTPException(404, "Unknown room")
    content_type = request.headers.get("content-type", "").split(";", 1)[0].lower()
    if content_type not in AUDIO_TYPES:
        raise HTTPException(415, "Send raw WebM, WAV, MP3, MP4, or Ogg audio")
    data = bytearray()
    async for chunk in request.stream():
        if len(data) + len(chunk) > MAX_AUDIO_BYTES:
            raise HTTPException(413, "Recording exceeds 10 MiB")
        data.extend(chunk)
    if not data:
        raise HTTPException(422, "Recording is empty")
    return await agent.voice(bytes(data), AUDIO_TYPES[content_type], speak, room_id, device_id)
