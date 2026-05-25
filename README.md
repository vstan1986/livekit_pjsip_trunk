<p align="center">
  <img src="https://img.shields.io/badge/python-3.9-blue?logo=python" alt="Python">
  <img src="https://img.shields.io/badge/PJSIP-2.15.1-green" alt="PJSIP">
  <img src="https://img.shields.io/badge/LiveKit-SIP%20Trunk-purple?logo=livekit" alt="LiveKit">
  <a href="https://hub.docker.com/r/vstan1986/livekit-pjsip-trunk"><img src="https://img.shields.io/badge/docker-ready-2496ED?logo=docker" alt="Docker"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-green" alt="License"></a>
  <a href="https://github.com/vstan1986/livekit_pjsip_trunk/actions/workflows/docker-build.yml"><img src="https://github.com/vstan1986/livekit_pjsip_trunk/actions/workflows/docker-build.yml/badge.svg" alt="Build"></a>
</p>

# B2BUA SIP Gateway — Static SIP Trunk for LiveKit

**Solve the missing outbound REGISTER problem.** LiveKit's built-in SIP Trunk
cannot initiate outbound SIP REGISTER messages, so many SIP providers have no
way to deliver incoming calls. This gateway acts as a **B2BUA (Back-to-Back
User Agent)** that registers with your provider and bridges calls bidirectionally
between the SIP provider and LiveKit.

```
SIP Provider ◄─REGISTER── B2BUA Gateway ◄──RTP──► LiveKit
     │                        │                      │
     └──────inbound call──────┘────forward INVITE────┘
     ┌──────outbound call─────┐◄───forward INVITE─────┘
```

## ✨ Features

- **🔗 Static SIP trunk for LiveKit** — accept incoming calls from any SIP provider that requires registration
- **📤 Bidirectional B2BUA** — inbound calls from provider to LiveKit AND outbound calls from LiveKit to provider
- **🔄 Full B2BUA media bridging** — two independent call legs with RTP forwarded via PJSIP conference bridge
- **📞 Caller ID preserved** — original From header forwarded as `P-Asserted-Identity` to LiveKit
- **🔌 Multi-line, multi-provider** — each line configures its own provider + LiveKit trunk pair
- **🔒 Password via environment** — override SIP passwords with `SIP_PASSWORD_<NAME>` env vars (never commit secrets)
- **🩺 Health endpoint** — `GET /health` returns registration status of every line
- **🐳 Docker-only, zero deps** — no database, Redis, S3, or external services required. Runs on a single VPS
- **⚡ Low latency** — minimal jitter buffer (10 ms), no VAD, no resampling, Opus passthrough

## 📦 Quick Start

```bash
# 1. Copy and edit the config
cp config.example.json config.json
#    ^ fill in your provider and LiveKit credentials

# 2. Start the gateway
docker compose up -d

# 3. Check registration status
curl http://localhost:8080/health
```

PJSIP is downloaded and compiled automatically during the Docker build.

## 🔧 Why This Exists

LiveKit's SIP Trunk is ** outbound-only** — it does NOT send REGISTER to your
provider. Many providers (especially in Europe and Asia) require a REGISTER
before they route inbound calls to you. This project fills that gap with a
lightweight, stateless B2BUA gateway.

| Approach | Inbound calls | Complexity |
|---|---|---|
| LiveKit SIP Trunk (standalone) | ❌ No | Low |
| **This gateway + LiveKit** | ✅ Yes | Low |
| Full PBX (Asterisk / FreeSWITCH) | ✅ Yes | High |

## 🧠 How It Works

```
  +-------------+         +-----------------------------------+         +--------------+
  │             │  INVITE │ 1. ProviderLine accepts the call, │  INVITE │              │
  │  SIP        │ ───────►│    sends 180 Ringing to provider  │ ───────►│  LiveKit     │
  │ Provider    │         │ 2. Creates B2BCall → makeCall()   │         │ SIP Trunk    │
  │             │         │ 3. LiveKit answers 200 OK ──      │ 200 OK  │              │
  │             │ ◄───────│    gateway responds 200 OK        │ ◄───────│              │
  │             │         │ 4. AudioMedia bridged via         │         │              │
  │             │  RTP    │    PJSIP conference bridge        │  RTP    │              │
  +-------------+         +-----------------------------------+         +--------------+
```

1. **ProviderLine** registers with the SIP provider via REGISTER.
2. Incoming call from provider → `ProviderLine.onIncomingCall()` →
   creates B2BCall → INVITE to LiveKit.
3. LiveKit responds → answer to provider → audio bridged.
4. Outgoing call from LiveKit → `LiveKitLine.onIncomingCall()` →
   INVITE to provider — same flow.
5. **Health Check** `GET /health` returns JSON status of each line.

## ⚙️ Configuration

Copy `config.example.json` to `config.json` and fill in your data:

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

### 🔐 Environment Variables

Passwords can be overridden via env (more secure than config.json):

```bash
SIP_PASSWORD_LINE_1=supersecret
```

The variable follows the pattern `SIP_PASSWORD_<NAME>`, where `<NAME>` is the
line name in uppercase, with spaces replaced by `_`. For example, for a line
named `My Line`:

```bash
SIP_PASSWORD_MY_LINE=supersecret
```

You can also use a `.env` file in the project directory:

```bash
echo "SIP_PASSWORD_LINE_1=supersecret" >> .env
docker compose --env-file .env up -d
```

## 🌐 Ports

Inbound ports (open on firewall):
- `provider.register_port` — for calls from the SIP provider
- `livekit.listen_port` — for calls from LiveKit
- `8080` — health check

## 🛡️ Firewall Configuration (UFW)

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

## 📊 Comparison

| Feature | This gateway | Asterisk / FreeSWITCH | Kamailio + RTPProxy |
|---|---|---|---|
| Setup time | 5 minutes | Hours–days | Days |
| Docker image | ✅ Single-stage | ❌ Complex | ❌ Complex |
| Resources | 256 MB RAM | 1 GB+ RAM | 512 MB+ RAM |
| Configuration | Single JSON file | Multiple configs | Multiple configs |
| Inbound REGISTER | ✅ Yes | ✅ Yes | ✅ Yes |
| Media anchoring | ✅ Yes (PJSIP) | ✅ Yes | ✅ Yes |

## 🏗️ Project Philosophy

- **Single configuration file** — `config.json`. No env flags, extra configs,
  or complex CLI arguments.
- **Zero overhead for the peer** — The gateway does not modify the audio stream,
  and Caller ID is transparently forwarded.
- **Each line gets its own port** — Multiple providers and multiple LiveKit
  trunks can be connected.
- **Cheap and simple** — Runs on a single VPS, no database, S3, or Redis
  required.

## 🤝 Contributing

Contributions are welcome! Please see [CONTRIBUTING.md](CONTRIBUTING.md).

## 📄 License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.
