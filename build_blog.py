#!/usr/bin/env python3
"""Build static SEO blog site (HK Money Lab) from markdown posts."""
import os, re, glob
import markdown

SRC = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(SRC, "site")
os.makedirs(OUT, exist_ok=True)

SITE_URL = "https://aibizlab-hub.github.io/aibizlab-hkfinance"

PRODUCTS = [
    ("📈 Investment Portfolio Tracker (Excel)", "https://gumroad.com/products/ocqse", "HK$12"),
    ("🧠 Notion Financial Freedom Tracker", "https://gumroad.com/products/agcfz", "HK$9"),
    ("🤖 1000+ AI Prompts Pack", "https://gumroad.com/products/zudzxu", "HK$8"),
    ("📘 AI Side Hustle Blueprint", "https://gumroad.com/products/nwhbls", "HK$9"),
]

CSS = """
:root{--bg:#0f1117;--card:#1a1d27;--fg:#e8eaf0;--muted:#9aa3b2;--accent:#ff5e5b;--link:#6ea8fe}
*{box-sizing:border-box}
body{margin:0;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;background:var(--bg);color:var(--fg);line-height:1.7}
header.site{background:linear-gradient(135deg,#1a1d27,#262a38);padding:28px 20px;text-align:center;border-bottom:1px solid #2c3040}
header.site h1{margin:0;font-size:24px}
header.site p{margin:6px 0 0;color:var(--muted);font-size:14px}
.wrap{max-width:820px;margin:0 auto;padding:24px 18px}
article{background:var(--card);border:1px solid #2c3040;border-radius:12px;padding:28px 30px;margin-bottom:26px}
article h1{font-size:28px;margin-top:0;line-height:1.3}
article h2{font-size:21px;margin-top:30px;border-left:3px solid var(--accent);padding-left:10px}
article h3{font-size:17px}
article p,article li{color:#d6dae3}
article a{color:var(--link);text-decoration:none}
article a:hover{text-decoration:underline}
article pre{background:#0b0d13;border:1px solid #2c3040;border-radius:8px;padding:14px;overflow:auto;font-size:13px}
article code{background:#0b0d13;padding:2px 6px;border-radius:4px;font-size:13px}
article table{border-collapse:collapse;width:100%;margin:18px 0;font-size:14px}
article th,article td{border:1px solid #2c3040;padding:9px 12px;text-align:left}
article th{background:#20242f}
.cta{background:#20242f;border:1px solid var(--accent);border-radius:10px;padding:16px 20px;margin:24px 0;text-align:center}
.cta a{color:var(--accent);font-weight:700}
.prod-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin:18px 0}
.prod{padding:12px 14px;border:1px solid #2c3040;border-radius:8px;background:#161922}
.prod a{color:var(--link);font-weight:600;text-decoration:none}
.prod span{color:var(--muted);font-size:13px}
footer.site{text-align:center;color:var(--muted);font-size:13px;padding:30px 20px;border-top:1px solid #2c3040}
.meta{color:var(--muted);font-size:13px;margin-bottom:18px}
.signup{background:#20242f;border:1px solid var(--accent);border-radius:12px;padding:22px 24px;margin:28px 0;text-align:center}
.signup h3{margin:0 0 6px;color:var(--fg);font-size:19px}
.signup p{margin:0 0 14px;color:var(--muted);font-size:14px}
.signup form{display:flex;gap:8px;justify-content:center;flex-wrap:wrap}
.signup input[type=email]{flex:1 1 240px;max-width:320px;padding:11px 14px;border-radius:8px;border:1px solid #2c3040;background:#0b0d13;color:var(--fg);font-size:14px}
.signup button{padding:11px 20px;border-radius:8px;border:0;background:var(--accent);color:#fff;font-weight:700;font-size:14px;cursor:pointer}
.signup button:hover{opacity:.9}
.aff{background:#161922;border:1px solid #2c3040;border-radius:12px;padding:20px 24px;margin:28px 0}
.aff h3{margin:0 0 10px;color:var(--fg);font-size:18px}
.aff .prod-grid{margin-top:8px}
"""

TRACK = """<script data-goatcounter="https://aibizlab.goatcounter.com/count.js" async src="//gc.goatcounter.com/count.js"></script>"""

SIGNUP = f"""<div class="signup"><h3>📬 免費「週週增值」理財通訊</h3>
<p>每週一封：香港理財乾貨、被動收入點子、悭錢實戰。直接入你 inbox。</p>
<form action="https://docs.google.com/forms/d/e/1FAIpQLScCxi_w7f8Ep2hqylOLt9LSbOdzfATiV2g6GKmg1LAjxBhYvg/formResponse" method="POST" target="_blank">
<input type="hidden" name="entry.343764206" value="HK 理財通訊訂閱">
<input type="email" name="entry.324733833" placeholder="你的電郵地址" required>
<input type="hidden" name="entry.29427835" value="訂閱 HK 理財通訊">
<button type="submit">免費訂閱</button>
</form></div>"""

