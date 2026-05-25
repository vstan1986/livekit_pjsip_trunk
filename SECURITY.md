# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in this project, please report it
privately by opening a **draft security advisory** on GitHub:

https://github.com/vstan1986/livekit_pjsip_trunk/security/advisories/new

Do **not** open a public issue for security vulnerabilities.

## Best Practices for Users

- **Use environment variables for passwords** (`SIP_PASSWORD_<NAME>`) rather
  than storing them in `config.json`.
- **Keep your firewall strict** — only allow SIP traffic from your provider's
  IP ranges and your LiveKit server.
- **Run behind NAT** with the `public_address` option set in config to avoid
  SDP IP mismatches.
- **Use `network_mode: host`** only when necessary — consider bridge networking
  with port mapping for better isolation.
