"""lua_host.py - kör Sourcefuls FTW-drivrutiner (srcfl/device-drivers, Lua, AGPL-3.0 som EnergyWizard, med deras OK)
i EnergyWizard.

En drivrutin är en Lua-fil med PROTOCOL, driver_init(config), driver_poll() och ev. driver_command(). Den pratar
med enheten genom ett `host`-objekt (spec/host-api.md i deras repo). Här implementeras det API:et i Python:

  host.modbus_read(addr, count, kind)   Modbus TCP (pymodbus), "holding"/"input", 1-indexerad tabell eller nil, fel
  host.modbus_write / write / write_registers   SKRIVNING - avstängd om inte allow_write=True (läs först, styr sen)
  host.http_get(url)                    HTTP GET (requests), ger kroppen som sträng
  host.emit(der_type, data)             telemetri: "pv", "battery", "meter", "inverter", "v2x_charger", "vehicle"
  host.emit_metric(name, value, unit)   diagnostikvärden
  host.decode_* / host.scale / host.json_decode, host.log, host.now_ms/unix_ms/sleep, host.set_make/model/sn ...

LuaDriver.poll() kör en driver_poll() och returnerar det senaste som emittats per DER-typ med FTW:s fältnamn (t.ex.
pv.w, battery.w/soc, meter.w). Tecken och enheter följer Sourcefuls datamodell; omslagen i drivers/*_ftw.py översätter
till EnergyWizards gränssnitt.
"""
import json
import os
import struct
import threading
import time

FTW_DIR = os.path.join(os.path.dirname(__file__), "ftw_drivers")