AFFILIATE = """<div class="aff"><h3>💸 幫我賣，賺 50% 佣金</h3>
<p>鍾意呢啲產品？成為我哋嘅 Gumroad 聯盟推廣人，搵人買就分你一半。零成本、零庫存。</p>
<form action="https://docs.google.com/forms/d/e/1FAIpQLScCxi_w7f8Ep2hqylOLt9LSbOdzfATiV2g6GKmg1LAjxBhYvg/formResponse" method="POST" target="_blank">
<input type="hidden" name="entry.343764206" value="聯盟推廣申請">
<input type="email" name="entry.324733833" placeholder="你的電郵地址" required>
<input type="hidden" name="entry.29427835" value="想做聯盟推廣人">
<button type="submit">拎聯盟連結</button>
</form></div>"""

def parse_frontmatter(text):
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    fm_raw, body = parts[1], parts[2]
    fm = {}
    for line in fm_raw.strip().splitlines():
        if ":" in line and not line.strip().startswith("-"):
            k, v = line.split(":", 1)
            fm[k.strip()] = v.strip().strip('"')
    return fm, body

def render_index(posts):
    cards = ""
    for p in posts:
        cards += f"""<article><h2><a href="{p['html']}">{p['title']}</a></h2>
<div class="meta">{p['desc']}</div>
<a class="cta" href="{p['html']}">📖 Read more →</a></article>"""
    prod = "".join(f'<div class="prod"><a href="{u}">{n}</a><br><span>{pr}</span></div>' for n,u,pr in PRODUCTS)
    html = f"""<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>HK Money Lab — 香港人理財 × 被動收入</title>
<meta name="description" content="香港人專屬理財指南：Excel 投資組合、被動收入、升小面試準備。實用、免費、即學即用。">
<link rel="canonical" href="{SITE_URL}/">
{TRACK}
<style>{CSS}</style></head>
<body><header class="site"><h1>💰 HK Money Lab</h1><p>香港人理財 × 被動收入 — 實用指南，慳錢又賺錢</p></header>
<div class="wrap">
{cards}
<div class="cta">💡 <strong>我們的 Gumroad 店：</strong> 4 款理財 / AI 工具，幫你起跑<br>
<div class="prod-grid">{prod}</div></div>
{SIGNUP}
{AFFILIATE}
</div>
<footer class="site">© 2026 HK Money Lab · Built with an automated content pipeline<br>🔗 姊妹站：<a href="https://aibizlab-hub.github.io/aibizlab-blog/" style="color:var(--link)">AI Business Lab</a> — 數碼產品 × AI 被動收入</footer></body></html>"""
    return html

def main():
    files = sorted(glob.glob(os.path.join(SRC, "blog_post_*.md")))
    posts = []
    md = markdown.Markdown(extensions=["tables", "fenced_code"])
    for f in files:
        raw = open(f, encoding="utf-8").read()
        fm, body = parse_frontmatter(raw)
        md.reset()
        content = md.convert(body)
        slug = fm.get("slug", os.path.splitext(os.path.basename(f))[0])
        title = fm.get("title", slug)
        desc = fm.get("meta_description", title)
        out_name = slug + ".html"
        cta = '<div class="cta">🔥 <strong>實用？拎工具：</strong> <a href="https://gumroad.com/products/ocqse">投資組合 Excel</a> / <a href="https://gumroad.com/products/nwhbls">AI 被動收入藍圖</a></div>'
        page = f"""<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<meta name="description" content="{desc}">
<link rel="canonical" href="{SITE_URL}/{out_name}">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{desc}">
<meta property="og:type" content="article">
{TRACK}
<style>{CSS}</style></head>
<body><header class="site"><h1>💰 HK Money Lab</h1><p><a href="index.html" style="color:var(--link)">← 全部文章</a></p></header>
<div class="wrap"><article>{content}{cta}</article>
<div class="cta">💡 <strong>我們的 Gumroad 店：</strong><div class="prod-grid">""" + "".join(f'<div class="prod"><a href="{u}">{n}</a><br><span>{pr}</span></div>' for n,u,pr in PRODUCTS) + """</div></div>
{SIGNUP}
{AFFILIATE}
</div><footer class="site">© 2026 HK Money Lab<br>🔗 姊妹站：<a href="https://aibizlab-hub.github.io/aibizlab-blog/" style="color:var(--link)">AI Business Lab</a></footer></body></html>"""
        open(os.path.join(OUT, out_name), "w", encoding="utf-8").write(page)
        posts.append({"title": title, "desc": desc, "html": out_name})
        print("built:", out_name)
    open(os.path.join(OUT, "index.html"), "w", encoding="utf-8").write(render_index(posts))
    print("built: index.html (", len(posts), "posts )")

if __name__ == "__main__":
    main()
