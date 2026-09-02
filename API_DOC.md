# Tapo L530E Local API

This project controls a Tapo L530E over its local KLAP v2 protocol.
The bulb uses HTTP on port 80 and the following endpoints:

- `POST /app/handshake1`
- `POST /app/handshake2`
- `POST /app/request?seq=N`

## Authentication and session

### Phase 1: handshake1

Request body: 16 random bytes (`local_seed`).

Response body: 48 bytes:

```text
remote_seed (16 bytes) + SHA256(local_seed + remote_seed + auth_hash) (32 bytes)
```

For KLAP v2:

```text
user_hash     = SHA1(TAPO_USER)
password_hash = SHA1(TAPO_PASS)
auth_hash     = SHA256(user_hash + password_hash)
```

The response also sets the `TP_SESSIONID` cookie. The HTTP client must retain it.

### Phase 2: handshake2

Request body:

```text
SHA256(remote_seed + local_seed + auth_hash)
```

Send the `TP_SESSIONID` cookie from Phase 1.

### Session keys

```text
key    = SHA256("lsk" + local_seed + remote_seed + auth_hash)[0:16]
ivFull = SHA256("iv"  + local_seed + remote_seed + auth_hash)
sigKey = SHA256("ldk" + local_seed + remote_seed + auth_hash)[0:28]
iv     = ivFull[0:12]
seq    = signed big-endian integer from ivFull[28:32]
```

## Phase 3 encrypted request

Every command is JSON, padded with PKCS#7, and encrypted with AES-128-CBC.
The IV is `iv + uint32(seq)` in big-endian order. Increment `seq` before each request.

The request body is:

```text
SHA256(sigKey + uint32(seq) + ciphertext) + ciphertext
```

Send it to `/app/request?seq=<seq>` with the `TP_SESSIONID` cookie.

The response has the same 32-byte signature prefix and AES-CBC ciphertext.

The command response may be `{}` even when the command succeeds. To verify the
physical state, send a second encrypted request with `{"system":{"get_sysinfo":null}}`
and inspect `system.get_sysinfo.light_state.on_off` (`0` means off, `1` means on).

## Light commands

All commands use this L530E service envelope:

```json
{
  "smartlife.iot.smartbulb.lightingservice": {
    "transition_light_state": {
      "...": "..."
    }
  }
}
```

### Turn off

Go function: `TurnOff`

```json
{
  "smartlife.iot.smartbulb.lightingservice": {
    "transition_light_state": {
      "on_off": 0,
      "ignore_default": 1
    }
  }
}
```

### Turn on

Go function: `TurnOn`

```json
{
  "smartlife.iot.smartbulb.lightingservice": {
    "transition_light_state": {
      "on_off": 1,
      "ignore_default": 0
    }
  }
}
```

`ignore_default: 0` restores the bulb's previous/default light state.

### Change brightness

Go function: `ChangeBrightness(session, client, deviceIP, brightness)`

`brightness` is an integer from 1 to 100. A value of 0 is treated as off by the bulb libraries, so use `TurnOff` for an explicit off command.

```json
{
  "smartlife.iot.smartbulb.lightingservice": {
    "transition_light_state": {
      "on_off": 1,
      "brightness": 75,
      "ignore_default": 1
    }
  }
}
```

### Change color

Go function: `ChangeColor(session, client, deviceIP, hue, saturation, brightness)`

- `hue`: integer from 0 to 360 degrees
- `saturation`: integer from 0 to 100 percent
- `brightness`: integer from 1 to 100 percent

```json
{
  "smartlife.iot.smartbulb.lightingservice": {
    "transition_light_state": {
      "on_off": 1,
      "hue": 180,
      "saturation": 100,
      "brightness": 80,
      "color_temp": 0,
      "ignore_default": 1
    }
  }
}
```

Set `color_temp` to `0` when using HSV color mode. For white-temperature mode, use a color temperature in the bulb's supported range and omit HSV fields.

## Example

The current `main.go` performs the three phases and calls `TurnOff`:

```bash
go run .
```

Replace the call in `main` with `TurnOn`, `ChangeBrightness`, or `ChangeColor` to test another operation. Each call consumes the next KLAP sequence number.
