#!/usr/bin/env python3
"""
B2BUA SIP Gateway (Media-Bridge) on PJSUA2.

Each line has two ports:
  - provider.register_port: for REGISTER + incoming calls from provider
  - livekit.listen_port:    for incoming calls from LiveKit (outbound trunk)

Each line has its own ProviderLine + LiveKitLine pair.
Media is bridged via startTransmit — no RTP termination inside the gateway.
"""

import logging
import os
import re
import signal
import sys
import threading

import pjsua2 as pj

from config import CONFIG_PATH, load_config
from sip_helpers import (
    inbound_header,
    inbound_target,
    outbound_target_uri,
)
from health import HealthHandler, start_health_server

_log = logging.getLogger("gateway")
_provider_registry: dict = {}    # name -> ProviderLine
_lkline_registry: dict = {}      # listen_port -> LiveKitLine
_call_registry: dict = {}        # call_id -> B2BCall
_ep = None                       # pj.Endpoint
_config = None                   # dict


# ---------------------------------------------------------------------------
# Account & endpoint builders
# ---------------------------------------------------------------------------

def setup_logging(level: int):
    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    logging.basicConfig(level=level, format=fmt, stream=sys.stdout, force=True)

def build_provider_account(line_cfg: dict) -> pj.AccountConfig:
    """Build AccountConfig for a provider line."""
    prov = line_cfg["provider"]
    acfg = pj.AccountConfig()
    acfg.priority = 0

    username = prov["auth"]["username"]
    domain = prov["host"]
    acfg.idUri = f"sip:{username}@{domain}"

    acfg.regConfig.registrarUri = f"sip:{domain}"
    if prov.get("register", True):
        acfg.regConfig.regOn = True
        acfg.regConfig.regTimeout = prov.get("registration_timeout", 300)
        acfg.regConfig.contactParams = ";transport=UDP;lr=on"
        acfg.natConfig.keepAliveInterval = prov.get("keepalive_interval", 25)
    else:
        acfg.regConfig.regOn = False

    port = prov["register_port"]
    tcfg = pj.TransportConfig()
    tcfg.port = port
    try:
        tp = _ep.transportCreate(pj.PJSIP_TRANSPORT_UDP, tcfg)
        _log.info("Provider transport: UDP on port %d", port)
        acfg.transportId = tp
    except pj.Error as e:
        _log.warning("Transport on port %d may already exist: %s", port, e.info())
        acfg.transportId = 0

    # RTP port pool — avoid "Address already in use" by using a dedicated
    # range per line, so concurrent calls get unique ports.
    rtp_start = prov.get("rtp_port_start", 40000)
    rtp_count = prov.get("rtp_port_count", 256)
    acfg.mediaConfig.transportConfig.port = rtp_start
    acfg.mediaConfig.transportConfig.portRange = rtp_count
    # Public RTP address — override the container's internal IP in SDP so
    # the provider can reach RTP.  Falls back to livekit.target_host as a
    # best-effort guess at an externally-reachable address.
    ext_ip = (
        prov.get("public_address")
        or prov.get("external_ip")
        or line_cfg.get("livekit", {}).get("target_host", "")
    )
    if ext_ip:
        acfg.mediaConfig.transportConfig.publicAddress = ext_ip

    if username and prov["auth"].get("password"):
        cred = pj.AuthCredInfo("digest", "*", username, 0, prov["auth"]["password"])
        acfg.sipConfig.authCreds.append(cred)

    # Support password via env var (higher priority): SIP_PASSWORD_<NAME>
    # Replaces password from config.json for security
    env_var = f"SIP_PASSWORD_{line_cfg['name'].upper().replace(' ', '_')}"
    env_pass = os.environ.get(env_var)
    if env_pass:
        # Remove old cred with same username, add new one with env password
        acfg.sipConfig.authCreds.clear()
        cred = pj.AuthCredInfo("digest", "*", username, 0, env_pass)
        acfg.sipConfig.authCreds.append(cred)
        _log.info("Using password from env %s for line '%s'", env_var,
                  line_cfg["name"])

    return acfg

