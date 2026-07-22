#!/usr/bin/env python3
# Manulife KB Telegram bot — PC-independent, runs on GitHub Actions (free).
# Pure stdlib. No external deps, no paid LLM. Answers by lexical search over
# the public kb_all.json and returns the relevant doc text + PDF link.
import re, json, sys, os, time, urllib.request, urllib.error, urllib.parse

KB_BASE = "https://aibizlab-hub.github.io/aibizlab-hkfinance/manulife-kb/kb_all"
ALLOWED_CHAT = "828131815"   # user's private chat with @My_babyG_bot
MAX_MSG = 10                  # circuit breaker: never process >10 msgs/run
HTTP_TIMEOUT = 15

def log(*a):
    print("[bot]", *a, file=sys.stderr, flush=True)

# HK insurance synonym map (bidirectional)
SYN = {
    '理賠': ['索償'], '索償': ['理賠'],
    '危疾': ['嚴重疾病', '重大疾病'], '嚴重疾病': ['危疾'], '重大疾病': ['危疾'],
    '住院': ['醫院', '入院'], '醫院': ['住院'],
    '內地': ['中國大陸', '大陸'], '大陸': ['內地'],
    '表格': ['申請表'], '索償表': ['理賠表'],
}

def tok(s):
    s = (s or "").lower()
    toks = []
    for run in re.findall(r"[一-鿿]+", s):
        toks.append(run)                       # full run
        if len(run) >= 2:
            for i in range(len(run) - 1):
                toks.append(run[i:i + 2])       # 2-grams
        if len(run) >= 3:
            for i in range(len(run) - 2):
                toks.append(run[i:i + 3])       # 3-grams
    toks += re.findall(r"[a-z0-9]+", s)
    return toks

def expand(toks):
    out = list(toks)
    for t in toks:
        for k, vs in SYN.items():
            if t == k:
                out += vs
            elif t in vs:
                out.append(k)
    return out

# High-value insurance concepts — matching these is a strong relevance signal.
HIGH_STRONG = {'內地', '大陸', '中國大陸'}   # dominant intent (mainland China)
HIGH = {'索償', '危疾', '住院', '手術', '保費', '紓困', '免稅', '扣稅',
        '醫院', '理賠', '收據', '保障', '保單', '表格', '授權'}

def w_for(t):
    base = 3 + max(0, len(t) - 2) * 2          # longer phrase = more specific
    if t in HIGH_STRONG:
        base += 12
    elif t in HIGH:
        base += 6
    return base

def score_doc(doc, qtoks):
    title = doc.get("t", "").lower()
    # Search the FULL extracted text (field "text"); fall back to snippet "s".
    body = (title + " " + doc.get("f", "") + " " + doc.get("text", "") + " " + doc.get("s", "")).lower()
    score = 0
    matched = 0
    for t in qtoks:
        if len(t) >= 2 and t in body:
            score += w_for(t); matched += 1
        elif len(t) == 1 and t in body:
            score += 1; matched += 1
        if t in title:
            score += 3
    # Co-occurrence: a doc matching several distinct query terms is highly relevant.
    if matched >= 2:
        score += matched * 2
    # Strong intent: any mainland-China signal dominates generic medical docs.
    if any(t in HIGH_STRONG and t in body for t in qtoks):
        score += 100
    return score

def best_passage(text, qtoks, window=420):
    """Extractive QA: return the segment centered on the highest-weight query
    term (e.g. 內地 +100), so deep in-document answers surface correctly."""
    low = (text or "").lower()
    # Anchor on the highest-weight query term's first occurrence.
    best_t, best_w = None, -1
    for t in qtoks:
        if len(t) >= 1 and t in low and w_for(t) > best_w:
            best_w = w_for(t); best_t = t
    anchor = low.find(best_t) if best_t else -1
    if anchor < 0:  # fallback: first occurrence of any query term
        for t in qtoks:
            if len(t) >= 1:
                p = low.find(t)
                if p >= 0:
                    anchor = p; break
    if anchor < 0:
        return (text or "")[:window]
    start = max(0, anchor - window // 3)
    return (text or "")[start:start + window]

def http_get_json(url, timeout=HTTP_TIMEOUT, retries=3):
    """Fetch + parse JSON with bounded retries (circuit-breaker safe: every
    external call has a timeout + retry cap, no open-ended loops)."""
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "manulife-kb-bot"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:
            last = e
            log(f"http_get_json attempt {attempt+1}/{retries} failed: {e}")
            time.sleep(1.5 * (attempt + 1))
    raise last

def load_kb():
    """Load the KB. The full KB is split into kb_all0.json..N.json (+manifest)
    because the GitHub Contents/Pages file is >1MB. Fall back to a single
    kb_all.json if no manifest is present."""
    docs = []
    # Primary: manifest + numbered parts.
    try:
        m = http_get_json(KB_BASE + "_manifest.json")
        n = int(m.get("count", 0))
        for i in range(n):
            try:
                docs.extend(http_get_json(f"{KB_BASE}{i}.json"))
            except Exception as e:
                log(f"part {i} load failed: {e}")
                break
        if docs:
            return docs
    except Exception as e:
        log(f"manifest load failed: {e}")
    # Fallback: single file.
    try:
        return http_get_json(KB_BASE + ".json")
    except Exception as e:
        log(f"single kb load failed: {e}")
        return []

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

def main():
    token = os.environ.get("TG_BOT_TOKEN")
    if not token:
        log("ERROR: TG_BOT_TOKEN not set"); sys.exit(1)
    # We do NOT rely on GitHub repo variables (GITHUB_TOKEN cannot write them ->
    # 403). Instead Telegram itself tracks confirmed updates: every run pulls
    # unconfirmed messages (offset=0) and at the end confirms them via a
    # getUpdates?offset=max_id+1 call, so the next run won't re-answer.
    offset = 0
    log(f"start offset={offset}")

    # 1) Load KB (public, CORS *). Fail -> circuit break, don't crash.
    try:
        docs = load_kb()
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

    # (No first-run skip guard: the bot answers from the very first run so the
    #  user never has to send twice. Offset is maintained via TG_OFFSET variable.)

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
        qt = expand(tok(q))
        ranked = []
        for d in docs:
            sc = score_doc(d, qt)
            if sc > 0:
                ranked.append((sc, d))
        ranked.sort(key=lambda x: x[0], reverse=True)
        top = ranked[:6]

        lines = ["🔎 搵到以下相關資料（嚟自宏利公開文件）：", ""]
        total = 0
        for sc, d in top:
            full = (d.get("text", "") or d.get("s", "") or "")
            snip = best_passage(full, qt)
            more = "…" if len(full) > len(snip) else ""
            block = f"📄 {d.get('t','')}\n{snip}{more}\n📁 文件：{d.get('f','')}\n"
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

    log(f"answered {answered} message(s); confirming up to update_id {new_offset-1}")
    # Confirm (remove) processed updates via Telegram itself so the next
    # scheduled run won't re-answer them. Avoids external state / 403 on vars.
    if updates:
        tg_api(token, "getUpdates", {"offset": new_offset, "limit": 1, "timeout": 1})

if __name__ == "__main__":
    main()
