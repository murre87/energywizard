"""log_scrub.py - sanerar loggtext innan den lämnar huset (#227, Emil 2026-11-11: "Systemet ska se till att känsliga
uppgifter inte kommer med").

Används för supportutdragen som följer med felrapporterna (support_bundle.py) och igen i samlaren innan något hamnar
i ett offentligt GitHub-ärende. Tre lager:

1. Husets egna känsliga ord, hämtade ur Home Assistant och EnergyWizards inställningar: platsens namn, koordinater,
   HA:s adresser, personernas och användarnas namn, zoner, telefoner/notistjänster, bilnamn, gästkonto, house_id.
   Ersätts med <namn> (eller <plats>/<adress>/<koordinat>).
2. Mönster: URL:er och värdnamn, IPv4/IPv6, MAC, e-post, token/nycklar (JWT, Bearer, ghp_, långa hex/base64),
   lösenord och nycklar i nyckel=värde, koordinater (tal med minst fyra decimaler i rimligt lat/long-intervall),
   serienummer, sökvägar. Entitets-id behåller bara domänen (sensor.<…>), som behövs för felsökningen.
3. Slutkontroll: en rad där något ändå ser känsligt ut byts helt mot "<rad borttagen>".

Ren logik + en uppslagning mot HA (sensitive_words) som cachas en timme.
"""
from __future__ import annotations

import re
import time

REMOVED = "<rad borttagen>"

_DOMAINS = (r"sensor|binary_sensor|switch|number|input_\w+|climate|water_heater|button|select|device_tracker|person|"
            r"media_player|light|cover|lock|vacuum|update|script|automation|scene|zone|fan|humidifier|calendar|todo|"
            r"notify|event|text|time|date|datetime|weather|camera|alarm_control_panel|remote|siren|valve|lawn_mower|image")
_ENTITY = re.compile(rf"\b({_DOMAINS})\.[a-z0-9_]+\b", re.I)
_URL = re.compile(r"\b[a-z][a-z0-9+.-]*://[^\s\"'<>)]+", re.I)
_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")
_IPV4 = re.compile(r"\b(?:25[0-5]|2[0-4]\d|1?\d?\d)(?:\.(?:25[0-5]|2[0-4]\d|1?\d?\d)){3}(?::\d{1,5})?\b")
_IPV6 = re.compile(r"(?<![\w:])(?:[0-9a-f:]*::[0-9a-f:]*[0-9a-f]|(?:[0-9a-f]{1,4}:){5,7}[0-9a-f]{1,4})(?![\w:])", re.I)   # inte klockslag
_MAC = re.compile(r"\b[0-9a-f]{2}(?:[:-][0-9a-f]{2}){5}\b", re.I)
_JWT = re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}(?:\.[A-Za-z0-9_-]+)?")
_BEARER = re.compile(r"\b(Bearer|Token|Basic)\s+[A-Za-z0-9._~+/=-]{8,}", re.I)
_PREFIXED = re.compile(r"\b(?:ghp_|gho_|github_pat_|sk-|xox[abp]-|AKIA)[A-Za-z0-9_-]{8,}\b")
_LONGHEX = re.compile(r"\b[0-9a-f]{24,}\b", re.I)
_LONGB64 = re.compile(r"(?<![\w/+])(?=[A-Za-z0-9+/_-]*\d)(?=[A-Za-z0-9+/_-]*[A-Za-z])[A-Za-z0-9+/_-]{32,}={0,2}(?![\w/+])")
_KEYVAL = re.compile(r"(?i)\b(pass(?:word|wd)?|lösen(?:ord)?|token|secret|api[_-]?key|access[_-]?key|private[_-]?key|pin|"
                     r"client[_-]?secret|refresh[_-]?token|cookie|session)\b(\s*[=:]\s*|\"\s*:\s*\")([^\s,;\"'&}]+)")
_COORD = re.compile(r"(?<![\d.])-?(?:(?:[1-8]\d|90)\.\d{4,}|\d{1,3}\.\d{6,})(?![\d])")   # 59.3345 / 18.068532, inte priser som 0.62675
_SERIAL = re.compile(r"\b(?=[A-Z0-9]*\d)(?=[A-Z0-9]*[A-Z])[A-Z0-9]{8,20}\b")
_HOST = re.compile(r"\b(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+(?:se|com|net|org|io|local|lan|home|arpa|nu|eu|de|"
                   r"dk|no|fi|nl|uk|info|app|dev|cloud|duckdns\.org|ui\.nabu\.casa|nabu\.casa)\b", re.I)
_PATH = re.compile(r"(?:/home|/var|/opt|/data|/usr|/tmp|/config|/root|/media|/share|/mnt|[A-Z]:\\\\?)[/\\][^\s\"']+")
_MOBILE = re.compile(r"\bmobile_app_[a-z0-9_]+\b", re.I)

# Slutkontrollen: syns något av detta efter saneringen tas hela raden bort
_LEAK = [re.compile(p, re.I) for p in (r"://", r"@[\w-]+\.", r"\b\d{1,3}(?:\.\d{1,3}){3}\b", r"\beyJ", r"\bghp_",
                                       r"\bmobile_app_", r"\b[0-9a-f]{32,}\b")]