def build_livekit_line_account(line_cfg: dict) -> pj.AccountConfig:
    """Build AccountConfig for a LiveKitLine (no registration)."""
    lk = line_cfg["livekit"]
    acfg = pj.AccountConfig()
    acfg.priority = 0
    safe_name = re.sub(r"[^a-zA-Z0-9_.-]", "_", line_cfg["name"])
    lk_host = lk['target_host']
    acfg.idUri = f'sip:livekit-{safe_name}@{lk_host}'
    acfg.regConfig.regOn = False

    # RTP port pool — use a different range than the provider so the two
    # legs of a call don't collide.
    rtp_start = lk.get("rtp_port_start", 40512)
    rtp_count = lk.get("rtp_port_count", 256)
    acfg.mediaConfig.transportConfig.port = rtp_start
    acfg.mediaConfig.transportConfig.portRange = rtp_count
    # Public RTP address — falls back to target_host as a best-effort
    # guess at an externally-reachable address.
    ext_ip = (
        lk.get("public_address")
        or lk.get("external_ip")
        or lk.get("target_host", "")
    )
    if ext_ip:
        acfg.mediaConfig.transportConfig.publicAddress = ext_ip

    port = lk["listen_port"]
    tcfg = pj.TransportConfig()
    tcfg.port = port
    try:
        tp = _ep.transportCreate(pj.PJSIP_TRANSPORT_UDP, tcfg)
        _log.info("LiveKit transport for '%s' on port %d", line_cfg["name"], port)
        acfg.transportId = tp
    except pj.Error:
        _log.warning("LiveKit transport on port %d may already exist", port)
        acfg.transportId = 0

    return acfg

def create_endpoint(cfg: dict) -> pj.Endpoint:
    ep_cfg = pj.EpConfig()
    log_lvl = cfg.get("endpoint", {}).get("log_level", 4)
    ep_cfg.logConfig.level = log_lvl
    ep_cfg.logConfig.consoleLevel = cfg.get("endpoint", {}).get("console_level", log_lvl)
    # Enable SIP message printing (mod-msg-print) at level 4+
    ep_cfg.logConfig.msgLogging = log_lvl >= 4
    ep_cfg.logConfig.decor = (
        pj.PJ_LOG_HAS_DAY_NAME | pj.PJ_LOG_HAS_TIME |
        pj.PJ_LOG_HAS_MICRO_SEC | pj.PJ_LOG_HAS_SENDER |
        pj.PJ_LOG_HAS_NEWLINE | pj.PJ_LOG_HAS_LEVEL_TEXT
    )
    # Match codec sample rate (PCMA/PCMU = 8kHz) to avoid resampling
    ep_cfg.medConfig.clockRate = 8000
    ep_cfg.medConfig.sndClockRate = 8000
    ep_cfg.medConfig.ecOptions = 0
    ep_cfg.medConfig.ecTailLen = 0
    ep_cfg.medConfig.noVad = True
    ep_cfg.medConfig.txPtime = 20
    ep_cfg.medConfig.quality = 0
    # Reduce jitter buffer for low-latency
    ep_cfg.medConfig.jbInit = 10
    ep_cfg.medConfig.jbMinPrefetch = 10
    ep_cfg.medConfig.jbMaxPrefetch = 50
    ep_cfg.uaConfig.maxCalls = 256
    ep_cfg.uaConfig.threadCnt = 0
    ep_cfg.uaConfig.mainThreadOnly = True
    ep_cfg.uaConfig.nameserver.clear()

    ua = cfg.get("endpoint", {})
    if ua.get("user_agent"):
        ep_cfg.uaConfig.userAgent = ua["user_agent"]
    if ua.get("stun_server"):
        ep_cfg.uaConfig.stunServer = ua["stun_server"]

    ep = pj.Endpoint()
    ep.libCreate()
    ep.libInit(ep_cfg)

    # Prioritise PCMA over PCMU in SDP offers — provider prefers A-law.
    ep.codecSetPriority("pcma/8000", 255)   # PJMEDIA_CODEC_PRIO_HIGHEST
    ep.codecSetPriority("pcmu/8000", 128)   # PJMEDIA_CODEC_PRIO_NORMAL
    return ep


# ---------------------------------------------------------------------------
# Call class (B2BUA leg)
# ---------------------------------------------------------------------------

