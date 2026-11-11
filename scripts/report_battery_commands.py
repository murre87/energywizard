"""Read-only local command evidence; never resumes commands or contacts devices."""
import argparse
import json
from pathlib import Path
import sqlite3

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--database',default='/data/battery-commands.sqlite3')
    p.add_argument('--limit',type=int,default=100)
    args=p.parse_args()
    if not 1 <= args.limit <= 5000:p.error('Limit must be between 1 and 5000')
    uri=Path(args.database).resolve().as_uri()+'?mode=ro'
    with sqlite3.connect(uri,uri=True) as db:
        rows=db.execute('SELECT payload FROM command_events ORDER BY id DESC LIMIT ?',(args.limit,)).fetchall()
    print(json.dumps([json.loads(row[0]) for row in rows],indent=2))
