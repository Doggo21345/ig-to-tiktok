"""Send one Instagram video to TikTok drafts.

Runs on a schedule (see .github/workflows/repost.yml). Each run:
  1. Checks whether a posting time (9am, 1pm, 7pm Pacific by default) is due.
  2. Picks the next Instagram video that has not been sent yet.
  3. Uploads it to your TikTok inbox, where you tap to finish the post.
  4. Records it in posted.json so it is never sent twice.

Run with --force to send one video right now, ignoring the schedule.
"""

import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

# ---- Settings you can change (or override with environment variables) ----
TZ = ZoneInfo(os.getenv("POST_TIMEZONE", "America/Los_Angeles"))
POST_HOURS = [int(h) for h in os.getenv("POST_HOURS", "9,13,19").split(",")]
ORDER = os.getenv("POST_ORDER", "oldest_first")  # or "newest_first"

STATE_FILE = Path(__file__).with_name("posted.json")
IG = "https://graph.instagram.com"
TT = "https://open.tiktokapis.com"
MB = 1024 * 1024


class PendingLimit(Exception):
    """TikTok already has 5 videos waiting for you to post."""


# ---------------------------- schedule ----------------------------
def due_slot(now, done):
    """Return the key of a posting time that is due and not yet handled."""
    for hour in POST_HOURS:
        start = now.replace(hour=hour, minute=0, second=0, microsecond=0)
        if start <= now < start + timedelta(hours=2):
            key = f"{now:%Y-%m-%d}-{hour:02d}"
            if key not in done:
                return key
    return None


# ---------------------------- secrets ----------------------------
def save_secret(name, value):
    """Store a renewed token back into the GitHub repo's secrets."""
    pat, repo = os.getenv("GH_PAT"), os.getenv("GITHUB_REPOSITORY")
    if not (pat and repo):
        print(f"WARNING: {name} was renewed but could not be saved (no GH_PAT).")
        return False
    subprocess.run(
        ["gh", "secret", "set", name, "--repo", repo],
        input=value, text=True, check=True, env={**os.environ, "GH_TOKEN": pat},
    )
    print(f"Saved renewed {name}.")
    return True


# ---------------------------- Instagram ----------------------------
def refresh_instagram_token(token):
    """Instagram tokens last 60 days. Renewing keeps them alive."""
    try:
        r = requests.get(
            f"{IG}/refresh_access_token",
            params={"grant_type": "ig_refresh_token", "access_token": token},
            timeout=30,
        )
        new = r.json().get("access_token")
        if r.ok and new and new != token:
            save_secret("INSTAGRAM_ACCESS_TOKEN", new)
            return new
    except Exception as e:  # renewing is best effort
        print(f"Could not renew Instagram token this run: {e}")
    return token


def list_instagram_videos(token):
    videos = []
    url = f"{IG}/me/media"
    params = {
        "fields": "id,caption,media_type,media_product_type,media_url,permalink,timestamp",
        "limit": 50,
        "access_token": token,
    }
    while url:
        r = requests.get(url, params=params, timeout=60)
        data = r.json()
        if "error" in data:
            raise RuntimeError(f"Instagram error: {data['error'].get('message')}")
        for item in data.get("data", []):
            # media_url is missing when Instagram blocks download (e.g. licensed music)
            if item.get("media_type") == "VIDEO" and item.get("media_url"):
                videos.append(item)
        url = data.get("paging", {}).get("next")
        params = None  # the "next" link already includes everything
    videos.sort(key=lambda v: v["timestamp"], reverse=(ORDER == "newest_first"))
    return videos


def download(url, path):
    with requests.get(url, stream=True, timeout=300) as r:
        r.raise_for_status()
        with open(path, "wb") as f:
            for block in r.iter_content(MB):
                f.write(block)


# ---------------------------- TikTok ----------------------------
def tiktok_access_token():
    """Trade the long-lived refresh token for a fresh 24-hour access token."""
    old = os.environ["TIKTOK_REFRESH_TOKEN"]
    r = requests.post(
        f"{TT}/v2/oauth/token/",
        data={
            "client_key": os.environ["TIKTOK_CLIENT_KEY"],
            "client_secret": os.environ["TIKTOK_CLIENT_SECRET"],
            "grant_type": "refresh_token",
            "refresh_token": old,
        },
        timeout=30,
    )
    data = r.json()
    if "access_token" not in data:
        raise RuntimeError(
            f"TikTok login failed: {data.get('error_description') or data}. "
            "You may need to run get_tiktok_token.py again."
        )
    new = data.get("refresh_token")
    if new and new != old:
        save_secret("TIKTOK_REFRESH_TOKEN", new)
    return data["access_token"]