class B2BCall(pj.Call):
    """
    Represents one leg of a B2BUA session.
    The paired leg is stored in *peer_call*.
    """

    def __init__(self, acc: pj.Account, call_id: int = pj.PJSUA_INVALID_ID):
        super().__init__(acc, call_id)
        self.acc = acc
        self.peer_call = None

    def onCallState(self, prm: pj.OnCallStateParam):
        ci = self.getInfo()
        if ci.state == pj.PJSIP_INV_STATE_CONFIRMED:
            # Peer call is answered — answer the other leg with 200 OK
            peer = self.peer_call
            if peer is not None:
                try:
                    peer_ci = peer.getInfo()
                    if peer_ci.state in (pj.PJSIP_INV_STATE_EARLY,
                                         pj.PJSIP_INV_STATE_CONNECTING):
                        ans_prm = pj.CallOpParam()
                        ans_prm.statusCode = 200
                        peer.answer(ans_prm)
                        _log.info("Answered peer call %d with 200 OK",
                                  peer_ci.id)
                except pj.Error as e:
                    _log.error("Failed to answer peer call: %s", e.info())
        elif ci.state == pj.PJSIP_INV_STATE_DISCONNECTED:
            remote = ci.remoteUri
            _log.info("Call %d disconnected (reason=%s code=%d remote=%s)",
                      ci.id, ci.lastReason, ci.lastStatusCode, remote)
            peer = self.peer_call
            self.peer_call = None
            if peer is not None:
                try:
                    peer_ci = peer.getInfo()
                    if peer_ci.state != pj.PJSIP_INV_STATE_DISCONNECTED:
                        peer.hangup(pj.CallOpParam())
                except pj.Error:
                    pass
                peer.peer_call = None
            _call_registry.pop(ci.id, None)

    def onCallMediaState(self, prm: pj.OnCallMediaStateParam):
        """Bridge audio between this call leg and its peer."""
        peer = self.peer_call
        if peer is None:
            return

        ci = self.getInfo()
        try:
            peer_ci = peer.getInfo()
        except pj.Error:
            return

        # Find active audio media in this call
        my_aud = None
        for i, mi in enumerate(ci.media):
            if mi.type == pj.PJMEDIA_TYPE_AUDIO and \
               mi.status == pj.PJSUA_CALL_MEDIA_ACTIVE:
                try:
                    my_aud = self.getAudioMedia(i)
                    break
                except pj.Error:
                    pass

        # Find active audio media in peer call
        peer_aud = None
        for i, mi in enumerate(peer_ci.media):
            if mi.type == pj.PJMEDIA_TYPE_AUDIO and \
               mi.status == pj.PJSUA_CALL_MEDIA_ACTIVE:
                try:
                    peer_aud = peer.getAudioMedia(i)
                    break
                except pj.Error:
                    pass

        if my_aud is not None and peer_aud is not None:
            try:
                my_aud.startTransmit(peer_aud)
                peer_aud.startTransmit(my_aud)
                _log.info("Audio bridged between call %d and call %d",
                          ci.id, peer_ci.id)
            except pj.Error as e:
                _log.error("Failed to bridge audio: %s", e.info())

    def onCallMediaEvent(self, prm: pj.OnCallMediaEventParam):
        """Suppress media event processing."""
        pass


# ---------------------------------------------------------------------------
# ProviderLine — registers at provider, receives incoming calls from provider
# ---------------------------------------------------------------------------

