#!/usr/bin/env python3
# Manulife KB Telegram bot — PC-independent, runs on GitHub Actions (free).
# Pure stdlib. No external deps, no paid LLM. Answers by lexical search over
# the public kb_all.json and returns the relevant doc text + PDF link.
import re, json, sys, os, urllib.request, urllib.error, urllib.parse

KB_URL = "https://aibizlab-hub.github.io/aibizlab-hkfinance/manulife-kb/kb_all.json"
PDF_BASE = "https://aibizlab-hub.github.io/aibizlab-hkfinance/manulife-kb/pdfs/"
ALLOWED_CHAT = "828131815"   # user's private chat with @My_babyG_bot
MAX_MSG = 10                  # circuit breaker: never process >10 msgs/run
HTTP_TIMEOUT = 15

def log(*a):
    print("[bot]", *a, file=sys.stderr, flush=True)

def tok(s):
    s = (s or "").lower()
    return re.findall(r"[一-鿿]", s) + re.findall(r"[a-z0-9]+", s)

def http_get_json(url, timeout=HTTP_TIMEOUT):
    req = urllib.request.Request(url, headers={"User-Agent": "manulife-kb-bot"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))

def tg_api(token, method, params=None, timeout=HTTP_TIMEOUT):
    url = f"https://api.telegram.org/bot{token}/{method}"
    data = json.dumps(params or {}).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "ignore")
        # Circuit breaker: 429 rate-limit / 402 payment -> stop, alert admin.
        if e.code in (402, 429):
            log(f"CIRCUIT BREAKER: Telegram returned {e.code}. Aborting run to prevent token drain.")
            sys.exit(0)
        log(f"tg_api {method} HTTP {e.code}: {body[:200]}")
        return None

def set_github_var(name, value, gh_token):
    if not gh_token:
        return
    base = "https://api.github.com/repos/aibizlab-hub/aibizlab-hkfinance/actions/variables"
    data = json.dumps({"name": name, "value": str(value)}).encode()
    h = {"Authorization": f"Bearer {gh_token}", "Accept": "application/vnd.github+json",
         "Content-Type": "application/json"}
    # Try PATCH (update) first; if 404, POST (create).
    try:
        req = urllib.request.Request(f"{base}/{name}", data=data, method="PATCH", headers=h)
        urllib.request.urlopen(req, timeout=HTTP_TIMEOUT)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            try:
                req = urllib.request.Request(base, data=data, method="POST", headers=h)
                urllib.request.urlopen(req, timeout=HTTP_TIMEOUT)
            except Exception as ex:
                log(f"warn: could not create var {name}: {ex}")
        else:
            log(f"warn: could not update var {name}: {e.code}")

def main():
    token = os.environ.get("TG_BOT_TOKEN")
    if not token:
        log("ERROR: TG_BOT_TOKEN not set"); sys.exit(1)
    gh_token = os.environ.get("GITHUB_TOKEN")
    offset = int(os.environ.get("TG_OFFSET", "0") or "0")
    log(f"start offset={offset}")

    # 1) Load KB (public, CORS *). Fail -> circuit break, don't crash.
    try:
        docs = http_get_json(KB_URL)
    except Exception as e:
        log(f"KB fetch failed: {e}. Aborting.")
        return
    log(f"loaded {len(docs)} docs")

    # 2) Poll Telegram.
    resp = tg_api(token, "getUpdates", {"offset": offset, "limit": MAX_MSG, "timeout": 10})
    if not resp or not resp.get("ok"):
        log("getUpdates failed"); return
    updates = resp.get("result", [])
    if not updates:
        log("no new messages"); return

    max_id = max(u["update_id"] for u in updates)
    new_offset = max_id + 1

    # First-run init guard: if we started at 0 (no stored offset), skip answering
    # stale messages and just advance the offset.
    if offset == 0:
        log(f"first run: initializing offset to {new_offset}, not answering {len(updates)} stale msg(s)")
        print(new_offset)
        set_github_var("TG_OFFSET", new_offset, gh_token)
        return

    answered = 0
    for u in updates:
        msg = u.get("message")
        if not msg or "text" not in msg:
            continue
        chat_id = str(msg.get("chat", {}).get("id", ""))
        if chat_id != ALLOWED_CHAT:
            log(f"ignored msg from non-allowed chat {chat_id}")
            continue
        q = msg["text"].strip()
        if not q:
            continue
        qt = tok(q)
        ranked = []
        for d in docs:
            sc = sum(1 for t in qt if t in set(tok(d.get("t","")+" "+d.get("f","")+" "+d.get("s",""))))
            if sc > 0:
                ranked.append((sc, d))
        ranked.sort(key=lambda x: x[0], reverse=True)
        top = ranked[:6]

        lines = ["🔎 搵到以下相關資料（嚟自宏利公開文件）：", ""]
        total = 0
        for sc, d in top:
            snip = (d.get("s","") or "")[:500]
            block = f"📄 {d.get('t','')}\n{snip}{'…' if len(d.get('s','') or '')>500 else ''}\n🔗 {PDF_BASE}{d.get('f','')}\n"
            if total + len(block) > 3800:
                break
            lines.append(block); total += len(block)
        if len(top) == 0:
            answer = "搵唔到相關文件，試下其他字眼（例如：內地醫院理賠 / 危疾定義 / 住院現金 / 索償表格）。"
        else:
            answer = "\n".join(lines)
        r = tg_api(token, "sendMessage", {"chat_id": chat_id, "text": answer})
        if r and r.get("ok"):
            answered += 1
        else:
            log(f"send failed for chat {chat_id}")
        if answered >= MAX_MSG:
            log("hit MAX_MSG cap, stopping")
            break

    log(f"answered {answered} message(s); new offset {new_offset}")
    print(new_offset)
    set_github_var("TG_OFFSET", new_offset, gh_token)

if __name__ == "__main__":
    main()
