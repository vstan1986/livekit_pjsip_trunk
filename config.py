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
Configuration loader and validator for the B2BUA SIP Gateway.
"""

import json
import os


CONFIG_PATH = os.environ.get("CONFIG_PATH", "/app/config.json")


def load_config(path: str) -> dict:
    with open(path, "r") as f:
        cfg = json.load(f)

    # Validate required structure
    if "lines" not in cfg or not isinstance(cfg["lines"], list):
        raise ValueError("config.json must contain a 'lines' array")

    errors = []
    for i, lc in enumerate(cfg["lines"]):
        name = lc.get("name", f"Line {i + 1}")
        if not isinstance(lc, dict):
            errors.append(f"Line {i}: expected object, got {type(lc).__name__}")
            continue

        prov = lc.get("provider")
        if not isinstance(prov, dict):
            errors.append(f"Line '{name}': missing or invalid 'provider'")
            continue

        for key in ("host", "port", "register_port"):
            if key not in prov:
                errors.append(f"Line '{name}': missing 'provider.{key}'")

        auth = prov.get("auth")
        if isinstance(auth, dict):
            if not auth.get("username"):
                errors.append(f"Line '{name}': 'provider.auth.username' is required")
        elif auth is not None:
            errors.append(f"Line '{name}': 'provider.auth' must be an object")

        lk = lc.get("livekit")
        if not isinstance(lk, dict):
            errors.append(f"Line '{name}': missing or invalid 'livekit'")
            continue

        for key in ("listen_port", "target_host", "target_port"):
            if key not in lk:
                errors.append(f"Line '{name}': missing 'livekit.{key}'")

    if errors:
        raise ValueError("Configuration errors:\n  - " + "\n  - ".join(errors))

    return cfg
