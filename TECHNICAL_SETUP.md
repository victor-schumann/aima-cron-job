# Technical setup

This file is written so a person or an AI assistant can set the watcher up end to end without guessing. Follow
the steps in order and run each check before moving on.

If you are an AI assistant setting this up for someone: ask the user before each step that changes their system
(`sudo apt` through `--with-deps`, systemd units, cron lines) and say what it changes. Let the user type the
token and chat id into `.env` themselves; never print the token or paste it into logs, chats or commits.

## What it does

`aima_watch.py` runs once and exits. A timer (systemd or cron) starts it a few times a day. Each run:

1. Calls `https://api-contactenos.aima.gov.pt/api/FormTracking/<AIMA_TRACKING_ID>` (the same JSON the public
   tracking page loads). No login is needed: the tracking id is the secret.
2. Reads the steps done so far (`result.data.historico`, each with a `tipo`) and compares their `tipo` values
   with the ones saved in `state.json`.
3. No new step: logs `no change: <status>` and exits.
4. New step: takes a screenshot of the "Estado atual" part of the tracking page with headless Chromium
   (Playwright), sends it to Telegram with the new and the previous status, a CTT tracking link once the card is
   shipped (`registoSaida` in the payload), and the page link. It saves the raw reply in `snapshots/`. It
   updates `state.json` only when Telegram accepts the message, so a failed send is retried at the next run.
5. The first run ever only saves the current steps to `state.json` and sends nothing.

`--test` sends a message titled "TESTE - ATUALIZACAO AIMA" with the real current and previous step, the same
ones the screenshot shows. It does not touch `state.json`.

If the screenshot fails (no browser, page changed), the message is sent as text only and the error is logged.

## Files

| File | Purpose |
|---|---|
| `aima_watch.py` | the watcher, standard library only except Playwright for the screenshot |
| `sectigo-ov-r36.pem` | public intermediate certificate. AIMA's API serves an incomplete TLS chain, so plain Python fails with `CERTIFICATE_VERIFY_FAILED`; this file completes it against the system root store. Valid until 2036-03-21 |
| `.env.example` | template for `.env` |
| `systemd/aima-watch.service`, `systemd/aima-watch.timer` | system units, runs at 08:00, 14:00, 16:00 and 20:00 in the system timezone |
| `requirements.txt` | Playwright |

Written at run time, all ignored by git: `state.json` (seen steps), `aima.log` (one line per run),
`runs.jsonl` (one JSON object per run: result, HTTP status, timings, errors), `last.png` (last screenshot),
`snapshots/` (raw API reply at init and at every change).

## Requirements

- Linux with Python 3.8 or newer and `python3-venv`. Runs on a Raspberry Pi with Debian 13 (arm64) and Python 3.13.
- Outbound HTTPS to `api-contactenos.aima.gov.pt`, `contactenos.aima.gov.pt` and `api.telegram.org`.
- For the screenshot only: Playwright's headless Chromium, about 275 MB in `~/.cache/ms-playwright` with
  `--only-shell`. Without `--only-shell` Playwright also downloads the full browser, about 680 MB in total.
- `--with-deps` runs `sudo apt-get install` for the browser's system libraries. apt may also upgrade packages
  that are already installed (on a Debian 13 desktop it upgraded 24 and added 6 on 2026-10-23). Skip it on a
  machine where that is not acceptable and install the libraries yourself, or use the system Chromium (step 2).
- The paths in `systemd/aima-watch.service` and in the cron line assume the repo is at `~/aima-cron-job`.

## Steps

1. Clone and create the virtual environment:

   ```bash
   git clone https://github.com/victor-schumann/aima-cron-job.git ~/aima-cron-job
   cd ~/aima-cron-job
   python3 -m venv venv
   venv/bin/pip install -r requirements.txt
   ```

2. Install a browser for the screenshot. Either let Playwright download one:

   ```bash
   venv/bin/playwright install --with-deps --only-shell chromium
   ```

   `--with-deps` uses sudo apt; see Requirements. Where Playwright has no build (some ARM boards), use the system
   package instead (`sudo apt install chromium`) and set `CHROMIUM_PATH=/usr/bin/chromium` in `.env`. Skipping
   both is fine: messages go out as text.

3. Find your tracking id. It is the UUID at the end of your AIMA tracking link,
   `https://contactenos.aima.gov.pt/tracking/<id>`. `AIMA_TRACKING_ID` also accepts the full link.

