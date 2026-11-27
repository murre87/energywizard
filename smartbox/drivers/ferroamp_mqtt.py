"""Explicit Ferroamp command channel. One publish, matching response AND result.

No telemetry inference, retry, transport fallback or physical-delivery claim.
Unfinished durable transactions block a restarted writer until operator recovery.
"""
import hashlib
import json
import math
import os
from pathlib import Path
import re
import threading
import time
import uuid


class CommandClient:
    TOPICS = ('extapi/control/response', 'extapi/control/result')

    def __init__(self, config, *, client_factory=None, journal_factory=None, identity=None):
        self.config = dict(config or {})
        self.host = self.config.get('host')
        self.port = self.config.get('port', 1883)
        self.timeout = self.config.get('timeout_s', 5)
        if (not isinstance(self.host, str) or not self.host.strip() or type(self.port) is not int
                or not 1 <= self.port <= 65535 or type(self.timeout) not in (int, float)
                or not math.isfinite(self.timeout) or not .1 <= self.timeout <= 10):
            raise ValueError('Explicit MQTT broker and bounded timeout required')
        for key in ('username_env', 'password_env'):
            if self.config.get(key) and (not isinstance(self.config[key], str)
                    or not re.fullmatch(r'[A-Z_][A-Z0-9_]*', self.config[key])):
                raise ValueError('Explicit credential environment name required')
        if self.config.get('password_env') and not self.config.get('username_env'):
            raise ValueError('Password requires a username environment name')
        if 'tls' in self.config and type(self.config['tls']) is not bool:
            raise ValueError('TLS must be boolean')
        from drivers.host import ew_settings
        self.path = self.config.get('journal_path') or str(Path(ew_settings.PATH).with_name('ferroamp-mqtt-command.json'))
        self.context = hashlib.sha256(json.dumps({'identity': identity, 'broker': {k: self.config.get(k) for k in
            ('host', 'port', 'username_env', 'password_env', 'tls', 'tls_ca')}}, sort_keys=True).encode()).hexdigest()
        self.factory, self.journal_factory = client_factory, journal_factory
        self.client = self.journal = self.pending = None
        self.ready = self.closed = self.blocked = False
        self.subscription = None
        self.condition = threading.Condition()
        self.serial = threading.Lock()
        self.protocol_acknowledged = False

    def _journal(self):
        if self.journal is not None:
            return not self.blocked
        try:
            if self.journal_factory is None:
                from drivers.host import Journal
                self.journal = Journal(self.path)
            else:
                self.journal = self.journal_factory(self.path)
            saved = self.journal.load()
            if saved and (saved.get('schema') != 1 or saved.get('context') != self.context
                          or saved.get('phase') != 'complete'):
                self.blocked = True
        except Exception:
            self.blocked = True
        return not self.blocked

    def _save(self, phase):
        try:
            self.journal.save({'schema': 1, 'context': self.context, 'phase': phase,
                               'transaction_id': self.pending['id'], 'at': time.time()})
            return True
        except Exception:
            self.blocked = True
            return False

    def start(self):
        """Connect/subscribe only. Does not open a journal or publish a command."""
        if self.client is not None or self.closed:
            return
        client = None
        try:
            if self.factory is None:
                import paho.mqtt.client as mqtt
                client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id='', protocol=mqtt.MQTTv311)
            else:
                client = self.factory()
            user = os.environ.get(self.config.get('username_env', ''))
            password = os.environ.get(self.config.get('password_env', ''))
            if ((self.config.get('username_env') and not user)
                    or (self.config.get('password_env') and not password)):
                raise ValueError('Configured credential unavailable')
            if user:
                client.username_pw_set(user, password)
            if self.config.get('tls') is True:
                client.tls_set(ca_certs=self.config.get('tls_ca'))
            client.on_connect = self._connect
            client.on_disconnect = self._disconnect
            client.on_subscribe = self._subscribed
            client.on_message = self._message
            self.client = client
            client.connect_async(self.host, self.port, 30)
            client.loop_start()
        except Exception:
            self.blocked = True
            if client:
                try:
                    client.disconnect()
                except Exception:
                    pass
                try:
                    client.loop_stop()
                except Exception:
                    pass

    def _connect(self, client, userdata, flags, reason, properties=None):
        with self.condition:
            self.ready = False
            self.subscription = None
            if reason == 0 and not self.closed:
                result, mid = client.subscribe([(topic, 0) for topic in self.TOPICS])
                if result == 0:
                    self.subscription = mid
            self.condition.notify_all()

    def _subscribed(self, client, userdata, mid, codes, properties=None):
        with self.condition:
            self.ready = (not self.closed and mid == self.subscription and len(codes) == 2
                          and all(not getattr(code, 'is_failure', False)
                                  and getattr(code, 'value', code) in (0, 1, 2) for code in codes))
            self.condition.notify_all()

    def _disconnect(self, *args):
        with self.condition:
            self.ready = False
            self.condition.notify_all()

    def _message(self, client, userdata, message):
        if message.topic not in self.TOPICS or message.retain or message.dup or len(message.payload) > 16384:
            return
        try:
            data = json.loads(message.payload)
            with self.condition:
                if (not self.ready or not self.pending or data.get('transId') != self.pending['id']
                        or data.get('status') not in ('ack', 'nak')):
                    return
                if data['status'] == 'nak':
                    self.pending['rejected'] = True
                else:
                    self.pending[message.topic] = True
                self.condition.notify_all()
        except (ValueError, TypeError, AttributeError):
            return

    def _done(self):
        return self.pending and (self.pending.get('rejected') or all(self.pending.get(t) for t in self.TOPICS))

    def request(self, name, watts=None):
        self.protocol_acknowledged = False
        if name not in ('auto', 'charge', 'discharge'):
            return False
        if name == 'auto':
            if watts is not None:
                return False
            command = {'name': name}
        else:
            if type(watts) not in (int, float) or not math.isfinite(watts) or watts <= 0:
                return False
            command = {'name': name, 'arg': format(watts, '.12g')}
        if not self.serial.acquire(blocking=False):
            return False
        try:
            if self.closed or self.blocked or not self._journal():
                return False
            with self.condition:
                if self.pending:
                    if not self._done():
                        return False  # Uncertain outcome: never resend or race an auto request.
                    accepted = not self.pending.get('rejected')
                    same = self.pending['command'] == command
                    if not accepted and name != 'auto':
                        return False  # Only a completed explicit release can clear rejection.
                    if not self._save('complete'):
                        return False
                    self.pending = None
                    if same:
                        self.protocol_acknowledged = accepted
                        return bool(accepted)
            self.start()
            deadline = time.monotonic()+self.timeout
            with self.condition:
                while not self.ready and not self.closed and not self.blocked:
                    remaining = deadline-time.monotonic()
                    if remaining <= 0:
                        return False
                    self.condition.wait(remaining)
                if not self.ready or self.closed or self.blocked:
                    return False
                self.pending = {'id': str(uuid.uuid4()), 'command': command}
                if not self._save('pending'):
                    return False
                try:
                    sent = self.client.publish('extapi/control/request', json.dumps(
                        {'transId': self.pending['id'], 'cmd': command}), qos=0, retain=False)
                    if sent.rc != 0:
                        return False  # Preserve pending journal even on uncertain queue failure.
                except Exception:
                    return False
                while not self._done() and self.ready and not self.closed:
                    remaining = deadline-time.monotonic()
                    if remaining <= 0:
                        return False
                    self.condition.wait(remaining)
                if not self._done() or self.pending.get('rejected'):
                    return False
                if not self._save('complete'):
                    return False
                self.pending = None
                self.protocol_acknowledged = True
                return True
        finally:
            self.serial.release()

    def close(self):
        with self.condition:
            self.closed = True
            self.ready = False
            self.condition.notify_all()
        if self.client:
            try:
                self.client.disconnect()
            finally:
                self.client.loop_stop()
        if self.journal is not None:
            self.journal.lock.close()
