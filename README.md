# YT Shorts Downloader — Render Free Web Service

Telegram bot for public YouTube Shorts links with Help/About, cancellation, temporary-file cleanup, and an HTTP health endpoint.

## Deploy on Render Free

1. Push these files to GitHub.
2. Render Dashboard → **New → Web Service** → connect this repo.
3. Choose Docker runtime and the **Free** instance type.
4. Add Environment Variable `BOT_TOKEN` with the token from @BotFather.
5. Set health check path to `/health`.
6. Deploy. Check logs for `Bot starting with polling...`.
7. Open the Render URL (it should say the service is running), then test `/start` in Telegram.

`render.yaml` is included as a Blueprint option; if you create the service manually, use the settings above.

## Commands

- `/start` — main menu
- `/help` — instructions
- `/about` — about the bot
- `/cancel` — cancel a current download

## Security

Never upload `.env` or your actual token to GitHub. Set `BOT_TOKEN` in Render's Environment settings. If the token leaks, revoke it via @BotFather.

## Important free-plan caveats

Render Free supports Web Services, not Background Workers. Free Web Services can spin down after 15 minutes without inbound traffic and can restart. This means the bot may be temporarily unavailable or slow to wake up; free hosting cannot guarantee uninterrupted 24/7 service. A health endpoint does not guarantee uninterrupted service.

## Limits

- Only `youtube.com/shorts/...` URLs are accepted.
- Videos over approximately 49 MB are rejected.
- Private, age-restricted, region-restricted, unavailable, or blocked videos may fail.
- Use only content you have permission to download and respect YouTube's terms and copyright.

## Local run

Python 3.10+ recommended.

```bash
pip install -r requirements.txt
```

Set `BOT_TOKEN` in your environment, then run:

```bash
python bot.py
```