class ProviderLine(pj.Account):
    """
    Registers at the SIP provider and waits for incoming calls.
    Incoming calls from provider are forwarded to LiveKit.
    """

    def __init__(self, cfg: dict, line_cfg: dict):
        super().__init__()
        self.cfg = cfg
        self.line_cfg = line_cfg
        self.name = line_cfg["name"]

    def onRegState(self, prm: pj.OnRegStateParam):
        self._cached_reg_active = (prm.code == 200)
        self._cached_reg_code = prm.code
        self._cached_reg_reason = prm.reason
        _log.info(
            "Line '%s' registration state changed (code=%d reason=%s)",
            self.name, prm.code, prm.reason,
        )

    def onIncomingCall(self, prm: pj.OnIncomingCallParam):
        """Incoming call from provider → make outgoing call to LiveKit (B2BUA)."""
        _log.info("Incoming call on line '%s' from provider, call_id=%d",
                  self.name, prm.callId)

        _log.debug("Provider INVITE (wholeMsg): %.1000s", prm.rdata.wholeMsg)

        prov_call = B2BCall(self, prm.callId)
        _call_registry[prm.callId] = prov_call

        target_uri = inbound_target(prm, self.line_cfg)

        lk_line = _lkline_registry.get(self.line_cfg["livekit"]["listen_port"])
        if lk_line is None:
            _log.error("No LiveKitLine for listen_port %d",
                       self.line_cfg["livekit"]["listen_port"])
            prov_call.hangup(pj.CallOpParam())
            _call_registry.pop(prm.callId, None)
            return

        lk_call = B2BCall(lk_line)
        prov_call.peer_call = lk_call
        lk_call.peer_call = prov_call

        ring_prm = pj.CallOpParam()
        ring_prm.statusCode = 180
        try:
            prov_call.answer(ring_prm)
        except pj.Error as e:
            _log.error("Failed to answer provider call: %s", e.info())

        # Forward the real caller number (From) to LiveKit
        # via P-Asserted-Identity (RFC 3325).
        call_prm = pj.CallOpParam()
        call_prm.txOption = pj.SipTxOption()
        caller_from = inbound_header(prm.rdata.wholeMsg, "From")
        if caller_from:
            hdr = pj.SipHeader()
            hdr.hName = "P-Asserted-Identity"
            hdr.hValue = caller_from
            call_prm.txOption.headers.append(hdr)
            _log.info("Forwarding caller to LiveKit as P-Asserted-Identity: %s",
                      caller_from)
        try:
            lk_call.makeCall(target_uri, call_prm)
            _log.info("Ringing call to LiveKit: %s", target_uri)
            _call_registry[lk_call.getInfo().id] = lk_call
        except pj.Error as e:
            _log.error("Failed to call LiveKit: %s", e.info())
            _call_registry.pop(prm.callId, None)
            prov_call.hangup(pj.CallOpParam())


# ---------------------------------------------------------------------------
# LiveKitLine — receives calls from LiveKit, forwards to provider
# ---------------------------------------------------------------------------