_words: dict = {"at": 0.0, "list": []}


def _add(out: list, value, label: str = "<namn>", min_len: int = 3) -> None:
    if value is None:
        return
    s = str(value).strip()
    if len(s) >= min_len and s.lower() not in ("home", "hemma", "unknown", "none", "true", "false"):
        out.append((s, label))


def sensitive_words(refresh_s: float = 3600) -> list:
    """[(ord, ersättning)] för just det här huset: namn och adresser ur Home Assistant och inställningarna."""
    if _words["list"] and time.time() - _words["at"] < refresh_s:
        return _words["list"]
    out: list = []
    try:
        import homeassistant
        import requests
        if not homeassistant.configured():
            raise RuntimeError("HA inte kopplat")
        cfg = requests.get(f"{homeassistant._BASE}/config", headers=homeassistant._HEADERS, timeout=5,
                           verify=homeassistant._VERIFY).json() or {}
        _add(out, cfg.get("location_name"), "<plats>")
        for k in ("external_url", "internal_url"):
            _add(out, cfg.get(k), "<adress>")
        for k in ("latitude", "longitude"):
            if cfg.get(k) is not None:
                _add(out, f"{float(cfg[k]):.4f}"[:-1], "<koordinat>", 4)      # även kortare avrundningar
        states = requests.get(f"{homeassistant._BASE}/states", headers=homeassistant._HEADERS, timeout=10,
                              verify=homeassistant._VERIFY).json() or []
        for s in states:
            e = str(s.get("entity_id", ""))
            a = s.get("attributes") or {}
            if e.startswith(("person.", "zone.", "device_tracker.")):
                _add(out, a.get("friendly_name"))
                _add(out, e.split(".", 1)[1].replace("_", " "))
                if e.startswith("person.") and a.get("user_id"):
                    _add(out, a.get("user_id"), "<id>")
            if e.startswith(("person.", "zone.")) and a.get("latitude") is not None:
                _add(out, f"{float(a['latitude']):.3f}", "<koordinat>", 4)
                _add(out, f"{float(a.get('longitude') or 0):.3f}", "<koordinat>", 4)
    except Exception:
        pass
    try:
        import ew_settings
        for v in (ew_settings.get("phones") or {}).values():
            _add(out, v)
        _add(out, ew_settings.get("notify_target"))
        _add(out, ew_settings.get("ha_url"), "<adress>")
    except Exception:
        pass
    try:
        import os
        _add(out, os.environ.get("HA_URL"), "<adress>")
        _add(out, os.environ.get("HA_IP"), "<ip>")
        _add(out, os.environ.get("GUEST_USER"))
        for pair in (os.environ.get("EW_USERS") or "").split(","):
            _add(out, pair.split(":", 1)[0])
        import house_config
        hc = house_config.load_house_config(os.environ.get("HOUSE_CONFIG_PATH", "/house_config.yaml")) or {}
        _add(out, hc.get("house_id"))
        for n, ev in enumerate(hc.get("evs") or [], 1):           # bilarna hålls isär: <bil 1>, <bil 2>
            _add(out, ev.get("name"), f"<bil {n}>")
    except Exception:
        pass
    # längst först, så att "Emils Tesla" byts före "Emil"
    seen, uniq = set(), []
    for w, lab in sorted(out, key=lambda x: -len(x[0])):
        if w.lower() not in seen:
            seen.add(w.lower())
            uniq.append((w, lab))
    _words.update(at=time.time(), list=uniq)
    return uniq


def scrub_line(line: str, words: list | None = None) -> str:
    t = str(line or "")
    for w, lab in (words or []):
        pat = re.escape(w)
        if w[0].isalnum():
            pat = r"(?<!\w)" + pat
        if w[-1].isalnum():
            pat = pat + r"(?!\w)"
        t = re.sub(pat, lab, t, flags=re.I)
    t = _URL.sub("<adress>", t)
    t = _EMAIL.sub("<e-post>", t)
    t = _JWT.sub("<hemlighet>", t)
    t = _BEARER.sub(lambda m: m.group(1) + " <hemlighet>", t)
    t = _PREFIXED.sub("<hemlighet>", t)
    t = _KEYVAL.sub(lambda m: m.group(1) + m.group(2) + "<dolt>", t)
    t = _MAC.sub("<mac>", t)
    t = _IPV4.sub("<ip>", t)
    t = _IPV6.sub("<ip>", t)
    t = _MOBILE.sub("<telefon>", t)
    t = _ENTITY.sub(lambda m: m.group(1).lower() + ".<…>", t)
    t = _HOST.sub("<värd>", t)
    t = _PATH.sub("<sökväg>", t)
    t = _LONGHEX.sub("<hemlighet>", t)
    t = _LONGB64.sub("<hemlighet>", t)
    t = _COORD.sub("<koordinat>", t)
    t = _SERIAL.sub("<serienr>", t)
    if any(p.search(t) for p in _LEAK):
        return REMOVED
    return t


def scrub(text: str, words: list | None = None, max_line: int = 600) -> str:
    return "\n".join(scrub_line(ln[:max_line], words) for ln in str(text or "").splitlines())
