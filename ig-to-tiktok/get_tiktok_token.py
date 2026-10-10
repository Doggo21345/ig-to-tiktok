"""One-time helper: connect your TikTok account and print the refresh token.

Run this once on your own computer:
    pip install requests
    python get_tiktok_token.py
"""

import secrets
from urllib.parse import parse_qs, urlencode, urlparse

import requests

client_key = input("TikTok client key: ").strip()
client_secret = input("TikTok client secret: ").strip()
redirect_uri = input("Redirect URI (exactly as entered in the TikTok app settings): ").strip()

state = secrets.token_urlsafe(8)
auth_url = "https://www.tiktok.com/v2/auth/authorize/?" + urlencode({
    "client_key": client_key,
    "scope": "video.upload",
    "response_type": "code",
    "redirect_uri": redirect_uri,
    "state": state,
})
print("\n1. Open this link, log in to TikTok and approve:\n")
print(auth_url)
print("\n2. You will land on your redirect page (it may look blank or broken, that is fine).")
landed = input("   Copy the full address from the browser bar and paste it here: ").strip()

params = parse_qs(urlparse(landed).query)
if params.get("state", [""])[0] != state:
    raise SystemExit("The pasted address does not match this login attempt. Try again.")
if "code" not in params:
    raise SystemExit(f"TikTok did not approve: {params.get('error_description', params)}")

r = requests.post(
    "https://open.tiktokapis.com/v2/oauth/token/",
    data={
        "client_key": client_key,
        "client_secret": client_secret,
        "code": params["code"][0],
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri,
    },
    timeout=30,
)
data = r.json()
if "refresh_token" not in data:
    raise SystemExit(f"Could not get a token: {data}")

print("\nSuccess. Save this as the GitHub secret TIKTOK_REFRESH_TOKEN:\n")
print(data["refresh_token"])
print(f"\nPermissions granted: {data.get('scope')}")
