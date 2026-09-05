# Commands
```bash
uv run python tapo_control.py
uv run python tapo_control.py --debug
```

The service subscribes to `MQTT_TOPIC` (default `/home/office/light`) on
`MQTT_BROKER` and accepts only the payloads `on` and `off`. It requires
`DEVICE_IP`, `TAPO_USER`, and `TAPO_PASS`. `MQTT_PORT` defaults to `30883`.
Set `MQTT_CA_PATH` to a CA certificate to use a secure MQTT connection. Leave
it empty or unset to use a non-secure MQTT connection. Relative paths are
resolved from the project root.

For the container, use `/app/certs/ca.crt`, which is copied into the image.

Docker:
```bash
source .env
cd subscriber/

docker run --rm --network host --env KASA_USERNAME=$TAPO_USER --env KASA_PASSWORD=$TAPO_PASS kasa-cli kasa --host 192.168.1.20 state
docker run --rm --network host --env KASA_USERNAME=$TAPO_USER --env KASA_PASSWORD=$TAPO_PASS kasa-cli kasa --host 192.168.1.20 on
docker run --rm --network host --env KASA_USERNAME=$TAPO_USER --env KASA_PASSWORD=$TAPO_PASS kasa-cli kasa --host 192.168.1.20 off
```

# Build image Subscriber for arm64 (Pi arch)
```bash
docker buildx build \
  --platform linux/arm64 \
  --tag ghcr.io/minhngo248/smart-home/mqtt-subscriber:v0.0 \
  --push .
```