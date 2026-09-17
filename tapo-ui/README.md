# Smart home UI

Streamlit frontend for the [Tapo API](../docs/TAPO_API.md).
Select a room and light, view live status, apply power/brightness/HSV changes,
or send text and recorded voice commands with optional spoken replies.

The UI loads its settings from `tapo-ui/.env`, which is ignored by Git.
Copy `.env.sample` to create it:

```bash
cp .env.sample .env
```

Currently the only required UI setting is:

```dotenv
TAPO_API_URL=http://localhost:8000
```

The UI fails at startup with `Missing environment variable: TAPO_API_URL`
if this setting is absent. This matches the backend's required environment
handling and avoids silently sending commands to the wrong default host.

Shell environment variables take precedence over `.env`, so one-off overrides
are also supported.

## Run in WSL

Start the backend in one terminal:

```bash
cd tapo-backend
uv run python backend.py
```

Start the UI in another terminal:

```bash
cd tapo-ui
uv sync --locked
uv run streamlit run app.py
```

Build and run the minimal runtime image:

```bash
docker build -t smart-home-ui .
docker run --rm --network host \
  -e TAPO_API_URL=http://127.0.0.1:8000 smart-home-ui
```

The image uses a build-only `uv` stage, copies only the locked virtualenv and
runtime app files, and runs Streamlit as UID/GID `10001` without a login shell.
The UI configuration is supplied through `TAPO_API_URL`; `.env` is excluded
from the build context. In Kubernetes, set that variable to the backend Service
URL, for example `http://smart-home-subscriber:8000`.

Open **http://localhost:8501**. The UI defaults to `http://localhost:8000` for the
backend. To use another backend, set `TAPO_API_URL` in `.env` or the UI
process environment:

```bash
TAPO_API_URL=http://192.168.1.10:8000 uv run streamlit run app.py
```

Requests originate from the Streamlit server, not the browser. In a container,
use the backend's reachable service name/address instead of `localhost`.
The UI does not require an API token, OpenAI key, or Tapo credentials. Those
provider credentials stay in the backend. This UI loads only its own `.env`.

## Use

- Choose **Room**, then **Device** in the sidebar. **Reload rooms** refreshes inventory.
- Status loads on first device selection; use **Refresh status** for another read.
  Unavailable state is not shown as off.
- **Turn on/off** sends immediately. Brightness and HSV forms send only when
  **Apply** is clicked, so dragging sliders does not flood the device with commands.
  Refreshing status does not overwrite edits in the forms.
- Send a text command, or record with the microphone, stop, then **Send recording**.
  Recordings are WAV and limited to 10 MiB. Enable **Include a spoken reply** to
  display an audio player; click play to listen to the AI-generated voice.
- Each agent request includes the selected room/device as context. Explicitly
  naming another device overrides that context. The backend does not ask follow-up
  questions: it infers a target and says which one it used when needed. Only the
  last result is shown; every command is independent and has no conversation history.
- Commands are never automatically retried. A failed request may already have
  changed a light; refresh status before repeating it. Recordings are cleared
  after submission, including failures, to avoid accidental replay on reruns.

Browser microphone capture works on localhost; your planned HTTPS ingress will
cover access from other devices. No ingress or TLS configuration is included here.

## Offline checks

```bash
uv run python -m unittest -v test_app
```

Uses Streamlit AppTest with a mocked backend. Checks room/device targeting,
light controls, text/voice requests, rerun behavior, empty/offline inventory, and
upload/error handling without touching real lights or making paid AI calls.
Microphone permission, actual recording, and speaker playback require a browser
check with the running backend.