4. Create the Telegram bot and find the chat id:
   - In Telegram, talk to @BotFather, send `/newbot`, and copy the token.
   - Add the bot to the group (or open a private chat with it). In a group, a new bot runs in privacy mode and only
     sees commands and mentions, so send `/start@<bot_username>` there rather than a plain message.
   - Open `https://api.telegram.org/bot<TOKEN>/getUpdates` and read `message.chat.id` (groups have a negative
     id, often starting with `-100`). The list is often empty: updates are kept for 24 hours only, and a webhook
     or another program polling the same bot empties it. Then look for `my_chat_member.chat.id` (sent when the
     bot is added), or use the next point, which always works.
   - From a message link: in Telegram Desktop or Web, right-click a message in the group and copy its link. A
     private group link looks like `https://t.me/c/<number>/<topic>/<message>` (or `/c/<number>/<message>`
     without topics). The chat id is `-100<number>`, and `<topic>` is the `TELEGRAM_THREAD_ID`.
   - Leave `TELEGRAM_THREAD_ID` empty to post in the main chat.
   - Check the chat id with `https://api.telegram.org/bot<TOKEN>/getChat?chat_id=<chat id>`: `"ok": true` means
     the bot is in the chat. The topic id cannot be checked this way; a wrong one shows up as `HTTP Error 400`
     at step 6.

5. Create `.env` and keep it private:

   ```bash
   cp .env.example .env
   chmod 600 .env
   nano .env   # or any editor
   ```

6. Check and send a test message:

   ```bash
   set -a; . ./.env; set +a
   venv/bin/python aima_watch.py --test
   tail -1 runs.jsonl
   ```

   Expected: `test message sent: True`, a "TESTE" message in Telegram, and `"result": "test"` in `runs.jsonl`.
   `"screenshot": false` means the browser step failed; see `screenshot_error` in the same line.

7. Initialise the state (sends nothing):

   ```bash
   venv/bin/python aima_watch.py
   cat state.json
   ```

   Expected: `initialised with N steps, current: ...` and a JSON list of step names.

8. Schedule it. Pick one.

   systemd (recommended, it catches up on runs missed while the machine was off):

   ```bash
   sed -e "s/YOUR_USER/$USER/g" -e "s#/home/$USER/aima-cron-job#$PWD#g" systemd/aima-watch.service \
     | sudo tee /etc/systemd/system/aima-watch.service
   sudo cp systemd/aima-watch.timer /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable --now aima-watch.timer
   systemctl list-timers aima-watch.timer
   ```

   Run the `sed` from the repo folder: the second expression puts the real repo path in the unit. Run it
   once by hand with `sudo systemctl start aima-watch.service` and read `journalctl -u aima-watch.service -n 5`.

   cron:

   ```bash
   crontab -e
   # add:
   0 8,14,16,20 * * * cd ~/aima-cron-job && set -a && . ./.env && venv/bin/python aima_watch.py
   ```

   Replace `~/aima-cron-job` if the repo is elsewhere.

   Times follow the system timezone (`timedatectl`). Change them in the timer's `OnCalendar` line or in the cron
   line. Keep it to a few runs a day: it is a public government service.

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `fetch failed: ... CERTIFICATE_VERIFY_FAILED` | `sectigo-ov-r36.pem` missing, or AIMA changed certificate authority. Check the chain with `openssl s_client -connect api-contactenos.aima.gov.pt:443 -showcerts` and replace the file with the intermediate it names |
| `fetch failed: HTTP Error 404` or `KeyError` | wrong tracking id, or AIMA changed the API. Open the tracking page in a browser and compare with the network request it makes |
| `error: AIMA_TRACKING_ID is not set` | `.env` not loaded. For a manual run, use `set -a; . ./.env; set +a` first |
| `KeyError: 'TELEGRAM_BOT_TOKEN'` | same: `.env` not loaded or the variable is missing |
| `HTTP Error 401` from Telegram | wrong bot token |
| `HTTP Error 400` from Telegram | wrong chat id or thread id, or the bot is not in the chat |
| `screenshot failed: ...` | no browser, or the page layout changed (it looks for the text "Estado atual"). The message still goes out as text |
| A change was not announced | read `runs.jsonl`: `"telegram": false` means the send failed and the next run retries |

To announce a change again, delete `state.json`, run once to initialise, and edit `state.json` to remove the
step you want re-sent.

## Stopping

```bash
sudo systemctl disable --now aima-watch.timer
```

or remove the cron line. Nothing else runs in the background.
