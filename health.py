# B2BUA SIP Gateway — Static SIP Trunk for LiveKit
# Copyright (C) 2024  vstan1986
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
"""
Health-check HTTP server for the B2BUA SIP Gateway.
"""

import json
import logging
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

_log = logging.getLogger("gateway.health")


class HealthHandler(BaseHTTPRequestHandler):
    """Exposes registration status at GET /health."""

    provider_registry = None  # set by caller before starting the server

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            statuses = {}
            registry = self.__class__.provider_registry or {}
            for name, line in registry.items():
                active = getattr(line, "_cached_reg_active", False)
                code = getattr(line, "_cached_reg_code", 0)
                reason = getattr(line, "_cached_reg_reason", "unknown")
                statuses[name] = {
                    "active": active,
                    "code": code,
                    "reason": reason,
                }
            body = json.dumps({"lines": statuses}, indent=2)
            self.wfile.write(body.encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    # Suppress noisy HTTP access logs (health check)
    def log_message(self, fmt, *args):
        pass


def start_health_server(host: str, port: int):
    server = HTTPServer((host, port), HealthHandler)
    _log.info("Health check server listening on %s:%d", host, port)
    server.serve_forever()
