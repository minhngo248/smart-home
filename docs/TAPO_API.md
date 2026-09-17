# Tapo Backend API

HTTP API for room/device selection, live bulb status, light controls, and the
push-to-talk agent.

## Connection

- Local base URL: `http://localhost:8000` (no `/api` prefix).
- No authentication or Authorization header is required.
- JSON request bodies use `Content-Type: application/json`.
- Responses are JSON, including voice responses with optional base64 audio.
- Interactive documentation: `/docs`; OpenAPI schema: `/openapi.json`.
- `API_HOST` defaults to `127.0.0.1`; set `API_HOST=0.0.0.0` to listen on the
  home network and use the backend machine's address from another device.
- `API_PORT` defaults to `8000`. `CORS_ORIGINS` lists allowed browser origins,
  comma-separated; its default is `http://localhost:5173`.

Start in WSL with `cd tapo-backend && uv run python backend.py`. See the backend
README for environment and container settings.

## Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/rooms` | Configured rooms and devices |
| GET | `/rooms/{room_id}/devices/{device_id}/status` | Fresh device state |
| POST | `/rooms/{room_id}/devices/{device_id}/on` | Turn on |
| POST | `/rooms/{room_id}/devices/{device_id}/off` | Turn off |
| POST | `/rooms/{room_id}/devices/{device_id}/color` | Set HSV color |
| POST | `/rooms/{room_id}/devices/{device_id}/brightness` | Set brightness |
| POST | `/agent/message` | Send a text command |
| POST | `/agent/voice` | Send a recorded voice command |

Use IDs from `/rooms`, not display names. Room IDs are unique; device IDs are
unique within their room. IDs are case-sensitive and contain 1–64 letters,
digits, underscores, or hyphens.

## Inventory: GET /rooms

No request body. Example `200 OK`:

```json
{
  "rooms": [
    {
      "id": "office",
      "name": "Office",
      "devices": [
        {"id": "light", "name": "Desk light", "type": "light"}
      ]
    }
  ]
}
```

This returns configuration without contacting the bulbs. Hosts, credentials, and
A listed device is not necessarily online.

Devices are registered in the JSON file selected by `HOME_CONFIG`, not through an
HTTP endpoint. Relative paths resolve from the repository root. Copy
[`home.example.json`](../tapo-backend/home.example.json), edit rooms/devices, set
`HOME_CONFIG=home.json`, and restart. All bulbs use the configured Tapo account.

## Live state: GET /rooms/{room_id}/devices/{device_id}/status

```bash
curl http://localhost:8000/rooms/office/devices/light/status
```

Example `200 OK`, with `Cache-Control: no-store`:

```json
{
  "status": "ok",
  "room_id": "office",
  "device_id": "light",
  "is_on": true,
  "brightness": 75,
  "hsv": {"hue": 180, "saturation": 90, "value": 75},
  "color_temp": 0
}
```

| Field | Meaning |
| --- | --- |
| `status` | `"ok"` means the read completed successfully |
| `is_on` | Boolean power state reported by the bulb |
| `brightness` | Reported brightness percentage, or `null` if unsupported |
| `hsv` | Hue in degrees, saturation and value in percent; `null` if unsupported |
| `color_temp` | Reported white color temperature in kelvin; `0` indicates color mode on the current Tapo bulb; `null` if unsupported |

Each call connects if needed and refreshes the bulb before returning. It does
not change its settings. An off bulb may still report its saved brightness/color;
use `is_on` for the power indicator. In white-temperature mode, HSV values may be
saved color settings rather than the emitted white color.

Unknown room/device: `404`. Device connection/read failure: `502`, with no state
snapshot. The UI should mark state unavailable or stale, not assume the bulb is
off. This endpoint does not return cached state as a successful live read.

## Light controls

All four controls return this shape on `200 OK`:

```json
{"status":"ok","room_id":"office","device_id":"light"}
```

This acknowledges completion of the device operation; it is not a state
snapshot. Read `/status` afterward for the actual state.

### POST /rooms/{room_id}/devices/{device_id}/on

No body. Turning on an already-on bulb succeeds without toggling it.

```bash
curl -X POST http://localhost:8000/rooms/office/devices/light/on
```

### POST /rooms/{room_id}/devices/{device_id}/off

No body. Turning off an already-off bulb succeeds without toggling it.

```bash
curl -X POST http://localhost:8000/rooms/office/devices/light/off
```

### POST /rooms/{room_id}/devices/{device_id}/color

All three fields are required integers. Hue: `0–360`; saturation: `0–100`;
brightness (HSV value): `1–100`. Unknown JSON fields are rejected.

