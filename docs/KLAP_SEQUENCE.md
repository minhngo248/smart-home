# Tapo L530E KLAP Protocol Sequence

This diagram describes the KLAP v2 local communication flow implemented by this project.
The Tapo L530E is accessed over HTTP on port 80.

## Complete Flow

```mermaid
sequenceDiagram
    autonumber
    participant Go as Go Client
    participant Bulb as Tapo L530E

    Note over Go,Bulb: Authentication material is prepared locally
    Go->>Go: userHash = SHA1(TAPO_USER)
    Go->>Go: passwordHash = SHA1(TAPO_PASS)
    Go->>Go: authHash = SHA256(userHash + passwordHash)

    rect rgb(235, 245, 255)
        Note over Go,Bulb: Phase 1 - Handshake 1
        Go->>Go: Generate random 16-byte local_seed
        Go->>Bulb: POST /app/handshake1<br/>Body: local_seed
        Bulb-->>Go: 200 OK<br/>Body: remote_seed (16 bytes) + server_hash (32 bytes)
        Bulb-->>Go: Set-Cookie: TP_SESSIONID=...
        Go->>Go: Verify server_hash = SHA256(local_seed + remote_seed + authHash)
    end

    rect rgb(240, 250, 240)
        Note over Go,Bulb: Phase 2 - Handshake 2
        Go->>Go: client_hash = SHA256(remote_seed + local_seed + authHash)
        Go->>Bulb: POST /app/handshake2<br/>Body: client_hash<br/>Cookie: TP_SESSIONID
        Bulb-->>Go: 200 OK
        Go->>Go: Derive key, IV, sigKey, and initial seq
    end

    rect rgb(255, 248, 235)
        Note over Go,Bulb: Phase 3 - Encrypted request
        Go->>Go: seq = seq + 1
        Go->>Go: JSON -> PKCS#7 -> AES-128-CBC
        Go->>Go: signature = SHA256(sigKey + uint32(seq) + ciphertext)
        Go->>Bulb: POST /app/request?seq=seq<br/>Body: signature + ciphertext<br/>Cookie: TP_SESSIONID
        Bulb-->>Go: 200 OK<br/>Body: response_signature + response_ciphertext
        Go->>Go: Verify signature and decrypt response
    end
```

## Turn-Off Example

The first Phase 3 command sent by `TurnOff` is:

```json
{
  "smartlife.iot.smartbulb.lightingservice": {
    "transition_light_state": {
The current `go/main.go` performs the three phases and calls `TurnOff`:
```bash
cd go
go run .
    }
  }
}
```

The bulb may return an empty JSON object (`{}`) as the command result. The client then sends a second encrypted Phase 3 request to verify the physical state:

```mermaid
sequenceDiagram
    participant Go as Go Client
    participant Bulb as Tapo L530E

    Go->>Bulb: Encrypted transition_light_state<br/>on_off = 0
    Bulb-->>Go: Encrypted response: {}
    Go->>Go: Increment seq
    Go->>Bulb: Encrypted system.get_sysinfo request
    Bulb-->>Go: Encrypted system response
    Go->>Go: Read system.get_sysinfo.light_state.on_off
    Note over Go: on_off = 0 means off
```

The verification request plaintext is:

```json
{
  "system": {
    "get_sysinfo": null
  }
}
```

## Session Key Derivation

After Phase 2, the client derives the values used by Phase 3:

```text
key    = SHA256("lsk" + local_seed + remote_seed + authHash)[0:16]
ivFull = SHA256("iv"  + local_seed + remote_seed + authHash)
sigKey = SHA256("ldk" + local_seed + remote_seed + authHash)[0:28]
iv     = ivFull[0:12]
seq    = signed big-endian integer from ivFull[28:32]
```

For every encrypted request, the AES-CBC IV is:

```text
iv + uint32(seq)
```

The `TP_SESSIONID` cookie must be retained between all three phases and subsequent requests.

## Function Mapping

| Protocol operation | Go function |
|---|---|
| Handshake 1 | `phase1` |
| Handshake 2 | `phase2` |
| Turn off | `TurnOff` |
| Turn on | `TurnOn` |
| Change brightness | `ChangeBrightness` |
| Change color | `ChangeColor` |
| Encrypt/send/decrypt Phase 3 request | `sendKlapRequest` |
| Verify bulb state | `VerifyLightState` |
