"""Poll the AIMA tracking API and post to Telegram when the process history of a residence card request changes."""
import datetime, html, json, os, ssl, sys, time, traceback, urllib.parse, urllib.request, uuid

HERE = os.path.dirname(os.path.abspath(__file__))


def load_env():
    """Read KEY=value lines from .env next to the script; variables already set win."""
    path = os.path.join(HERE, ".env")
    if not os.path.exists(path):
        return
    for line in open(path):
        key, sep, value = line.strip().partition("=")
        if sep and key and not key.startswith("#"):
            os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


load_env()
TRACKING_ID = os.environ.get("AIMA_TRACKING_ID", "").strip().rstrip("/").split("/")[-1]
API = f"https://api-contactenos.aima.gov.pt/api/FormTracking/{TRACKING_ID}"
PAGE = f"https://contactenos.aima.gov.pt/tracking/{TRACKING_ID}"
THREAD_ID = os.environ.get("TELEGRAM_THREAD_ID", "")  # optional forum topic id
CHROMIUM = os.environ.get("CHROMIUM_PATH") or None  # None uses the browser installed by `playwright install`
STATE = os.path.join(HERE, "state.json")
LOG = os.path.join(HERE, "aima.log")
SHOT = os.path.join(HERE, "last.png")
RUNS = os.path.join(HERE, "runs.jsonl")
SNAPSHOTS = os.path.join(HERE, "snapshots")
RUN = {}
# AIMA serves an incomplete chain; the Sectigo OV R36 intermediate completes it against the system roots.
CTX = ssl.create_default_context()
CTX.load_verify_locations(os.path.join(HERE, "sectigo-ov-r36.pem"))


def log(msg):
    with open(LOG, "a") as f:
        f.write(f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S} {msg}\n")
    print(msg)


def fetch():
    req = urllib.request.Request(API, headers={"Accept": "application/json", "Origin": "https://contactenos.aima.gov.pt"})
    t0 = time.monotonic()
    with urllib.request.urlopen(req, context=CTX, timeout=30) as r:
        RUN["http"] = r.status
        raw = json.load(r)
    RUN["fetch_ms"] = int((time.monotonic() - t0) * 1000)
    return raw["result"]["data"], raw


def snapshot(raw):
    os.makedirs(SNAPSHOTS, exist_ok=True)
    path = os.path.join(SNAPSHOTS, f"{datetime.datetime.now():%Y%m%d-%H%M%S}.json")
    json.dump(raw, open(path, "w"), ensure_ascii=False, indent=1)
    return os.path.basename(path)


def record():
    RUN["duration_ms"] = int((time.monotonic() - RUN.pop("_t0")) * 1000)
    with open(RUNS, "a") as f:
        f.write(json.dumps(RUN, ensure_ascii=False) + "\n")


def fmt_date(s):
    return datetime.datetime.fromisoformat(s[:19]).strftime("%d/%m %H:%M")


def find_key(x, key):
    """Return the first truthy value of key anywhere in the payload."""
    if isinstance(x, dict):
        if x.get(key):
            return x[key]
        x = list(x.values())
    if isinstance(x, list):
        for v in x:
            r = find_key(v, key)
            if r:
                return r
    return None


def ctt_line(data):
    code = find_key(data, "registoSaida")
    if not code:
        return None
    url = f"https://www.ctt.pt/feapl_2/app/open/objectSearch/objectSearch.jspx?objects={urllib.parse.quote(str(code))}"
    return f'-&gt; <a href="{html.escape(url)}">CTT link</a>'


def message(data, before_tipo, new_step, test=False):
    labels = {c["tipo"]: c for c in data["caminhoEsperado"]}
    before = labels.get(before_tipo, {}).get("labelPt", "?")
    title = "TESTE - ATUALIZACAO AIMA" if test else "ATUALIZACAO AIMA"
    return "\n".join([
        f"<b>{title}</b>",
        fmt_date(new_step["dataCriacao"]),
        "",
        f"<i>{html.escape(before)} -&gt; {html.escape(new_step['labelPt'])}</i>",
        "",
        *([ctt] if (ctt := ctt_line(data)) else []),
        f'-&gt; <a href="{html.escape(PAGE)}">AIMA link</a>',
    ])


