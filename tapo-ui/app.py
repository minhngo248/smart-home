"""Run with: uv run streamlit run app.py."""

import base64
import os
from datetime import datetime
from pathlib import Path

import requests
import streamlit as st
from dotenv import load_dotenv

load_dotenv(Path(__file__).with_name(".env"))


def required_environment(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing environment variable: {name}")
    return value


API_URL = required_environment("TAPO_API_URL").rstrip("/")
MAX_AUDIO_BYTES = 10 * 1024 * 1024


def api(method, path, *, timeout=15, **kwargs):
    """No retries: a failed mutation may already have changed a light."""
    try:
        response = requests.request(method, API_URL + path, timeout=(3, timeout), **kwargs)
    except requests.RequestException as error:
        message = "Cannot reach the home backend."
        if method == "POST":
            message += " The command may have run; check the light before sending again."
        raise RuntimeError(message) from error
    try:
        data = response.json()
    except ValueError as error:
        raise RuntimeError("The backend returned an unreadable response. Refresh status before retrying a command.") from error
    if not isinstance(data, dict):
        raise RuntimeError("The backend returned an unexpected response.")
    if not response.ok:
        detail = data.get("detail", "Request failed")
        if isinstance(detail, list):
            detail = "; ".join(item.get("msg", "Invalid value") for item in detail)
        raise RuntimeError(f"{response.status_code}: {detail}")
    return data


def send_voice(recording, room_id, device_id, speak):
    data = recording.getvalue()
    if not data:
        raise RuntimeError("Record a voice message first.")
    if len(data) > MAX_AUDIO_BYTES:
        raise RuntimeError("Recording exceeds 10 MiB. Please record a shorter message.")
    return api("POST", "/agent/voice", timeout=180, data=data,
               headers={"Content-Type": "audio/wav"},
               params={"room_id": room_id, "device_id": device_id,
                       "speak": str(speak).lower()})


def live_status(path):
    st.subheader("Live status")
    if st.button("Refresh status", key="refresh_status"):
        st.session_state.status_refresh = True
        st.session_state.reset_controls = True
    if st.session_state.get("status_target") != path or st.session_state.pop("status_refresh", False):
        try:
            st.session_state.live_state = api("GET", path + "/status")
            st.session_state.status_target = path
        except RuntimeError as error:
            st.session_state.live_state = None
            st.session_state.status_target = path
            st.error("Device status unavailable")
            st.caption(str(error))
            return
    state = st.session_state.get("live_state")
    if state is None:
        st.info("Press Refresh status to try again.")
        return
    power, brightness = st.columns(2)
    power.metric("Power", "On" if state["is_on"] else "Off")
    brightness.metric("Brightness", f'{state["brightness"]}%' if state["brightness"] is not None else "Unavailable")
    hsv, temperature = state.get("hsv"), state.get("color_temp")
    if temperature:
        st.caption(f"White light · {temperature} K")
    elif hsv is not None:
        st.caption(f'Color · {hsv["hue"]}° hue · {hsv["saturation"]}% saturation · {hsv["value"]}% value')
    if not state["is_on"]:
        st.caption("Brightness and color may show the bulb's saved settings while off.")
    st.caption(f"Updated {datetime.now():%H:%M:%S} · refreshes every 5 seconds")


def change_light(path, action, body=None):
    try:
        api("POST", path + "/" + action, json=body)
        st.session_state.notice = ("success", "Light command completed.")
    except RuntimeError as error:
        st.session_state.notice = ("error", str(error))
    st.session_state.reset_controls = True
    st.rerun()


def controls(path, target):
    state = st.session_state.get("live_state")
    st.subheader("Light controls")
    on, off = st.columns(2)
    if on.button("Turn on", use_container_width=True):
        change_light(path, "on")
    if off.button("Turn off", use_container_width=True):
        change_light(path, "off")
    if state is None:
        st.info("Refresh status to load brightness and color controls.")
        return
    hsv = state.get("hsv")
    reset = st.session_state.pop("reset_controls", False)
    if st.session_state.get("control_target") != target or reset:
        st.session_state.control_target = target
        st.session_state.brightness = max(1, min(100, state.get("brightness") or 100))
        st.session_state.hue = hsv["hue"] if hsv else 0
        st.session_state.saturation = hsv["saturation"] if hsv else 100
        st.session_state.value = max(1, min(100, hsv["value"])) if hsv else 100
    st.caption("Choose values, then apply. Live refresh does not overwrite your edits.")
    if state.get("brightness") is not None:
        with st.form("brightness_form"):
            brightness = st.slider("Brightness (%)", 1, 100, key="brightness")
            if st.form_submit_button("Apply brightness"):
                change_light(path, "brightness", {"brightness": brightness})
    if hsv is not None:
        with st.form("color_form"):
            hue = st.slider("Hue (degrees)", 0, 360, key="hue")
            saturation = st.slider("Saturation (%)", 0, 100, key="saturation")
            value = st.slider("Value / brightness (%)", 1, 100, key="value")
            if st.form_submit_button("Apply color"):
                change_light(path, "color", {"hue": hue, "saturation": saturation, "brightness": value})


def assistant(room_id, device_id, target_label):
    st.subheader("Home assistant")
    st.caption(f"Selected: {target_label}. Name another light to target it instead.")
    with st.form("message_form", clear_on_submit=True):
        message = st.text_area("Your command", placeholder="Set this light to 50 percent brightness", max_chars=8000)
        send_text = st.form_submit_button("Send message")
    if send_text:
        if not message.strip():
            st.warning("Enter a command first.")
        else:
            with st.spinner("Working on your command…"):
                try:
                    result = api("POST", "/agent/message", timeout=180,
                                 json={"message": message, "room_id": room_id, "device_id": device_id})
                    result["transcript"] = message
                except RuntimeError as error:
                    result = {"error": str(error)}
            st.session_state.agent_result = result
            st.session_state.agent_target = target_label
            st.session_state.reset_controls = True
            st.rerun()

    st.divider()
    st.caption("Record, stop, then send your voice command.")
    version = st.session_state.get("recording_version", 0)
    recording = st.audio_input("Voice command", key=f"recording_{room_id}_{device_id}_{version}")
    speak = st.checkbox("Include a spoken reply", value=True)
    if st.button("Send recording", disabled=recording is None):
        # Consume even failed submissions: reruns must never replay a voice command.
        st.session_state.recording_version = version + 1
        with st.spinner("Listening and working on your command…"):
            try:
                result = send_voice(recording, room_id, device_id, speak)
            except RuntimeError as error:
                result = {"error": str(error)}
        st.session_state.agent_result = result
        st.session_state.agent_target = target_label
        st.session_state.reset_controls = True
        st.rerun()

    if result := st.session_state.get("agent_result"):
        st.divider()
        st.caption(f'Last request · {st.session_state.agent_target}')
        if result.get("error"):
            st.error(result["error"])
        else:
            if result.get("transcript"):
                with st.chat_message("user"):
                    st.write(result["transcript"])
            with st.chat_message("assistant"):
                st.write(result["reply"])
                if result.get("audio_base64"):
                    st.caption("AI-generated voice")
                    try:
                        st.audio(base64.b64decode(result["audio_base64"], validate=True),
                                 format=result.get("audio_type", "audio/mpeg"))
                    except ValueError:
                        st.warning("The spoken reply could not be played. Read the response above.")
                if result.get("audio_error"):
                    st.warning(result["audio_error"])
    st.caption("Each command is independent. Include the details needed; previous messages are not remembered.")


def main():
    st.set_page_config(page_title="My home", page_icon="💡", layout="wide")
    st.title("My home")
    st.caption("Your rooms, your lights, your voice.")
    st.sidebar.header("Rooms & devices")
    st.sidebar.button("Reload rooms")
    try:
        rooms = api("GET", "/rooms")["rooms"]
    except RuntimeError as error:
        st.error(str(error))
        st.info("Start the subscriber backend, then reload this page.")
        return
    if not rooms:
        st.info("No rooms configured yet. Add a room and light to the home configuration.")
        return
    room_map = {r["id"]: r for r in rooms}
    room_id = st.sidebar.selectbox("Room", list(room_map), format_func=lambda key: room_map[key]["name"])
    devices = {d["id"]: d for d in room_map[room_id]["devices"]}
    if not devices:
        st.info("This room has no devices yet.")
        return
    device_id = st.sidebar.selectbox("Device", list(devices), key=f"device_{room_id}",
                                     format_func=lambda key: devices[key]["name"])
    label = f'{room_map[room_id]["name"]} / {devices[device_id]["name"]}'
    st.header(label)
    path = f"/rooms/{room_id}/devices/{device_id}"
    if notice := st.session_state.pop("notice", None):
        getattr(st, notice[0])(notice[1])
    lights, agent = st.columns([1, 1], gap="large")
    with lights:
        live_status(path)
        controls(path, (room_id, device_id))
    with agent:
        assistant(room_id, device_id, label)


if __name__ == "__main__":
    main()
