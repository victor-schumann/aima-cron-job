# aima-cron-job

Watches your AIMA residence card request (the `contactenos.aima.gov.pt/tracking/...` page) and sends a Telegram
message with a screenshot when the status changes. It runs a few times a day on any Linux box, for example a
Raspberry Pi.

## Setup

You need a Linux machine that is always on (a Raspberry Pi is enough), a Telegram account, and your AIMA tracking
link.

1. Download and install. This takes a few minutes and asks for your sudo password once:

   ```bash
   git clone https://github.com/victor-schumann/aima-cron-job.git ~/aima-cron-job
   cd ~/aima-cron-job
   python3 -m venv venv
   venv/bin/pip install -r requirements.txt
   venv/bin/playwright install --with-deps --only-shell chromium
   ```

2. Create a Telegram bot. In Telegram, open @BotFather, send `/newbot`, follow the questions, and copy the token
   it gives you. Then add the new bot to the group where you want the messages.

3. Find the chat id of that group. In Telegram Desktop or Web, right-click any message in the group and choose
   "Copy Message Link". The link looks like `https://t.me/c/1234567890/55`. Your chat id is `-100` followed by
   the first number: `-1001234567890`. No "Copy Message Link" option? Use the other way in
   [TECHNICAL_SETUP.md](TECHNICAL_SETUP.md) step 4.

4. Fill in your details:

   ```bash
   cp .env.example .env
   nano .env
   ```

   Set `AIMA_TRACKING_ID` to your AIMA tracking link, and paste the bot token and the chat id. Save with Ctrl+O,
   Enter, then exit with Ctrl+X.

5. Send a test message. You should get a message titled "TESTE" with your current status:

   ```bash
   venv/bin/python aima_watch.py --test
   ```

6. Save your current status. This sends nothing; from now on, only changes are sent:

   ```bash
   venv/bin/python aima_watch.py
   ```

7. Make it run by itself at 08:00, 14:00, 16:00 and 20:00. Run `crontab -e`, add this line at the end, and save:

   ```
   0 8,14,16,20 * * * ~/aima-cron-job/venv/bin/python ~/aima-cron-job/aima_watch.py
   ```

Done. When AIMA changes your status, the bot sends a message like the one above.

Topics in a group, systemd instead of cron, and troubleshooting: [TECHNICAL_SETUP.md](TECHNICAL_SETUP.md). If you use an AI assistant to set it
up, point it to that file.
