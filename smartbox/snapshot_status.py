"""Bounded, sanitized snapshot diagnostics shared by engine and owner UI.

Database publication runs independently of both control and the storage writer.
An unavailable publisher/database becomes unknown in the reader, never healthy.
"""
import json
import math
import threading
import time
from uuid import UUID

DEVICE = 'plan_snapshot_status'
STATES = {'disabled','waiting','queued','saving','failed','saved'}
_lock = threading.Lock()
_thread = None


def write(report):
    import logger
    with logger.get_db() as conn, conn.cursor() as cur:
        cur.execute("SET LOCAL statement_timeout = '2s'")
        cur.execute("INSERT INTO overrides (device,mode,updated_at) VALUES (%s,%s,NOW()) "
                    "ON CONFLICT (device) DO UPDATE SET mode=EXCLUDED.mode,updated_at=NOW()",
                    (DEVICE,json.dumps(report,allow_nan=False)))


class Publisher:
    def __init__(self,source,sink):
        self.source,self.sink=source,sink
        self.previous=None;self.sent_at=0

    def tick(self,now):
        try:
            report=self.source()
            if report==self.previous and 0<=now-self.sent_at<60:return False
            self.sink({**report,'reported_at':now})
            self.previous=dict(report);self.sent_at=now
            return True
        except Exception:
            return False  # Retry only status publication; never a snapshot/device command.


def start():
    global _thread
    import plan_snapshot
    with _lock:
        if _thread is not None:return
        publisher=Publisher(plan_snapshot.status,write)
        def run():
            while True:
                publisher.tick(time.time())
                time.sleep(5)
        _thread=threading.Thread(target=run,name='snapshot-status',daemon=True)
        try:
            _thread.start()
        except Exception:
            _thread=None


def decode(raw,now=None):
    """Allowlist bounded numeric diagnostics; reject missing/stale/future reports."""
    unknown={'state':'unknown','fresh':False}
    now=time.time() if now is None else now
    try:
        if not isinstance(raw,str) or len(raw)>4096:return unknown
        report=json.loads(raw)
        if type(report['schema']) is not int or report['schema']!=1 or report['state'] not in STATES:return unknown
        session=str(UUID(report['session']))
        numbers={}
        for key in ('failed','dropped','pending'):
            value=report[key]
            if isinstance(value,bool) or not isinstance(value,int) or not 0<=value<=2**53-1:return unknown
            numbers[key]=value
        stamps={}
        for key in ('reported_at','last_saved_at','last_failure_at'):
            value=report[key]
            if value is not None and (isinstance(value,bool) or not isinstance(value,(int,float))
                                     or not math.isfinite(value) or not 0<=value<=now+5):return unknown
            stamps[key]=value
        if stamps['reported_at'] is None or now-stamps['reported_at']>90:return unknown
        return {'schema':1,'session':session,'state':report['state'],'fresh':True,**numbers,**stamps}
    except (ValueError,KeyError,TypeError,AttributeError):
        return unknown


def read(connection):
    from sqlalchemy import text
    row=connection.execute(text('SELECT mode FROM overrides WHERE device=:device'),{'device':DEVICE}).first()
    return decode(row[0] if row else None)
