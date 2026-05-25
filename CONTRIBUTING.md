# Contributing to B2BUA SIP Gateway

Thank you for your interest! This project is small but useful — contributions
are welcome.

## How to Contribute

1. **Fork** the repository.
2. **Create a branch** for your change:
   ```bash
   git checkout -b feat/my-feature
   ```
3. **Make your changes.** Keep them focused — one change per PR.
4. **Test** that Docker build still works:
   ```bash
   docker build -t b2bua-gateway .
   ```
5. **Open a Pull Request** with a clear description of what you changed and why.

## Guidelines

- **Keep it simple.** This project values minimal dependencies and simple code.
- **Don't break existing configs.** Backward compatibility is important.
- **Python 3.9** compatibility (Alpine/builder constraint).
- **Update README.md** if you change configuration or add features.
- **No external services** — no database, Redis, etc.

## Reporting Issues

Open a GitHub issue with:
- Your config (redact passwords)
- Docker build / run logs
- What you expected vs what happened

Thank you! 🚀
