"""
SIP message helpers — SIP header/URI helpers for B2BUA gateway.
"""

import re
from typing import Optional


def inbound_header(sip_msg: str, header_name: str) -> Optional[str]:
    """Extract a SIP header from an INVITE received from the provider."""
    raw = sip_msg.encode("utf-8", errors="replace")
    _re = re.compile(
        rb"^" + re.escape(header_name.encode()) + rb":\s*(.*(?:\r?\n[ \t].*)*)",
        re.MULTILINE | re.IGNORECASE,
    )
    m = _re.search(raw)
    if not m:
        return None
    value = m.group(1).decode("utf-8", errors="replace")
    value = re.sub(r"\s*\r?\n\s+", " ", value)
    return value.strip()


def outbound_header(line_cfg: dict, header_name: str) -> Optional[str]:
    """
    Build a SIP header value for outbound calls from LiveKit to the provider.

    The value is always deterministic from config — no INVITE parsing.
    For ``"From"`` returns ``sip:{auth.username}@{host}:{port}``.
    Returns ``None`` for unsupported header names.
    """
    prov = line_cfg["provider"]
    if header_name == "From":
        return f"sip:{prov['auth']['username']}@{prov['host']}:{prov['port']}"
    return None


def inbound_target(_, line_cfg: dict) -> str:
    """
    Build the outbound SIP URI for a call coming from the provider
    and going to LiveKit.

    Target is deterministic from config — no request-URI parsing:
    ``sip:{provider.auth.username}@{livekit.target_host}:{livekit.target_port}``
    """
    lk = line_cfg["livekit"]
    username = line_cfg["provider"]["auth"]["username"]
    return f"sip:{username}@{lk['target_host']}:{lk['target_port']}"


def outbound_target_uri(prm, line_cfg: dict) -> str:
    """
    Build the outbound SIP URI for a call coming from LiveKit
    and going to the provider.

    Transforms the request-URI from the incoming LiveKit INVITE:

    1. Two ``@`` signs (``sip:user@actual-host@proxy``):
       host between ``sip:`` and the second ``@``.
    2. Single ``@``:
       a) host == *livekit.target_host* → replace with *provider.host*.
       b) otherwise keep original host.
    3. No ``@``:
       user from URI, host = *provider.host*.
    Port is always *provider.port*.
    """
    prov = line_cfg["provider"]
    lk = line_cfg["livekit"]

    # Extract request-URI from INVITE
    _re = re.compile(
        rb"^[a-z]+\s+(sip:[^\s]+)\s+sip/2\.0\s*$",
        re.MULTILINE | re.IGNORECASE,
    )
    m = _re.search(prm.rdata.wholeMsg.encode("utf-8", errors="replace"))
    request_uri = m.group(1).decode("utf-8", errors="replace") if m else ""

    if not request_uri:
        return f"sip:{prov['auth']['username']}@{prov['host']}:{prov['port']}"

    parts = request_uri.split("@")

    # 1) Two or more @ — double-@ notation
    if len(parts) >= 3:
        user = parts[0].replace("sip:", "")
        host = parts[1]
        return f"sip:{user}@{host}:{prov['port']}"

    # 2) Single @
    if len(parts) == 2:
        user = parts[0].replace("sip:", "")
        host = parts[1].split(":")[0]
        if host == lk["target_host"]:
            host = prov["host"]
        return f"sip:{user}@{host}:{prov['port']}"

    # 3) No @ — only user/number after sip:
    user = parts[0].replace("sip:", "")
    return f"sip:{user}@{prov['host']}:{prov['port']}"
