# Changelog

All notable changes to this project will be documented in this file.

## [1.0.0] - 2024-01-06

### Added
- Initial release of B2BUA SIP Gateway
- ProviderLine with SIP REGISTER support
- LiveKitLine for incoming calls from LiveKit
- B2BUA call bridging via PJSIP conference bridge
- Health check HTTP endpoint (`GET /health`)
- Multi-line, multi-provider support
- Docker build with PJSIP 2.15.1
- Environment variable password override (`SIP_PASSWORD_<NAME>`)
- Configurable RTP port pools per line
- STUN server support
- Configurable transport (UDP/TCP) per line