```bash
curl -X POST http://localhost:8000/rooms/office/devices/light/color \
  -H 'Content-Type: application/json' \
  -d '{"hue":180,"saturation":100,"brightness":80}'
```

### POST /rooms/{room_id}/devices/{device_id}/brightness

`brightness` is a required integer from `1–100`. Use `/off` for explicit power
off. Strings, booleans, floating-point values, and unknown fields are rejected.

```bash
curl -X POST http://localhost:8000/rooms/office/devices/light/brightness \
  -H 'Content-Type: application/json' -d '{"brightness":50}'
```

## Text agent: POST /agent/message

```json
{
  "message": "Make this light blue",
  "room_id": "office",
  "device_id": "light"
}
```

- `message`: required, nonblank string, maximum 8,000 characters.
- `room_id`: optional selected room.
- `device_id`: optional selected device; requires `room_id`.
- Extra JSON fields are rejected.

Example `200 OK`:

```json
{"reply":"The office light is now blue."}
```

The stateless agent does not ask follow-up questions. It infers the target using
explicit room/device names or IDs, unique inventory matches, the selected target,
and finally the first configured light. An explicit user target always takes
precedence over the page selection. If several targets remain, the agent chooses
the most likely one and states which target it used. Requests are independent
turns: there is no persistent conversation/session ID or follow-up history.

## Push-to-talk: POST /agent/voice

Send a raw recording as the request body, not JSON or multipart/form-data.

| Query parameter | Default | Meaning |
| --- | --- | --- |
| `room_id` | Omitted | Selected room |
| `device_id` | Omitted | Selected device; requires `room_id` |
| `speak` | `false` | Set `true` to also generate spoken output |

Accepted Content-Types: `audio/webm`, `audio/wav`, `audio/x-wav`, `audio/mpeg`,
`audio/mp4`, `audio/ogg`. MIME parameters such as `;codecs=opus` are accepted.
Maximum recording size: **10 MiB (10,485,760 bytes)**. Empty recordings are rejected.

```bash
curl -X POST \
  'http://localhost:8000/agent/voice?room_id=office&device_id=light&speak=true' \
  -H 'Content-Type: audio/webm' --data-binary @recording.webm
```

Example `200 OK` with `speak=false`:

```json
{"transcript":"Turn on the office light","reply":"The office light is on."}
```

With successful speech generation, the response also contains:

```json
{"audio_base64":"<base64-encoded MP3 bytes>","audio_type":"audio/mpeg"}
```

If speech generation fails after the agent completes, the response remains `200`
and retains `transcript` and `reply`, with an `audio_error` string instead of audio.
Do not repeat the command just because speech failed. Display generated speech as
AI-generated in the UI. The browser's microphone requires localhost or HTTPS.

Both agent endpoints require server-side `OPENAI_API_KEY`; without it they return
`503`. The frontend never sends this key. Transcription, agent reasoning, and
speech use the configured server models. Device controls and status work without
an OpenAI key.

## Errors

| HTTP status | Meaning |
| --- | --- |
| `404` | Unknown room or device |
| `413` | Voice recording exceeds 10 MiB |
| `415` | Unsupported voice Content-Type |
| `422` | Invalid body/query/value, empty recording, or empty transcription |
| `502` | Device or AI service failure |
| `503` | Agent unavailable because no OpenAI key is configured |

Application errors use a string `detail`, for example:

```json
{"detail":"Unknown room or device"}
```

FastAPI request-validation errors use an array under `detail` with per-field
`loc`, `msg`, and `type` information. UI code should handle either form.

An action or agent request can fail after a device command already ran. Do not
automatically replay failed mutation requests. Refresh state first. A failed GET
status request is read-only and can be retried.

## Suggested UI flow

1. Fetch `/rooms` to populate room and device selectors.
2. Fetch the selected device's `/status` for the toggle, brightness, and color.
3. POST a button/slider change, then refresh `/status`.
4. Record while speaking, then send the Blob to `/agent/voice` on stop/release.
   Display the transcript/reply and play audio when present.
5. Refresh visible device statuses after agent requests, including failed requests
   that may already have changed a bulb. An agent may target a different device
   from the current selection; the reply identifies the chosen target when it had
   to infer one.
6. Status is read on initial device selection and when the user presses Refresh.
   There is no automatic polling, WebSocket/SSE state feed, or bulk-status endpoint.

HTTP runs in a separate thread. All bulb reads and writes are dispatched to the
backend loop and serialized per device, so UI refreshes do not overlap device
commands on the same bulb.