def chunk_plan(size):
    """Return (chunk_size, chunk_count) following TikTok's upload rules."""
    if size <= 64 * MB:
        return size, 1  # small enough to send in one piece
    chunk = 10 * MB
    return chunk, size // chunk  # last piece carries the leftover bytes


def upload_to_tiktok_inbox(access_token, path):
    size = os.path.getsize(path)
    chunk, count = chunk_plan(size)
    r = requests.post(
        f"{TT}/v2/post/publish/inbox/video/init/",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json; charset=UTF-8",
        },
        json={"source_info": {
            "source": "FILE_UPLOAD",
            "video_size": size,
            "chunk_size": chunk,
            "total_chunk_count": count,
        }},
        timeout=60,
    )
    body = r.json()
    code = body.get("error", {}).get("code")
    if code == "spam_risk_too_many_pending_share":
        raise PendingLimit()
    if code != "ok":
        raise RuntimeError(f"TikTok refused the upload: {body.get('error')}")
    upload_url = body["data"]["upload_url"]
    publish_id = body["data"]["publish_id"]

    with open(path, "rb") as f:
        for i in range(count):
            first = i * chunk
            last = size - 1 if i == count - 1 else first + chunk - 1
            f.seek(first)
            piece = f.read(last - first + 1)
            for attempt in range(3):
                put = requests.put(
                    upload_url,
                    data=piece,
                    headers={
                        "Content-Type": "video/mp4",
                        "Content-Range": f"bytes {first}-{last}/{size}",
                    },
                    timeout=600,
                )
                if put.status_code in (201, 206):
                    break
                if put.status_code < 500 or attempt == 2:
                    raise RuntimeError(
                        f"Upload piece {i + 1}/{count} failed: "
                        f"{put.status_code} {put.text[:300]}"
                    )
                time.sleep(5)
    return publish_id


def wait_for_tiktok(access_token, publish_id):
    """Check that TikTok finished handling the video. Problems here are only logged."""
    for _ in range(12):
        time.sleep(10)
        try:
            r = requests.post(
                f"{TT}/v2/post/publish/status/fetch/",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json; charset=UTF-8",
                },
                json={"publish_id": publish_id},
                timeout=30,
            )
            data = r.json().get("data", {})
        except Exception as e:
            print(f"Status check problem: {e}")
            continue
        status = data.get("status")
        print(f"TikTok status: {status}")
        if status in ("SEND_TO_USER_INBOX", "PUBLISH_COMPLETE"):
            return True
        if status == "FAILED":
            raise RuntimeError(f"TikTok could not process the video: {data.get('fail_reason')}")
    return False


# ---------------------------- main ----------------------------
def main():
    force = "--force" in sys.argv
    state = json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {}
    posted = state.setdefault("posted", {})
    slots = state.setdefault("slots", [])

    now = datetime.now(TZ)
    slot = due_slot(now, slots)
    if not slot and not force:
        print(f"{now:%a %I:%M %p}: no posting time is due. Nothing to do.")
        return 0

    ig_token = os.environ["INSTAGRAM_ACCESS_TOKEN"]
    if slot and slot.endswith(f"-{min(POST_HOURS):02d}"):
        ig_token = refresh_instagram_token(ig_token)  # once a day

    todo = [v for v in list_instagram_videos(ig_token) if v["id"] not in posted]
    if not todo:
        print("Every Instagram video has already been sent. Nothing to do.")
        return 0
    video = todo[0]
    print(f"Sending {video['permalink']} ({len(todo) - 1} left after this one)")

    access = tiktok_access_token()
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "video.mp4")
        download(video["media_url"], path)
        try:
            publish_id = upload_to_tiktok_inbox(access, path)
        except PendingLimit:
            print("TikTok is holding 5 videos you have not posted yet. "
                  "Open TikTok, post or delete them, and the next run will continue.")
            return 1
    wait_for_tiktok(access, publish_id)

    posted[video["id"]] = {
        "permalink": video["permalink"],
        "caption": video.get("caption", ""),
        "sent_at": now.isoformat(timespec="seconds"),
    }
    if slot:
        slots.append(slot)
        state["slots"] = slots[-30:]
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n")
    print("Done. Open your TikTok inbox to finish the post.")
    print(f"Caption to paste:\n{video.get('caption', '')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
