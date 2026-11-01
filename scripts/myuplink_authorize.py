#!/usr/bin/env python3
"""Engångs-verktyg: hämtar en första refresh_token för myUplink (NIBE/Bosch/
Atlantic/Daikin-värmepumpar via molnet, se smartbox/drivers/heatpump_myuplink.py).

myUplink kräver en webbläsarbaserad inloggning + samtycke EN gång - det går inte
att automatisera headless. Så här gör du:

1. Skapa en applikation på https://dev.myuplink.com (Client Identifier + Client
   Secret). Ange "https://localhost/callback" som redirect-URI där.
2. Kör det här skriptet: MYUPLINK_CLIENT_ID=... MYUPLINK_CLIENT_SECRET=... \
   python3 scripts/myuplink_authorize.py
3. Öppna länken skriptet skriver ut i en webbläsare, logga in, godkänn.
4. Webbläsaren hamnar på en sida som inte laddar (localhost/callback) - det är
   okej, kopiera bara "code"-parametern ur adressfältet och klistra in den när
   skriptet frågar.
5. Skriptet skriver ut en refresh_token - klistra in den som MYUPLINK_REFRESH_TOKEN
   i din .env.
"""
import os
import sys
import urllib.parse

import requests

CLIENT_ID = os.environ.get("MYUPLINK_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("MYUPLINK_CLIENT_SECRET", "")
REDIRECT_URI = os.environ.get("MYUPLINK_REDIRECT_URI", "https://localhost/callback")
SCOPE = "READSYSTEM WRITESYSTEM offline_access"


def main():
    if not (CLIENT_ID and CLIENT_SECRET):
        print("Sätt MYUPLINK_CLIENT_ID och MYUPLINK_CLIENT_SECRET (från dev.myuplink.com) först.")
        sys.exit(1)

    params = {
        "response_type": "code", "client_id": CLIENT_ID, "redirect_uri": REDIRECT_URI,
        "scope": SCOPE,
    }
    print("Öppna den här länken i en webbläsare, logga in och godkänn:\n")
    print(f"https://api.myuplink.com/oauth/authorize?{urllib.parse.urlencode(params)}\n")
    code = input("Klistra in 'code'-parametern från omdirigerings-URL:en: ").strip()

    r = requests.post("https://api.myuplink.com/oauth/token", data={
        "grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT_URI,
        "client_id": CLIENT_ID, "client_secret": CLIENT_SECRET,
    }, timeout=10)
    r.raise_for_status()
    d = r.json()
    print("\nKlart. Lägg till i .env:\n")
    print(f"MYUPLINK_CLIENT_ID={CLIENT_ID}")
    print(f"MYUPLINK_CLIENT_SECRET={CLIENT_SECRET}")
    print(f"MYUPLINK_REFRESH_TOKEN={d['refresh_token']}")


if __name__ == "__main__":
    main()
