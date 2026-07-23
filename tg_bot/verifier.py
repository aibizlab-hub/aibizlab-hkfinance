#!/usr/bin/env python3
# Rule-based Verifier (反駁專家 / 對抗式驗證者) — 免費、零 LLM、唔會砌假嘢。
#
# 實裝 verifier-scoring.md 第 2 節「反駁協議 (Rebuttal Protocol)」而唔使 LLM：
#   用家講咗句（可能錯嘅）觀點 / 假設
#     → Verifier 先喺 KB 撈相關證據
#     → 撈到：明示「你以為 X，但根據 [來源] 實為 Y」
#     → 撈唔到：標註「未於知識庫核實」，絕不妄斷
# 再加 always-on 嘅 source 顯示 + 準確免責聲明（答案必須準確鐵律）。
#
# 設計原則（對抗 AutonomousOptimizationArchitect 嘅成本鐵律）：
#   - 零外部 API call（除咗撈公開 KB，本來 bot 都要撈）
#   - 每個反駁 rule 嘅證據都係 runtime 由 KB 實際檢索，唔係 hardcode 死嘅假 fact
#   - 無 open-ended loop；search 只攞 top1
import os, re, json

HERE = os.path.dirname(os.path.abspath(__file__))
RULES_PATH = os.path.join(HERE, "verifier_rules.json")

# ---------- 自包含 lexical search（同 bot.py 邏輯一致，獨立可測） ----------
def tok(s):
    s = (s or "").lower()
    toks = []
    for run in re.findall(r"[一-鿿]+", s):
        toks.append(run)
        if len(run) >= 2:
            for i in range(len(run) - 1):
                toks.append(run[i:i + 2])
        if len(run) >= 3:
            for i in range(len(run) - 2):
                toks.append(run[i:i + 3])
    toks += re.findall(r"[a-z0-9]+", s)
    return toks

HIGH = {'索償', '危疾', '住院', '手術', '保費', '紓困', '免稅', '扣稅', '醫院',
        '理賠', '收據', '保障', '保單', '表格', '授權', '保費融資', '內地',
        '大陸', '融資', '風險', 'shortfall'}

def w_for(t):
    base = 3 + max(0, len(t) - 2) * 2
    if t in HIGH:
        base += 6
    return base

def score_doc(doc, qtoks):
    body = (doc.get("t", "") + " " + doc.get("f", "") + " " +
            doc.get("text", "") + " " + doc.get("s", "")).lower()
    score = 0
    matched = 0
    for t in qtoks:
        if len(t) >= 2 and t in body:
            score += w_for(t); matched += 1
        elif len(t) == 1 and t in body:
            score += 1; matched += 1
        if t in doc.get("t", "").lower():
            score += 3
    if matched >= 2:
        score += matched * 2
    return score

def best_passage(text, qtoks, window=420):
    low = (text or "").lower()
    best_t, best_w = None, -1
    for t in qtoks:
        if len(t) >= 1 and t in low and w_for(t) > best_w:
            best_w = w_for(t); best_t = t
    anchor = low.find(best_t) if best_t else -1
    if anchor < 0:
        for t in qtoks:
            if len(t) >= 1:
                p = low.find(t)
                if p >= 0:
                    anchor = p; break
    if anchor < 0:
        return (text or "")[:window]
    start = max(0, anchor - window // 3)
    # clean left edge: avoid cutting an ASCII word in half (e.g. "imited").
    if start > 0 and text[start - 1].isascii() and text[start - 1].isalnum():
        sp = text.find(" ", start)
        if sp != -1 and sp - start < 40:
            start = sp + 1
    return (text or "")[start:start + window]

# ---------- rules ----------
def load_rules(path=RULES_PATH):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"rebuttals": [], "conflict_guards": []}

def _match(q, rule):
    ql = q.lower()
    for m in (rule.get("must_include") or []):
        if m.lower() not in ql:
            return False
    anyo = rule.get("any_of") or []
    if anyo and not any(a.lower() in ql for a in anyo):
        return False
    return True

def _search_evidence(docs, query, topn=1):
    qt = tok(query)
    ranked = []
    for d in docs:
        if not isinstance(d, dict):
            continue
        sc = score_doc(d, qt)
        if sc > 0:
            ranked.append((sc, d))
    ranked.sort(key=lambda x: x[0], reverse=True)
    out = []
    for _, d in ranked[:topn]:
        full = (d.get("text", "") or d.get("s", "") or "")
        snip = best_passage(full, qt)
        out.append({"t": d.get("t", ""), "f": d.get("f", ""), "snip": snip})
    return out

def check_rebuttals(q, docs, rules=None):
    """返 list of 反駁 text block（已 KB 實際撈證據，唔會砌假嘢）。"""
    if rules is None:
        rules = load_rules()
    blocks = []
    ql = q.lower()
    for r in rules.get("rebuttals", []):
        if not _match(ql, r):
            continue
        ev_lines = []
        if r.get("kb_query"):
            for ev in _search_evidence(docs, r["kb_query"], topn=1):
                if ev.get("snip"):
                    ev_lines.append(
                        f"📄 {ev['t']}\n「{ev['snip']}」\n📁 文件：{ev['f']}")
        if ev_lines:
            block = (
                f"⚠️ 更正／反駁：你可能以為「{r.get('misconception', '')}」。\n"
                f"但根據宏利文件，正確知識係：{r.get('correct', '')}\n\n"
                + "\n\n".join(ev_lines) + "\n\n"
                f"👉 正確應該咁諗：{r.get('think', '以官方文件／ManuTouch 為準，唔好憑記憶或感覺答。')}"
            )
        else:
            block = (
                f"⚠️ 提醒：你可能以為「{r.get('misconception', '')}」。\n"
                f"正確知識：{r.get('correct', '')}\n"
                f"👉 正確應該咁諗：{r.get('think', '以官方文件／ManuTouch 為準。')}"
                f"（未於知識庫撈到具體文件，建議向 ManuTouch 或主管確認。）"
            )
        blocks.append(block)
    return blocks

def build_disclaimer():
    return (
        "\n\n―――――――――\n"
        "🔎 資料來源：宏利公開文件（ManuTouch 產品／營運文件）。本 bot 只答知識庫有嘅內容，"
        "唔會砌價錢或任何數字。如與你嘅理解有出入，以保單合約及 ManuTouch 最新資料為準；"
        "重要決定前請向主管或合規確認。"
    )

# ---------- self-test ----------
if __name__ == "__main__":
    import sys
    docs = []
    for p in sys.argv[1:]:
        try:
            docs += json.load(open(p, encoding="utf-8"))
        except Exception:
            pass
    rules = load_rules()
    print(f"[selftest] loaded {len(docs)} docs, {len(rules.get('rebuttals', []))} rebuttal rules")
    for q in ["保費融資係咪包賺㗎？", "呢個plan保費幾多錢？", "內地醫院點理賠"]:
        print("\n=== Q:", q, "===")
        for b in check_rebuttals(q, docs, rules):
            print(b)
