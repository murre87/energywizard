"""Evidence-only command tracking. No retries, fallback writes or device authority."""
import json
import math
import os
from pathlib import Path
from queue import Queue
import sqlite3
import threading
import time
import uuid

_QUEUE = Queue(maxsize=64)
_LOCK = threading.Lock()
_WORKER = None
MAX_EVENTS = 5000
MAX_AGE_S = 30*86400


def finite(value):
    try:
        return not isinstance(value, bool) and math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def persist(event, path):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    # Open privately before SQLite touches the file. Parent is controlled by operator.
    fd=os.open(path,os.O_CREAT|os.O_WRONLY,0o600);os.close(fd)
    with sqlite3.connect(path,timeout=.2) as db:
        db.execute('CREATE TABLE IF NOT EXISTS command_events (id INTEGER PRIMARY KEY, at REAL, command_id TEXT, payload TEXT)')
        db.execute('INSERT INTO command_events(at,command_id,payload) VALUES (?,?,?)',
                   (event['at'],event['command_id'],json.dumps(event,allow_nan=False)))
        db.execute('DELETE FROM command_events WHERE at < ?', (time.time()-MAX_AGE_S,))
        db.execute('DELETE FROM command_events WHERE id NOT IN (SELECT id FROM command_events ORDER BY id DESC LIMIT ?)',(MAX_EVENTS,))


def _writer():
    while True:
        event,path=_QUEUE.get()
        try:persist(event,path)
        except Exception:pass
        finally:_QUEUE.task_done()


def enqueue(event):
    global _WORKER
    try:
        if os.environ.get('EW_BATTERY_COMMAND_TRACKING','1')=='0':return
        with _LOCK:
            if _WORKER is None:
                _WORKER=threading.Thread(target=_writer,name='battery-command-evidence',daemon=True)
                _WORKER.start()
        _QUEUE.put_nowait((dict(event),os.environ.get('EW_BATTERY_COMMAND_DB','/data/battery-commands.sqlite3')))
    except Exception:pass


class Tracker:
    def __init__(self,sink=enqueue,settle_s=120,fresh_s=90,tolerance_w=150,fraction=.2):
        self.sink=sink;self.settle_s=settle_s;self.fresh_s=fresh_s
        self.tolerance_w=tolerance_w;self.fraction=fraction
        self.current=None;self.last=None
        # Each process starts without command authority. Persisted history is never resumed.
        self.session_id=str(uuid.uuid4())

    def _emit(self,state,reason,now,**evidence):
        if self.current is None or (state,reason)==self.last:return
        self.last=(state,reason)
        event={**self.current,'session_id':self.session_id,'state':state,'reason':reason,'at':now,**evidence}
        try:self.sink(event)
        except Exception:pass

    def begin(self,intent,power_w,now):
        if self.current:
            self._emit('superseded','new_decision',now)
        self.current={'command_id':str(uuid.uuid4()),'intent':intent,
                      'requested_w':float(power_w) if finite(power_w) else None,'created_at':now}
        self.last=None
        self._emit('queued','awaiting_transport',now)
        return self.current['command_id']

    def sent(self,command_id,ok,now,reference_verified=False):
        if not self.current or command_id!=self.current['command_id']:return
        self.current['sent_at']=now
        self.current['accepted']=bool(ok)
        if not ok:self._emit('failed','transport_not_confirmed',now)
        else:self._emit('reference_verified' if reference_verified else 'sent',
                        'reference_readback' if reference_verified else 'transport_accepted',now)

    def observe(self,command_id,state,now,reserve_soc=None,max_soc=None):
        if not self.current or command_id!=self.current['command_id'] or not self.current.get('accepted'):return
        sent=self.current['sent_at'];stamp=state.get('power_sample_at');actual=state.get('power_w')
        if not finite(stamp) or not finite(actual) or not sent < float(stamp) <= now+5 or now-float(stamp)>self.fresh_s:
            self._emit('unconfirmed','fresh_post_send_measurement_unavailable',now);return
        intent=self.current['intent'];wanted=self.current['requested_w']
        soc=state.get('soc_pct')
        limited=(finite(soc) and ((intent=='charge' and finite(max_soc) and float(soc)>=float(max_soc)-1)
                                 or (intent=='discharge' and finite(reserve_soc) and float(soc)<=float(reserve_soc)+1)))
        if limited or intent=='auto':
            self._emit('unconfirmed','autonomous_or_soc_limited',now);return
        tolerance=max(self.tolerance_w,abs(wanted or 0)*self.fraction)
        if intent in ('charge','discharge'):
            if wanted is None or wanted<=0:
                self._emit('unconfirmed','target_power_unavailable',now);return
            target=wanted if intent=='charge' else -wanted
            follows=abs(float(actual)-target)<=tolerance
        elif intent=='idle':follows=abs(float(actual))<=self.tolerance_w
        elif intent=='hold':follows=float(actual)>=-self.tolerance_w
        else:
            self._emit('unconfirmed','unsupported_intent',now);return
        evidence={'actual_w':float(actual),'sample_at':float(stamp),'latency_s':max(0,float(stamp)-sent)}
        if follows:self._emit('physically_applied','measured_response_consistent',now,**evidence)
        elif now-sent>=self.settle_s:self._emit('failed','measured_response_outside_tolerance',now,**evidence)
        else:self._emit('unconfirmed','settling',now,**evidence)


def apply(tracker,driver,intent,power_w,now=None):
    """One existing driver call; tracking failures never change its return/exception."""
    now=time.time() if now is None else now
    try:command_id=tracker.begin(intent,power_w,now)
    except Exception:command_id=None
    try:ok=driver.apply_intent(intent,power_w)
    except Exception:
        try:tracker.sent(command_id,False,time.time())
        except Exception:pass
        raise
    try:
        import shadow
        if shadow.active():
            tracker.current['accepted']=False
            tracker._emit('unconfirmed','shadow_mode_no_physical_command',time.time())
        else:
            tracker.sent(command_id,ok,time.time(),getattr(driver,'command_reference_verified',False) is True)
    except Exception:pass
    return ok
