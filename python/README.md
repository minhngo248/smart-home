# Commands
```bash
uv run python tapo_control.py turn-on
uv run python tapo_control.py turn-off
uv run python tapo_control.py brightness 50
uv run python tapo_control.py color 180 100 80
```

Docker:
```bash
source .env
cd python/

docker run --rm --network host --env KASA_USERNAME=$TAPO_USER --env KASA_PASSWORD=$TAPO_PASS kasa-cli kasa --host 192.168.1.156 state
docker run --rm --network host --env KASA_USERNAME=$TAPO_USER --env KASA_PASSWORD=$TAPO_PASS kasa-cli kasa --host 192.168.1.156 on
docker run --rm --network host --env KASA_USERNAME=$TAPO_USER --env KASA_PASSWORD=$TAPO_PASS kasa-cli kasa --host 192.168.1.156 off
```