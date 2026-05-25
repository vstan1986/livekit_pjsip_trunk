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

## Firewall Configuration (UFW)

Below is an example `ufw` setup. Replace `<sip_provider_subnet>` with your
SIP provider's subnet (or IP range), and `<your_external_ip>` with your
LiveKit server's IP. Adjust ports to match your `config.json`.

```bash
# SIP signalling (UDP + TCP) from your provider
sudo ufw allow proto udp from <sip_provider_subnet> to any port 5060
sudo ufw allow proto tcp from <sip_provider_subnet> to any port 5060

# Registration port (if different from signalling port)
sudo ufw allow proto udp from <sip_provider_subnet> to any port 5061
sudo ufw allow proto tcp from <sip_provider_subnet> to any port 5061

# RTP media range 10000-20000 from provider
sudo ufw allow proto udp from <sip_provider_subnet> to any port 10000:20000

# LiveKit trunk (replace with your LiveKit server IP)
sudo ufw allow proto udp from <your_external_ip> to any port 5062

# Optional: health check only on internal network
# sudo ufw allow from 172.16.0.0/12 to any port 8080

# Make sure SSH stays accessible
sudo ufw allow 22/tcp
```

> **Note on RTP range:** The gateway uses PJSIP's built-in RTP port pool.
> You can set a custom range per line via `rtp_port_start` and
> `rtp_port_count` in `config.json`. The example above opens `10000:20000`
> for the provider side. LiveKit handles its own RTP ports internally.
