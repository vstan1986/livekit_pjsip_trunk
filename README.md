# B2BUA SIP Gateway

**B2BUA SIP Gateway** solves a limitation of LiveKit SIP Trunk -- LiveKit cannot
initiate outbound SIP REGISTER. As a result, the SIP provider has no way of
knowing where to deliver incoming calls.

This project provides LiveKit with a **static SIP trunk**:

```
SIP Provider <--> B2BUA Gateway <--> LiveKit
    (REGISTER)         (static SIP trunk)
```

The gateway registers with the provider, accepts incoming calls, and forwards
them to the LiveKit SIP trunk address. Conversely, calls from LiveKit are
routed to the provider. Media (audio) is bridged between the two legs.

## Philosophy

- **Single configuration file** `config.json`. No env flags, extra configs,
  or complex CLI arguments.
- **Zero overhead for the peer.** The gateway does not modify the audio stream,
  and Caller ID is transparently forwarded.
- **Each line gets its own port.** Multiple providers and multiple LiveKit
  trunks can be connected.
- **Cheap and simple.** Runs on a single VPS, no database, S3, or Redis
  required -- minimal dependencies.

## How It Works

```
  +-------------+         +-----------------------------------+         +--------------+
  |             |  INVITE | 1. ProviderLine accepts the call, |  INVITE |              |
  |  SIP        | ------->|    sends 180 Ringing to provider  | ------->|  LiveKit     |
  | Provider    |         | 2. Creates B2BCall -> makeCall()  |         | SIP Trunk    |
  |             |         | 3. LiveKit answers 200 OK --      | 200 OK  |              |
  |             | <-------|    gateway responds 200 OK        | <-------|              |
  |             |         | 4. AudioMedia bridged via         |         |              |
  |             | RTP pw  |    PJSIP conference bridge        | RTP pw  |              |
  +-------------+         +-----------------------------------+         +--------------+
```

1. **ProviderLine** registers with the SIP provider (REGISTER).
2. Incoming call from provider -> `ProviderLine.onIncomingCall()` ->
   creates B2BCall -> INVITE to LiveKit.
3. LiveKit responds -> answer to provider -> audio bridged.
4. Outgoing call from LiveKit -> `LiveKitLine.onIncomingCall()` ->
   INVITE to provider -- same flow.
5. **Health Check** `GET /health` -- JSON status of each line.

## Quick Start

```bash
# 1. Copy and edit the config
cp config.example.json config.json
#    ^ fill in your provider and LiveKit credentials

# 2. Start the gateway
docker compose up -d

# 3. Check status
curl http://localhost:8080/health
```

PJSIP is downloaded automatically from the official repository during build.

## Configuration

Copy `config.example.json` to `config.json` and fill in your data:

```bash
cp config.example.json config.json
```

Example structure:

```json
{
    "endpoint": {
        "log_level": 3
    },
    "lines": [
        {
            "name": "Line 1",
            "provider": {
                "host": "sip.provider.example.com",
                "port": 5060,
                "register_port": 5061,
                "auth": {
                    "username": "1001",
                    "password": "change-me"
                },
                "register": true,
                "registration_timeout": 300,
                "keepalive_interval": 25
            },
            "livekit": {
                "listen_port": 5062,
                "target_host": "livekit.example.com",
                "target_port": 5060
            }
        }
    ],
    "health_check": {
        "listen_ip": "0.0.0.0",
        "listen_port": 8080
    }
}
```

After changes, restart the container:
```bash
docker compose restart
```

## Environment Variables

Passwords can be overridden via env (more secure than config.json):

```
SIP_PASSWORD_LINE_1=supersecret
```

The variable follows the pattern `SIP_PASSWORD_<NAME>`, where `<NAME>` is the
line name in uppercase, with spaces replaced by `_`. For example, for a line
named `My Line` -- `SIP_PASSWORD_MY_LINE=...`.

You can also use a `.env` file in the project directory (it is already in
`.gitignore`):

```bash
echo "SIP_PASSWORD_LINE_1=supersecret" >> .env
docker compose --env-file .env up -d
```

## Ports

Inbound ports (open on firewall):
- `provider.register_port` -- for calls from the SIP provider
- `livekit.listen_port` -- for calls from LiveKit
- `8080` -- health check