def screenshot():
    """Save the current step and the one before it from the live page; return the path or None."""
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b = p.chromium.launch(executable_path=CHROMIUM, args=["--no-sandbox"])
            page = b.new_page(viewport={"width": 720, "height": 1400}, device_scale_factor=2, locale="pt-PT")
            page.goto(PAGE, wait_until="networkidle", timeout=60000)
            badge = page.get_by_text("Estado atual", exact=True).first
            badge.wait_for(timeout=30000)
            box = badge.evaluate("""e => {
                let row = e; for (let i = 0; i < 4; i++) row = row.parentElement;
                const a = row.getBoundingClientRect();
                const b = (row.nextElementSibling || row).getBoundingClientRect();
                return {x: a.left - 8, y: a.top + window.scrollY - 8, width: a.width + 16, height: b.bottom - a.top + 16};
            }""")
            page.screenshot(path=SHOT, clip=box, full_page=True)
            b.close()
        return SHOT
    except Exception as e:
        RUN["screenshot_error"] = f"{type(e).__name__}: {e}"
        log(f"screenshot failed: {e}")
        return None


def send(text, photo=None):
    base = f"https://api.telegram.org/bot{os.environ['TELEGRAM_BOT_TOKEN']}"
    fields = {"chat_id": os.environ["TELEGRAM_CHAT_ID"], "parse_mode": "HTML"}
    if THREAD_ID:
        fields["message_thread_id"] = THREAD_ID
    if not photo:
        body = urllib.parse.urlencode({**fields, "text": text}).encode()
        with urllib.request.urlopen(f"{base}/sendMessage", data=body, timeout=30) as r:
            return json.load(r)["ok"]
    boundary = uuid.uuid4().hex
    parts = [f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode()
             for k, v in {**fields, "caption": text}.items()]
    parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"photo\"; filename=\"aima.png\"\r\n"
                 f"Content-Type: image/png\r\n\r\n".encode() + open(photo, "rb").read() + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    req = urllib.request.Request(f"{base}/sendPhoto", data=b"".join(parts),
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)["ok"]


def main():
    RUN.update(ts=f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S}", _t0=time.monotonic(),
               trigger="test" if "--test" in sys.argv else os.environ.get("AIMA_TRIGGER", "manual"))
    try:
        if not TRACKING_ID:
            raise ValueError("AIMA_TRACKING_ID is not set")
        return run()
    except Exception as e:
        RUN.update(result="error", error=f"{type(e).__name__}: {e}")
        log(f"error: {RUN['error']}\n{traceback.format_exc()}")
        return 1
    finally:
        record()


def run():
    try:
        data, raw = fetch()
    except Exception as e:
        RUN.update(result="fetch_error", error=f"{type(e).__name__}: {e}")
        log(f"fetch failed: {RUN['error']}")
        return 1
    steps = {h["tipo"]: h for h in data["historico"]}
    latest = max(data["historico"], key=lambda h: h["dataCriacao"])
    RUN.update(current=latest["tipo"], steps=len(steps))
    if "--test" in sys.argv:
        # Real current and previous step, so the text matches the screenshot.
        hist = sorted(data["historico"], key=lambda h: h["dataCriacao"])
        prev = hist[-2]["tipo"] if len(hist) > 1 else latest["tipo"]
        shot = screenshot()
        ok = send(message(data, prev, latest, test=True), shot)
        RUN.update(result="test", screenshot=bool(shot), telegram=ok)
        log(f"test message sent: {ok}")
        return 0
    seen = json.load(open(STATE)) if os.path.exists(STATE) else None
    if seen is None:
        json.dump(sorted(steps), open(STATE, "w"))
        RUN.update(result="init", snapshot=snapshot(raw))
        log(f"initialised with {len(steps)} steps, current: {data['descricaoPt']}")
        return 0
    new = [h for t, h in steps.items() if t not in seen]
    if not new:
        RUN.update(result="no_change")
        log(f"no change: {data['descricaoPt']}")
        return 0
    order = [c["tipo"] for c in data["caminhoEsperado"]]
    before_tipo = max(seen, key=lambda t: order.index(t) if t in order else -1)
    newest = max(new, key=lambda h: h["dataCriacao"])
    shot = screenshot()
    ok = send(message(data, before_tipo, newest), shot)
    RUN.update(result="change", new=[h["tipo"] for h in new], before=before_tipo,
               screenshot=bool(shot), telegram=ok, snapshot=snapshot(raw))
    log(f"CHANGE {RUN['new']} telegram ok={ok}")
    if ok:
        json.dump(sorted(steps), open(STATE, "w"))
    return 0


sys.exit(main())