class LuaDriver:
    def __init__(self, path, host=None, port=502, unit_id=1, config=None, allow_write=False, timeout=3.0, log=print,
                 secrets=None, on_secret=None):
        from lupa import LuaRuntime
        self.path, self.allow_write, self._log = path, bool(allow_write), log
        self.emits, self.metrics, self.info = {}, {}, {}
        self.secrets, self._on_secret = dict(secrets or {}), (on_secret or (lambda k, v: None))
        self._mqtt, self._mqtt_buf, self._ws, self._ws_buf, self._tcp, self._http_s = None, [], None, [], None, None
        self._cfg_raw = dict(config or {})
        self._lock = threading.Lock()
        self._mb = None
        self._mb_args = (host, int(port), int(unit_id), float(timeout))
        self.L = LuaRuntime(unpack_returned_tuples=True, register_eval=False)
        g = self.L.globals()
        # Sandbox: inga filer, processer eller laddning av annan kod från drivrutinen
        for name in ("os", "io", "dofile", "loadfile", "require", "package", "debug"):
            g[name] = None
        g.host = self._host_table()
        src = open(path, encoding="utf-8").read()
        self.L.execute(src)
        self.protocol = str(g.PROTOCOL or "")
        drv = g.DRIVER
        self.meta = {k: drv[k] for k in ("id", "name", "manufacturer", "version") if drv is not None and drv[k] is not None} if drv else {}
        cfg = {"sn": "", "type": "lua", "profile": "", "host": host, "port": int(port), "unit_id": int(unit_id),
               "gateway_serial": "energywizard", "ders": self.L.table()}
        cfg.update(config or {})
        self._cfg = self.L.table_from(cfg, recursive=True)
        if g.driver_init is not None:
            g.driver_init(self._cfg)

    # ---- host-API ----------------------------------------------------------------------------------------------
    def _host_table(self):
        L = self.L
        t = L.table()
        # host.log(msg) eller host.log(nivå, msg) - FTW använder båda formerna
        t.log = lambda *a: self._log(f"🔌 [{os.path.basename(self.path)}] {' '.join(str(x) for x in a)}")
        t.now_ms = t.millis = lambda: int(time.monotonic() * 1000)
        t.unix_ms = lambda: int(time.time() * 1000)
        t.sleep = lambda ms: time.sleep(min(float(ms or 0), 5000) / 1000.0)
        for k in ("make", "model", "sn", "rated_w", "warmup_s", "poll_interval"):
            t[f"set_{k}"] = (lambda key: (lambda v: self.info.__setitem__(key, v)))(k)
        t.set_device_fault = lambda faulted, reason=None: self.info.__setitem__("fault", (bool(faulted), reason))
        t.site_location = lambda: None
        t.emit = self._emit
        t.emit_metric = lambda name, value, unit=None: self.metrics.__setitem__(str(name), (value, unit))
        t.modbus_read = self._modbus_read
        t.modbus_write = t.write = lambda addr, val: self._modbus_write(addr, [val])
        t.modbus_write_multi = t.write_registers = lambda addr, vals: self._modbus_write(addr, list(vals.values()) if hasattr(vals, "values") else list(vals))
        t.http_get = self._http_get
        t.http_post = lambda url, body=None, ctype=None: self._http("POST", url, body, ctype)
        t.http_patch = lambda url, body=None, headers=None: self._http("PATCH", url, body, headers)
        t.http_request = lambda method, url, body=None, headers=None: self._http(str(method).upper(), url, body, headers)
        t.http_cookies_clear = lambda: self._session().cookies.clear()
        t.json_encode = lambda v: json.dumps(self._to_py(v), ensure_ascii=False)
        t.mqtt_subscribe = self._mqtt_subscribe
        t.mqtt_messages = self._mqtt_messages
        t.mqtt_publish = self._mqtt_publish
        t.ws_open, t.ws_send, t.ws_messages, t.ws_is_open, t.ws_close = self._ws_open, self._ws_send, self._ws_messages, self._ws_is_open, self._ws_close
        t.tcp_open, t.tcp_recv, t.tcp_is_open, t.tcp_close = self._tcp_open, self._tcp_recv, self._tcp_is_open, self._tcp_close
        t.serial_read = lambda *a: (None, "ingen serieport i EnergyWizard (P1 läses via Home Assistant)")
        t.serial_available = lambda: 0
        t.aes_gcm_decrypt = self._aes_gcm
        t.set_watchdog_timeout_s = lambda v: self.info.__setitem__("watchdog_s", v)
        t.persist_secret = lambda k, v: (self.secrets.__setitem__(str(k), str(v)), self._on_secret(str(k), str(v)), True)[-1]
        t.reserve_vehicle_wake = lambda *a: False          # EnergyWizard väcker bilar själv (smartbox/main.py)
        t.decode_i16 = lambda v: struct.unpack(">h", struct.pack(">H", int(v) & 0xFFFF))[0]
        t.decode_u16 = lambda v: int(v) & 0xFFFF
        t.decode_u32_be = lambda hi, lo: ((int(hi) & 0xFFFF) << 16) | (int(lo) & 0xFFFF)
        t.decode_i32_be = lambda hi, lo: struct.unpack(">i", struct.pack(">I", ((int(hi) & 0xFFFF) << 16) | (int(lo) & 0xFFFF)))[0]
        t.decode_u32_le = lambda lo, hi: ((int(hi) & 0xFFFF) << 16) | (int(lo) & 0xFFFF)
        t.decode_i32_le = lambda lo, hi: struct.unpack(">i", struct.pack(">I", ((int(hi) & 0xFFFF) << 16) | (int(lo) & 0xFFFF)))[0]
        t.decode_f32_be = lambda hi, lo: struct.unpack(">f", struct.pack(">HH", int(hi) & 0xFFFF, int(lo) & 0xFFFF))[0]
        t.decode_f32 = t.decode_f32_be
        t.decode_u32 = t.decode_u32_be
        t.decode_u64 = lambda a, b, c, d: (int(a) << 48) | (int(b) << 32) | (int(c) << 16) | int(d)
        t.decode_string = self._decode_string
        t.scale = lambda v, sf: float(v) * (10 ** max(-10, min(10, int(sf))))
        t.json_decode = self._json_decode
        return t

    def _to_py(self, v):
        if v is None or isinstance(v, (int, float, str, bool)):
            return v
        try:
            keys = list(v.keys())
        except Exception:
            return v
        if keys and all(isinstance(k, int) for k in keys) and sorted(keys) == list(range(1, len(keys) + 1)):
            return [self._to_py(v[k]) for k in sorted(keys)]
        return {str(k): self._to_py(v[k]) for k in keys}

    def _emit(self, der_type, data):
        with self._lock:
            self.emits[str(der_type)] = self._to_py(data) or {}

    def _client(self):
        if self._mb is None:
            from pymodbus.client import ModbusTcpClient
            host, port, _unit, timeout = self._mb_args
            self._mb = ModbusTcpClient(host, port=port, timeout=timeout)
        if not self._mb.connected:
            self._mb.connect()
        return self._mb

    def _modbus_read(self, addr, count, kind="holding"):
        try:
            c = self._client()
            unit = self._mb_args[2]
            fn = c.read_input_registers if str(kind) == "input" else c.read_holding_registers
            try:
                r = fn(int(addr), count=int(count), device_id=unit)
            except TypeError:                                   # äldre pymodbus
                r = fn(int(addr), count=int(count), slave=unit)
            if r.isError():
                return None, f"modbus fel {r}"
            return self.L.table_from(list(r.registers))
        except Exception as e:
            try:
                self._mb.close()
            except Exception:
                pass
            return None, f"{type(e).__name__}: {e}"

    def _modbus_write(self, addr, values):
        if not self.allow_write:
            self._log(f"🔒 [{os.path.basename(self.path)}] skrivning till register {addr} stoppad (läsläge)")
            return "skrivning avstängd (läsläge)"
        try:
            c = self._client()
            unit = self._mb_args[2]
            vals = [int(v) & 0xFFFF for v in values]
            try:
                r = c.write_registers(int(addr), vals, device_id=unit) if len(vals) > 1 else c.write_register(int(addr), vals[0], device_id=unit)
            except TypeError:
                r = c.write_registers(int(addr), vals, slave=unit) if len(vals) > 1 else c.write_register(int(addr), vals[0], slave=unit)
            return f"modbus fel {r}" if r.isError() else None
        except Exception as e:
            return f"{type(e).__name__}: {e}"

    def _session(self):
        if self._http_s is None:
            import requests
            self._http_s = requests.Session()
        return self._http_s

    def _http_get(self, url):
        """Kroppen som sträng vid 2xx, annars nil, fel (spec/host-api.md)."""
        try:
            r = self._session().get(str(url), timeout=max(self._mb_args[3], 5))
            return r.text if r.ok else (None, f"HTTP {r.status_code}")
        except Exception as e:
            return None, str(e)

    _AUTH_URL = ("login", "token", "auth", "oauth", "session", "signin")

    def _http(self, method, url, body=None, extra=None):
        """POST/PATCH/annat. Skrivande anrop stoppas i läsläge - utom inloggning (token/auth i adressen)."""
        u = str(url)
        if method not in ("GET", "HEAD") and not self.allow_write and not any(k in u.lower() for k in self._AUTH_URL):
            self._log(f"🔒 [{os.path.basename(self.path)}] {method} {u.split('?')[0]} stoppad (läsläge)")
            return None, "skrivning avstängd (läsläge)"
        headers = {}
        ex = self._to_py(extra) if extra is not None and not isinstance(extra, str) else extra
        if isinstance(ex, dict):
            headers.update({str(k): str(v) for k, v in ex.items()})
        elif isinstance(ex, str):
            headers["Content-Type"] = ex
        if isinstance(body, str) and body[:1] in "{[" and "Content-Type" not in headers:
            headers["Content-Type"] = "application/json"
        data = body if body is None or isinstance(body, (str, bytes)) else json.dumps(self._to_py(body))
        try:
            r = self._session().request(method, u, data=data, headers=headers, timeout=max(self._mb_args[3], 5))
            return r.text if r.ok else (None, f"HTTP {r.status_code}: {r.text[:200]}")
        except Exception as e:
            return None, str(e)

    # ---- MQTT (paho) ----------------------------------------------------------------------------------------------
    def _mqtt_client(self):
        if self._mqtt is None:
            import paho.mqtt.client as mqtt
            c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"energywizard-{os.path.basename(self.path)}-{os.getpid()}")
            u, pw = self._cfg_raw.get("username"), self._cfg_raw.get("password")
            if u:
                c.username_pw_set(str(u), str(pw or ""))
            c.on_message = lambda _c, _u, m: self._mqtt_buf.append({
                "topic": m.topic, "payload": m.payload.decode("utf-8", "replace"),
                # Retained broker state is not a newly measured sample.
                "received_at": None if m.retain else time.time(),
            })
            port = int(self._cfg_raw.get("mqtt_port") or (self._mb_args[1] if self._mb_args[1] != 502 else 1883))
            c.connect(self._mb_args[0], port, keepalive=30)
            c.loop_start()
            self._mqtt = c
        return self._mqtt

    def _mqtt_subscribe(self, topic):
        try:
            return self._mqtt_client().subscribe(str(topic))[0] == 0
        except Exception as e:
            self._log(f"⚠️ [{os.path.basename(self.path)}] MQTT: {e}")
            return False

    def _mqtt_messages(self):
        buf, self._mqtt_buf = self._mqtt_buf, []
        return self.L.table_from(buf, recursive=True)

    def _mqtt_publish(self, topic, payload):
        if not self.allow_write:
            self._log(f"🔒 [{os.path.basename(self.path)}] MQTT publish till {topic} stoppad (läsläge)")
            return False
        import shadow
        if shadow.active():
            # Poll/cleanup can publish outside FtwDevice.command. Do not expose
            # payloads, topics or credentials in the shadow log.
            shadow.record("FTW MQTT publish", os.path.basename(self.path))
            return True
        try:
            return self._mqtt_client().publish(str(topic), str(payload)).rc == 0
        except Exception:
            return False

    # ---- WebSocket / TCP / krypto ----------------------------------------------------------------------------------
    def _ws_open(self, url, headers=None):
        try:
            import websocket                                     # websocket-client
        except ImportError:
            return None, "websocket-client saknas"
        try:
            h = self._to_py(headers) if headers is not None else {}
            self._ws = websocket.create_connection(str(url), header=[f"{k}: {v}" for k, v in (h or {}).items()], timeout=5)
            self._ws.settimeout(0.05)
            return True
        except Exception as e:
            return None, str(e)

    def _ws_send(self, data):
        try:
            self._ws.send(str(data))
            return True
        except Exception as e:
            return None, str(e)

    def _ws_messages(self):
        out = []
        while self._ws is not None:
            try:
                out.append(self._ws.recv())
            except Exception:
                break
        return self.L.table_from(out)

    def _ws_is_open(self):
        return bool(self._ws is not None and getattr(self._ws, "connected", False))

    def _ws_close(self):
        try:
            if self._ws is not None:
                self._ws.close()
        finally:
            self._ws = None

    def _tcp_open(self, addr):
        import socket
        try:
            h, _, p = str(addr).rpartition(":")
            self._tcp = socket.create_connection((h or self._mb_args[0], int(p)), timeout=5)
            self._tcp.settimeout(0.05)
            return True
        except Exception as e:
            return None, str(e)

    def _tcp_recv(self, n=4096):
        try:
            return self._tcp.recv(int(n or 4096)).decode("latin-1")
        except Exception:
            return ""

    def _tcp_is_open(self):
        return self._tcp is not None

    def _tcp_close(self):
        try:
            if self._tcp is not None:
                self._tcp.close()
        finally:
            self._tcp = None

    def _aes_gcm(self, key, iv, ct, aad="", tag=""):
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        except ImportError:
            return None, "cryptography saknas"
        try:
            b = lambda x: x.encode("latin-1") if isinstance(x, str) else bytes(x)
            return AESGCM(b(key)).decrypt(b(iv), b(ct) + b(tag), b(aad) or None).decode("latin-1")
        except Exception as e:
            return None, str(e)

    def _decode_string(self, regs, start, count):
        regs = self._to_py(regs) or []
        out = b""
        for i in range(int(start), int(start) + int(count)):
            v = regs[i - 1] if 0 < i <= len(regs) else 0
            out += struct.pack(">H", int(v) & 0xFFFF)
        return out.split(b"\x00")[0].decode("ascii", "replace").strip()

    def _json_decode(self, s):
        try:
            return self.L.table_from(json.loads(s), recursive=True)
        except Exception as e:
            return None, str(e)

    # ---- drivrutinens livscykel --------------------------------------------------------------------------------
    def poll(self):
        """Kör en driver_poll(). Returnerar (emits, nästa_intervall_ms)."""
        nxt = self.L.globals().driver_poll()
        with self._lock:
            return dict(self.emits), (int(nxt) if isinstance(nxt, (int, float)) and nxt > 0 else 5000)

    def command(self, action, power_w=0, cmd=None):
        f = self.L.globals().driver_command
        if f is None:
            return False
        return bool(f(action, power_w, self.L.table_from(cmd or {}, recursive=True)))

    def close(self):
        try:
            f = self.L.globals().driver_cleanup
            if f is not None:
                f()
        finally:
            if self._mb is not None:
                self._mb.close()
            if self._mqtt is not None:
                self._mqtt.loop_stop()
                self._mqtt.disconnect()
            self._ws_close()
            self._tcp_close()
