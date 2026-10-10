# Instagram to TikTok drafts

Three times a day (9am, 1pm, 7pm Pacific) this sends your next Instagram video
to your TikTok inbox. You open TikTok, tap the notification, paste the caption
and post. It runs for free on GitHub, so your computer can be off.

## What is in this folder

- `repost.py` - the script that moves one video per run
- `get_tiktok_token.py` - run once to connect your TikTok account
- `.github/workflows/repost.yml` - the schedule
- `posted.json` - the list of videos already sent (updates itself)

## Setup (about 45 minutes, one time)

### 1. Put this folder on GitHub

Create a new **private** repository and upload everything in this folder,
including the hidden `.github` folder.

### 2. Get an Instagram token

1. Your Instagram must be a Creator or Business account
   (Instagram app > Settings > Account type and tools).
2. Go to developers.facebook.com, create an app, and add the
   **Instagram** product ("API setup with Instagram login").
3. Add your Instagram account there and click **Generate token**.
4. Copy the token. This is `INSTAGRAM_ACCESS_TOKEN`.

### 3. Create a TikTok app

1. Go to developers.tiktok.com and create an app.
2. Add the **Content Posting API** product and the **Login Kit** product.
3. Ask for the `video.upload` permission.
4. Under Login Kit, set a redirect URI. Any https page you control works,
   for example your GitHub profile page `https://github.com/YOURNAME/`.
5. Copy the **client key** and **client secret**.
6. Add your own TikTok account as a test user (Sandbox tab) so you can use
   the app before TikTok reviews it.

### 4. Connect your TikTok account

On your computer:

```
pip install requests
python get_tiktok_token.py
```

Follow the prompts. It prints a refresh token. This is `TIKTOK_REFRESH_TOKEN`.

### 5. Make a GitHub token so the script can renew its own logins

GitHub > Settings > Developer settings > Fine-grained tokens > Generate new.
Give it access to only this repository, with **Secrets: Read and write**.
This is `GH_PAT`.

### 6. Save the five secrets

In your repository: Settings > Secrets and variables > Actions > New secret.

| Name | Value |
| --- | --- |
| `INSTAGRAM_ACCESS_TOKEN` | from step 2 |
| `TIKTOK_CLIENT_KEY` | from step 3 |
| `TIKTOK_CLIENT_SECRET` | from step 3 |
| `TIKTOK_REFRESH_TOKEN` | from step 4 |
| `GH_PAT` | from step 5 |

### 7. Test it

Repository > Actions > "Instagram to TikTok drafts" > Run workflow.
Within a minute or two a video should show up in your TikTok inbox.

## Things to know

- **Post your drafts.** TikTok holds at most 5 unposted videos per day from an
  app. If you fall behind, the script waits until you post or delete some.
- **Captions do not carry over.** TikTok does not let an app set the caption
  on a draft. The caption is printed in the run log and saved in
  `posted.json` so you can copy it.
- **Videos with licensed music are skipped.** Instagram does not hand those
  files out.
- **Timing is close, not exact.** GitHub can start a run 5 to 30 minutes late.
- **Order.** It starts with your oldest video and works forward. To start with
  the newest, change `POST_ORDER` to `newest_first` in `repost.yml`.
- **Changing times.** Edit `POST_HOURS` in `repost.yml` (24-hour clock). If you
  move far from 9/1/7, the `cron` lines need matching UTC hours.
- **To skip a video**, add its Instagram ID to `posted.json` by hand.