class LiveKitLine(pj.Account):
    """
    Listens for incoming calls from LiveKit on a dedicated listen_port.
    Each line has its own LiveKitLine.
    Forwards calls to the corresponding provider.
    """

    def __init__(self, cfg: dict, line_cfg: dict):
        super().__init__()
        self.cfg = cfg
        self.line_cfg = line_cfg
        self.name = line_cfg["name"]

    def onIncomingCall(self, prm: pj.OnIncomingCallParam):
        """Incoming call from LiveKit → make outgoing call to provider (B2BUA)."""
        _log.info("Incoming call from LiveKit on line '%s', call_id=%d",
                  self.name, prm.callId)

        _log.debug("LiveKit INVITE (wholeMsg): %.1000s", prm.rdata.wholeMsg)

        lk_call = B2BCall(self, prm.callId)
        _call_registry[prm.callId] = lk_call

        target_uri = outbound_target_uri(prm, self.line_cfg)

        prov = self.line_cfg["provider"]
        if prov.get("transport", "udp") != "udp":
            target_uri += f";transport={prov['transport']}"

        prov_line = _provider_registry.get(self.name)
        if prov_line is None:
            _log.error("No ProviderLine found for '%s'", self.name)
            call_prm = pj.CallOpParam()
            call_prm.statusCode = 404
            lk_call.answer(call_prm)
            return

        prov_call = B2BCall(prov_line)
        lk_call.peer_call = prov_call
        prov_call.peer_call = lk_call

        ring_prm = pj.CallOpParam()
        ring_prm.statusCode = 180
        try:
            lk_call.answer(ring_prm)
        except pj.Error as e:
            _log.error("Failed to answer LiveKit call: %s", e.info())

        call_prm = pj.CallOpParam()
        try:
            prov_call.makeCall(target_uri, call_prm)
            _log.info("Ringing call to provider: %s", target_uri)
            _call_registry[prov_call.getInfo().id] = prov_call
        except pj.Error as e:
            _log.error("Failed to call provider: %s", e.info())
            _call_registry.pop(prm.callId, None)
            lk_call.hangup(pj.CallOpParam())


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def main():
    global _ep, _config

    cfg_path = os.environ.get("CONFIG_PATH", CONFIG_PATH)
    _config = load_config(cfg_path)

    log_level = _config.get("endpoint", {}).get("log_level", 3)
    log_map = {0: logging.DEBUG, 1: logging.DEBUG, 2: logging.INFO,
               3: logging.WARNING, 4: logging.ERROR, 5: logging.CRITICAL,
               6: logging.CRITICAL}
    setup_logging(log_map.get(log_level, logging.INFO))

    _log.info("Starting B2BUA SIP Gateway...")

    _ep = create_endpoint(_config)
    # Use null sound device — no audio hardware needed
    _ep.audDevManager().setNullDev()
    _ep.libStart()
    _log.info("PJSUA2 endpoint started")

    # Validate uniqueness of all ports
    used_ports = {}
    for lc in _config.get("lines", []):
        if not lc.get("enabled", True):
            continue
        name = lc["name"]
        reg_port = lc["provider"]["register_port"]
        lk_port = lc["livekit"]["listen_port"]
        for label, p in [(f"{name}/register_port", reg_port),
                         (f"{name}/listen_port", lk_port)]:
            if p in used_ports.values():
                _log.error("Port %d is already used by %s", p,
                           [k for k, v in used_ports.items() if v == p][0])
                _ep.libDestroy()
                sys.exit(1)
            used_ports[label] = p

    # Create accounts for each line
    for lc in _config.get("lines", []):
        if not lc.get("enabled", True):
            _log.info("Line '%s' is disabled, skipping", lc["name"])
            continue

        name = lc["name"]
        prov = lc["provider"]
        lk = lc["livekit"]

        # 1. Provider account (with REGISTER)
        prov_acfg = build_provider_account(lc)
        prov_line = ProviderLine(_config, lc)
        try:
            prov_line.create(prov_acfg)
            _provider_registry[name] = prov_line
            _log.info("Provider '%s' created (register_port %d, registrar %s)",
                      name, prov["register_port"], prov["host"])
        except pj.Error as e:
            _log.error("Failed to create provider '%s': %s", name, e.info())
            continue

        # 2. LiveKit account (no register, just listens for INVITE)
        lk_acfg = build_livekit_line_account(lc)
        lk_line = LiveKitLine(_config, lc)
        try:
            lk_line.create(lk_acfg)
            _lkline_registry[lk["listen_port"]] = lk_line
            _log.info("LiveKitLine '%s' created (listen_port %d, target %s:%d)",
                      name, lk["listen_port"], lk["target_host"], lk["target_port"])
        except pj.Error as e:
            _log.error("Failed to create LiveKitLine '%s': %s", name, e.info())

    if not _provider_registry:
        _log.warning("No lines configured or enabled")
        _ep.libDestroy()
        sys.exit(1)

    # Start health check server
    hc = _config.get("health_check", {})
    hc_host = hc.get("listen_ip", "0.0.0.0")
    hc_port = hc.get("listen_port", 8080)
    hc_thread = threading.Thread(
        target=start_health_server, args=(hc_host, hc_port), daemon=True,
    )
    hc_thread.start()
    _log.info("Health check server started on %s:%d", hc_host, hc_port)

    # Wire up health server with the provider registry
    HealthHandler.provider_registry = _provider_registry

    _log.info("B2BUA Gateway is running. Press Ctrl+C to stop.")

    # Graceful shutdown on SIGTERM (docker stop) or SIGINT (Ctrl+C)
    shutdown_event = threading.Event()

    def _signal_handler(signum, frame):
        _log.info("Received signal %d, shutting down...", signum)
        shutdown_event.set()

    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)

    try:
        while not shutdown_event.is_set():
            _ep.libHandleEvents(100)
    finally:
        _log.info("Shutting down...")
        _ep.libDestroy()
        _log.info("Gateway stopped.")


if __name__ == "__main__":
    main()
