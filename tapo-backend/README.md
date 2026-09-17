# Backend API + voice agent

Full request/response reference: [Tapo API](../docs/TAPO_API.md).

Run in WSL from `tapo-backend/`:

```bash
uv sync --locked
uv run python backend.py
```

The main asyncio loop owns bulb connections. Uvicorn runs
the HTTP API and Google ADK agent in a separate thread. API and agent tool calls
are dispatched to the main loop; a per-bulb lock serializes device commands.
Use one backend process per home (no Uvicorn workers or reload). Bulbs connect on
their first command, so an offline bulb does not prevent the API from starting.

Add these settings to `tapo-backend/.env` (keep real keys out of Git):

```dotenv
TAPO_USER=your-tapo-email
TAPO_PASS=your-tapo-password
OPENAI_API_KEY=your-openai-api-key
API_HOST=127.0.0.1
API_PORT=8000
CORS_ORIGINS=http://localhost:5173
```

Application endpoints require no authentication for this home-network deployment.
OpenAPI docs are at `http://localhost:8000/docs`.
The OpenAI key stays on the server. Without it, device endpoints still work and
agent endpoints return 503.
`CORS_ORIGINS` is a comma-separated list of permitted frontend origins.

## Rooms and devices

`HOME_CONFIG` points to the JSON inventory. For multiple bulbs, copy
`home.example.json`, edit
the rooms/devices, and set `HOME_CONFIG=home.json` in `tapo-backend/.env`.
Relative config paths are resolved from the `tapo-backend/` directory. Each device has a
unique host and a room-local ID. All bulbs use the
configured Tapo account. Restart after editing inventory; no database is needed.

`GET /rooms` returns nested rooms and devices for the UI selectors, without hosts
or credentials. This is an inventory, not a live device-state report.

`GET /rooms/{room_id}/devices/{device_id}/status` refreshes the bulb and returns
its power, brightness, HSV, and color temperature. Read it when selecting a
device and after commands; an unreachable bulb returns 502, not an off state.

## Device endpoints

All four actions use `POST /rooms/{room_id}/devices/{device_id}/...`:

| Suffix | JSON body |
| --- | --- |
| `on` | None |
| `off` | None |
| `color` | `{"hue":180,"saturation":100,"brightness":80}` |
| `brightness` | `{"brightness":50}` |

HSV hue is 0â€“360 degrees, saturation is 0â€“100%, and value (`brightness`) is
1â€“100%. Values must be integers; use `off` for zero brightness. Success returns
`{"status":"ok","room_id":"office","device_id":"light"}`. It means the
device operation completed, not a live-state snapshot. Unknown targets return
404, invalid values 422, and device/AI failures 502. Do not automatically retry
502 responses: an action may have completed before a later step failed.

```bash
curl http://localhost:8000/rooms
curl -X POST \
  http://localhost:8000/rooms/office/devices/light/on
curl -X POST \
  -H 'Content-Type: application/json' -d '{"brightness":50}' \
  http://localhost:8000/rooms/office/devices/light/brightness
```

## Push-to-talk agent

`POST /agent/voice?room_id=office&device_id=light&speak=true` accepts the raw
recorded audio body (not multipart), with its audio `Content-Type`. Supported
containers: WebM, WAV, MP3, MP4, and Ogg; maximum request audio size is 10 MiB.
The browser records with `MediaRecorder` and sends the resulting Blob when the
user releases/stops recording. Microphone access requires localhost or HTTPS.

```javascript
const response = await fetch(
  `${apiUrl}/agent/voice?room_id=office&device_id=light&speak=true`,
  {
    method: "POST",
    headers: { "Content-Type": recording.type },
    body: recording, // Blob from MediaRecorder
  },
);
const result = await response.json();
if (!response.ok) throw new Error(result.detail);
// Display result.transcript and result.reply.
if (result.audio_base64) {
  await new Audio(`data:${result.audio_type};base64,${result.audio_base64}`).play();
}
```

Flow: OpenAI transcription â†’ Google ADK with OpenAI/LiteLLM â†’ shared light tools
â†’ optional OpenAI speech. The response contains `transcript` and `reply`; setting
`speak=true` adds `audio_base64` and `audio_type`. Speech is off by default. If TTS
fails after a command completes, the response retains the transcript/reply and
includes `audio_error`, so the UI need not repeat the command. Label generated
speech as AI-generated in the UI.

`POST /agent/message` also accepts text:
`{"message":"Make this light blue","room_id":"office","device_id":"light"}`.
Room/device selection is optional context, never a restriction; an explicit spoken
target takes precedence. The stateless agent does not ask follow-up questions. It
infers the most likely configured target using explicit names/IDs, unique inventory
matches, the selected target, and finally the first configured light. If it must
choose between several targets, it states which target it used. Device selection
requires a room. Each request is an independent turn; conversation history is not
persisted.

Optional server settings: `AGENT_MODEL=openai/gpt-4o-mini`,
`TRANSCRIPTION_MODEL=gpt-4o-mini-transcribe`, `TTS_MODEL=gpt-4o-mini-tts`,
`TTS_VOICE=alloy`. These use the OpenAI API and require API billing/model access.

References: [ADK LiteLLM](https://adk.dev/agents/models/litellm/),
[OpenAI transcription](https://developers.openai.com/api/docs/guides/speech-to-text),
[OpenAI speech](https://developers.openai.com/api/docs/guides/text-to-speech).

## Checks and container

```bash
uv run python -m unittest -v test_backend
docker build -t smart-home-tapo-backend .
docker run --rm --network host --env-file .env smart-home-tapo-backend
```

Checks use simulated devices/model/audio; they do not operate your lights or make
paid AI requests. The image starts `backend.py`, exposes port 8000, and binds to
`0.0.0.0` unless overridden. For custom inventory, mount your JSON read-only and
set `HOME_CONFIG` to its absolute container path. Add an HTTP Service to the
existing Kubernetes deployment when you want to expose the API there.
No deployment is performed by these changes.

Docker:
```bash
source .env
cd tapo-backend/

docker run --rm --network host --env KASA_USERNAME=$TAPO_USER --env KASA_PASSWORD=$TAPO_PASS kasa-cli kasa --host 192.168.1.20 state
docker run --rm --network host --env KASA_USERNAME=$TAPO_USER --env KASA_PASSWORD=$TAPO_PASS kasa-cli kasa --host 192.168.1.20 on
docker run --rm --network host --env KASA_USERNAME=$TAPO_USER --env KASA_PASSWORD=$TAPO_PASS kasa-cli kasa --host 192.168.1.20 off
```

# Build image Subscriber for arm64 (Pi arch)
```bash
docker buildx build \
  --platform linux/arm64 \
  --tag ghcr.io/minhngo248/smart-home/tapo-backend:v0.0 \
  --push .
```
