"""Build a small static site: per-store timelines of LINE posts (no LLM).

    .venv/bin/python scripts/line_pc_site.py            # -> data/line_pc_site/
    python3 -m http.server 8765 -d data/line_pc_site    # then open http://localhost:8765

index.html lists stores; stores/<hall_id>.html shows that store's posts grouped
by day, newest first. Images are re-encoded as small WebP (heavily compressed)
and loaded lazily. Carousel posts show every card side by side.
data/line_pc_site/ is git-ignored (screenshots of chats).
"""

from __future__ import annotations

import argparse
import html
import json
import shutil
from collections import defaultdict
from datetime import date
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
POSTS = ROOT / "data" / "line_pc_posts"
SITE = ROOT / "data" / "line_pc_site"
WIDTH = 300
QUALITY = 38
WEEKDAY = "月火水木金土日"

CSS = """
:root{--bg:#f5f4f0;--fg:#1c1c1a;--muted:#6d6c66;--card:#fff;--line:#e0dfd9;--accent:#1f6f5c;--chip:#ecebe5}
@media (prefers-color-scheme:dark){:root{--bg:#141413;--fg:#ebeae4;--muted:#a2a19a;--card:#1f1f1d;--line:#33322e;--accent:#72c4aa;--chip:#2a2a27}}
*{box-sizing:border-box}html{-webkit-text-size-adjust:100%}
body{margin:0;font:14px/1.55 -apple-system,"Hiragino Sans","Noto Sans JP",sans-serif;background:var(--bg);color:var(--fg)}
a{color:var(--accent)}header{position:sticky;top:0;z-index:2;background:var(--bg);border-bottom:1px solid var(--line);padding:10px 16px}
header h1{font-size:17px;margin:0}header p{margin:2px 0 0;color:var(--muted);font-size:12px}
main{max-width:1100px;margin:0 auto;padding:12px 16px 40px}
table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);border-radius:8px;overflow:hidden}
th,td{padding:8px 10px;border-bottom:1px solid var(--line);text-align:left;font-size:13px}th{color:var(--muted);font-weight:600}
td.n{text-align:right;font-variant-numeric:tabular-nums}.chip{display:inline-block;padding:1px 7px;border-radius:999px;background:var(--chip);font-size:11px;color:var(--muted)}
input{width:100%;max-width:360px;margin:0 0 10px;padding:6px 10px;border:1px solid var(--line);border-radius:6px;background:var(--card);color:var(--fg)}
.day{margin:18px 0 6px;font-size:15px;font-weight:700;border-bottom:1px solid var(--line);padding-bottom:4px}
.posts{display:flex;flex-wrap:wrap;gap:10px}
.post{background:var(--card);border:1px solid var(--line);border-radius:8px;overflow:hidden;width:min(100%,300px)}
.post.wide{width:100%}
.post img{display:block;width:100%;height:auto}
.cards{display:flex;gap:6px;overflow-x:auto;padding:6px;scroll-snap-type:x mandatory}
.cards img{width:min(78vw,300px);flex:none;border-radius:6px;scroll-snap-align:start}
.cap{padding:5px 8px;font-size:12px;color:var(--muted)}.cap b{color:var(--fg)}
details pre{white-space:pre-wrap;margin:4px 0 0;font:11px/1.4 ui-monospace,monospace}
nav.top{margin-bottom:8px;font-size:13px}
"""


def webp(src: Path, dest: Path) -> str:
    if not dest.exists():
        with Image.open(src) as image:
            image = image.convert("RGB")
            if image.width > WIDTH:
                image = image.resize((WIDTH, round(image.height * WIDTH / image.width)), Image.LANCZOS)
            image.save(dest, "WEBP", quality=QUALITY, method=6)
    return dest.name


def day_label(value: str | None) -> str:
    if not value:
        return "日付不明"
    d = date.fromisoformat(value)
    return f"{d.month}月{d.day}日（{WEEKDAY[d.weekday()]}）"


def page(title: str, subtitle: str, body: str, root: str) -> str:
    return (f"<!doctype html><html lang='ja'><head><meta charset='utf-8'>"
            f"<meta name='viewport' content='width=device-width,initial-scale=1'><title>{html.escape(title)}</title>"
            f"<link rel='stylesheet' href='{root}style.css'></head><body><header><h1>{html.escape(title)}</h1>"
            f"<p>{html.escape(subtitle)}</p></header><main>{body}</main></body></html>")


def store_info() -> dict[str, dict]:
    info: dict[str, dict] = {}
    for name, key in (("line_targets.json", "targets"), ("line_collection_plan.json", "stores")):
        path = ROOT / "data" / name
        if path.exists():
            for row in json.loads(path.read_text(encoding="utf-8"))[key]:
                info.setdefault(row["hall_id"], {}).update({k: v for k, v in row.items() if v is not None})
    return info


TYPE = {"type_a_passive": "A", "type_b_passive_plus_active": "B", "type_c_passive_external_web": "C", "unresolved": "未分類"}
TRIGGER = {"daily": "毎日送信", "verify_once": "送信確認中", "off": "—"}


def build(since: str | None) -> dict:
    records = [json.loads(l) for l in (POSTS / "posts.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    if since:
        records = [r for r in records if (r.get("posted_date") or r["capture_date"]) >= since]
    if SITE.exists():
        shutil.rmtree(SITE / "stores", ignore_errors=True)
    (SITE / "img").mkdir(parents=True, exist_ok=True)
    (SITE / "stores").mkdir(parents=True, exist_ok=True)
    (SITE / "style.css").write_text(CSS, encoding="utf-8")
    info = store_info()
    by_store: dict[str, list[dict]] = defaultdict(list)
    for record in records:
        by_store[record["hall_id"]].append(record)

    rows = []
    for hall, posts in by_store.items():
        meta = info.get(hall, {})
        name = meta.get("store_name") or hall
        posts.sort(key=lambda r: (r.get("posted_date") or "0000", r.get("posted_time") or "99:99"), reverse=True)
        by_day: dict[str | None, list[dict]] = defaultdict(list)
        for post in posts:
            by_day[post.get("posted_date")].append(post)
        body = ["<nav class='top'><a href='../index.html'>← 店舗一覧</a></nav>"]
        for day in sorted(by_day, key=lambda d: d or "0000", reverse=True):
            body.append(f"<div class='day'>{day_label(day)} <span class='chip'>{len(by_day[day])}件</span></div><div class='posts'>")
            for post in sorted(by_day[day], key=lambda r: r.get("posted_time") or "99:99"):
                cards = [c for c in post.get("cards", []) if (POSTS / c).exists()]
                if cards:
                    srcs = [webp(POSTS / c, SITE / 'img' / (Path(c).stem + '.webp')) for c in cards]
                    imgs = "".join(f"<img loading='lazy' src='../img/{src}' alt=''>" for src in srcs)
                    media, cls = f"<div class='cards'>{imgs}</div>", "post wide"
                else:
                    srcs = [webp(POSTS / post["image"], SITE / "img" / (post["post_id"] + ".webp"))]
                    media, cls = f"<img loading='lazy' src='../img/{srcs[0]}' alt=''>", "post"
                post["_srcs"] = srcs
                ocr = html.escape(post.get("ocr_text") or "")
                body.append(f"<div class='{cls}'>{media}<div class='cap'><b>{html.escape(post.get('posted_time') or '時刻不明')}</b>"
                            + (f" ・ 横並び{len(cards)}枚" if cards else "")
                            + (f"<details><summary>OCR</summary><pre>{ocr}</pre></details>" if ocr else "") + "</div></div>")
            body.append("</div>")
        subtitle = f"{hall} ・ Type {TYPE.get(meta.get('collection_type', ''), '')} ・ {len(posts)}件"
        (SITE / "stores" / f"{hall}.html").write_text(page(name, subtitle, "".join(body), "../"), encoding="utf-8")
        dated = [p["posted_date"] for p in posts if p.get("posted_date")]
        rows.append((max(dated) if dated else "", hall, name, meta, len(posts), len(by_day)))

    rows.sort(reverse=True)
    write_matrix(rows, by_store, info)
    compared = write_compare(info, records)
    hinted = write_hints(info)
    table = ["<input id='q' placeholder='店名で絞り込み'><table><thead><tr><th>店舗</th><th>最新の投稿</th>"
             "<th class='n'>件数</th><th class='n'>日数</th><th>Type</th><th>最新情報の送信</th></tr></thead><tbody>"]
    for last, hall, name, meta, count, days in rows:
        table.append(f"<tr data-name='{html.escape(name)}'><td><a href='stores/{html.escape(hall)}.html'>{html.escape(name)}</a></td>"
                     f"<td>{day_label(last) if last else '—'}</td><td class='n'>{count}</td><td class='n'>{days}</td>"
                     f"<td><span class='chip'>{TYPE.get(meta.get('collection_type', ''), '')}</span></td>"
                     f"<td>{TRIGGER.get(meta.get('text_trigger', ''), '')}</td></tr>")
    table.append("</tbody></table><script>const q=document.getElementById('q');q.addEventListener('input',()=>{"
                 "document.querySelectorAll('tbody tr').forEach(r=>{r.style.display=r.dataset.name.includes(q.value.trim())?'':'none'})})</script>")
    nav = "<nav class='top'><a href='matrix.html'>日付×店舗の一覧表 →</a> ・ <a href='compare.html'>画像と文字の比較 →</a> ・ <a href='hints.html'>機種カード（示唆） →</a></nav>"
    (SITE / "index.html").write_text(page("LINE投稿タイムライン", f"{len(rows)}店舗 ・ {len(records)}件", nav + "".join(table), ""), encoding="utf-8")
    size = sum(p.stat().st_size for p in SITE.rglob("*") if p.is_file())
    return {"stores": len(rows), "posts": len(records), "compared": compared, "hint_cards": hinted, "site_mb": round(size / 1e6, 2)}


MATRIX_CSS = """
:root{--s:30px}
main{max-width:none;padding:8px 8px 20px}
.bar{display:flex;gap:6px;align-items:center;margin:0 0 6px;font-size:12px;color:var(--muted)}
.bar button{font:inherit;padding:2px 8px;border:1px solid var(--line);border-radius:999px;background:var(--card);color:var(--fg);cursor:pointer}
.bar button.on{background:var(--accent);color:var(--bg);border-color:var(--accent)}
.wrap{overflow:auto;max-height:calc(100vh - 96px);border:1px solid var(--line);border-radius:6px;background:var(--card)}
table.m{border-collapse:separate;border-spacing:0;width:max-content;border:0;border-radius:0}
table.m th,table.m td{border-bottom:1px solid var(--line);border-right:1px solid var(--line);padding:2px;vertical-align:top}
table.m thead th{position:sticky;top:0;z-index:2;background:var(--card);font-size:10px;font-weight:600;white-space:nowrap;text-align:center;padding:2px 3px}
table.m th.s{position:sticky;left:0;z-index:1;background:var(--card);width:92px;min-width:92px;max-width:92px;font-size:10px;font-weight:500;line-height:1.25;white-space:normal;overflow:hidden}
table.m th.s a{color:var(--fg);text-decoration:none}table.m th.s small{color:var(--muted)}
table.m thead th.s{z-index:3}
td.c{min-width:calc(var(--s) + 4px)}td.c .t{display:flex;flex-wrap:wrap;gap:2px;width:calc(var(--s) * 4 + 12px)}
.g{display:contents}.g .th img{outline:1px solid var(--accent);outline-offset:-1px}
tr.q th.s{color:var(--muted)}td.e{background:repeating-linear-gradient(45deg,transparent 0 4px,var(--line) 4px 5px);opacity:.35}
.th{position:relative;display:block;width:var(--s);cursor:zoom-in}
.th img{display:block;width:var(--s);height:var(--s);object-fit:cover;object-position:top;border-radius:2px}
.th span{position:absolute;right:0;bottom:0;font-size:8px;line-height:1;padding:1px 2px;border-radius:2px;background:rgba(0,0,0,.7);color:#fff}
.th i{display:none}
body.big .th i{display:block;position:absolute;left:1px;top:1px;font-size:8px;font-style:normal;line-height:1;padding:1px 2px;border-radius:2px;background:rgba(255,255,255,.85);color:#222}
#lb{position:fixed;inset:0;background:rgba(0,0,0,.82);display:none;align-items:center;justify-content:center;z-index:9;padding:16px}
#lb.on{display:flex}#lb .in{display:flex;gap:8px;overflow-x:auto;max-width:100%;max-height:100%;align-items:flex-start}
#lb img{max-height:calc(100vh - 60px);max-width:min(92vw,420px);border-radius:6px;background:#fff}
#lb p{position:fixed;top:8px;left:16px;margin:0;color:#fff;font-size:13px}
"""


TEXT = ROOT / "data" / "line_pc_text"

COMPARE_CSS = """
main{max-width:1200px}
.store{margin:22px 0 8px;font-size:17px}
.cmp{border-top:1px solid var(--line);padding:10px 0 4px}
.row{display:grid;grid-template-columns:minmax(0,5fr) minmax(0,6fr);gap:14px;padding:4px 0 10px}
@media (max-width:760px){.row{grid-template-columns:1fr}}
.imgs{display:flex;gap:6px;overflow-x:auto}
.imgs img{width:min(100%,260px);flex:none;border-radius:6px;border:1px solid var(--line);cursor:zoom-in;background:#fff}
.imgs.one img{width:min(100%,360px)}
.when{font-size:12px;color:var(--muted);margin-bottom:4px}
.card{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:8px 10px;margin-bottom:6px}
.card h4{margin:0 0 4px;font-size:12px;color:var(--muted);font-weight:600}
.sum{font-size:14px;margin:0 0 6px}
.tags{display:flex;flex-wrap:wrap;gap:4px;margin:2px 0}
.tag{font-size:12px;padding:1px 8px;border-radius:999px;background:var(--chip)}
.tag.rec{background:#fde8c8;color:#7a4a00}.tag.cov{background:#d9ecff;color:#0b4a8a}.tag.new{background:#ddf3e4;color:#1e6b3a}
.tag.warn{background:#ffe0e0;color:#9b1c1c}
@media (prefers-color-scheme:dark){.tag.rec{background:#4a3410;color:#ffd59a}.tag.cov{background:#12324f;color:#a9d3ff}.tag.new{background:#173d26;color:#a8e6bd}.tag.warn{background:#4d1d1d;color:#ffb4b4}}
ul.ev{margin:2px 0 0;padding-left:18px;font-size:13px}
details{font-size:12px;color:var(--muted)}details pre{white-space:pre-wrap;font:12px/1.5 inherit;color:var(--fg)}
#lb{position:fixed;inset:0;background:rgba(0,0,0,.85);display:none;align-items:center;justify-content:center;z-index:9;padding:16px}
#lb.on{display:flex}#lb img{max-width:min(96vw,700px);max-height:94vh;border-radius:6px;background:#fff}
"""


def write_compare(info: dict[str, dict], records: list[dict]) -> int:
    """compare.html: each post's images next to the Vision + Qwen text (scripts/line_post_text.py)."""
    if not TEXT.exists():
        return 0
    def text_for(path: str) -> dict | None:
        cache = TEXT / f"{Path(path).stem}.json"
        return json.loads(cache.read_text(encoding="utf-8")) if cache.exists() else None
    big = SITE / "img_big"
    big.mkdir(exist_ok=True)
    by_store: dict[str, list[tuple[dict, list[str], list[dict]]]] = defaultdict(list)
    for post in records:
        images = [c for c in post.get("cards", []) if (POSTS / c).exists()] or [post["image"]]
        texts = [text_for(i) for i in images]
        if all(texts):
            by_store[post["hall_id"]].append((post, images, texts))
    esc = html.escape
    body = ["<nav class='top'><a href='index.html'>← 店舗一覧</a> ・ <a href='matrix.html'>一覧表</a></nav>"
            "<p style='font-size:12px;color:var(--muted)'>左が届いた画像、右が Vision（Mac標準の文字認識）＋ Qwen で起こした内容。"
            "<span class='tag warn'>要確認</span> は Vision の文字に見当たらない名前（Qwen の読み違い・作り話の可能性）。</p>"]
    count = 0
    for hall, items in sorted(by_store.items(), key=lambda kv: (info.get(kv[0], {}).get("store_name") or kv[0])):
        body.append(f"<h2 class='store'>{esc(info.get(hall, {}).get('store_name') or hall)}</h2>")
        items.sort(key=lambda t: (t[0].get("posted_date") or "", t[0].get("posted_time") or ""), reverse=True)
        for post, images, texts in items:
            count += 1
            imgs = []
            for path in images:
                name = Path(path).stem + ".webp"
                if not (big / name).exists():
                    with Image.open(POSTS / path) as im:
                        im = im.convert("RGB")
                        if im.width > 600:
                            im = im.resize((600, round(im.height * 600 / im.width)), Image.LANCZOS)
                        im.save(big / name, "WEBP", quality=60, method=6)
                imgs.append(f"<img loading='lazy' src='img_big/{name}' alt=''>")
            cards = []
            for i, t in enumerate(texts):
                unverified = set(t.get("unverified") or [])
                def tag(name: str, cls: str) -> str:
                    warn = " warn" if name in unverified else ""
                    return f"<span class='tag {cls}{warn}'>{esc(name)}{' ⚠要確認' if warn else ''}</span>"
                rec = [m for m in t.get("recommended_machines") or [] if isinstance(m, str) and m]
                cov = [c for c in t.get("coverage") or [] if isinstance(c, dict) and c.get("name")]
                new = [m for m in t.get("new_machines") or [] if isinstance(m, dict) and m.get("name")]
                ev = [e for e in t.get("events") or [] if isinstance(e, dict) and (e.get("content") or e.get("date"))]
                parts = [f"<h4>{'カード' + str(i + 1) if len(texts) > 1 else '内容'}</h4><p class='sum'>{esc(t.get('summary') or '（要約なし）')}</p>"]
                if rec:
                    parts.append("<div class='tags'>おすすめ " + "".join(tag(m, "rec") for m in rec) + "</div>")
                if cov:
                    parts.append("<div class='tags'>取材 " + "".join(tag(c["name"], "cov").replace("</span>", f"{(' ' + esc(str(c.get('date')))) if c.get('date') else ''}</span>", 1) for c in cov) + "</div>")
                if new:
                    parts.append("<div class='tags'>新台 " + "".join(tag(m["name"], "new").replace("</span>", f"{(' ' + esc(str(m.get('units')))) if m.get('units') else ''}</span>", 1) for m in new) + "</div>")
                if ev:
                    parts.append("<ul class='ev'>" + "".join(f"<li>{esc(str(e.get('date') or ''))} {esc(str(e.get('content') or ''))}</li>" for e in ev) + "</ul>")
                parts.append(f"<details><summary>書き起こし／Vision の文字</summary><pre>{esc(t.get('transcript') or '')}</pre><hr><pre>{esc(t.get('vision_text') or '')}</pre></details>")
                cards.append("<div class='card'>" + "".join(parts) + "</div>")
            when = f"{day_label(post.get('posted_date'))} {esc(post.get('posted_time') or '')}" + (f" ・ 横並び{len(imgs)}枚" if len(imgs) > 1 else "")
            body.append(f"<div class='cmp'><div class='when'>{when}</div>" + "".join(
                f"<div class='row'><div class='imgs one'>{img}</div><div>{card}</div></div>" for img, card in zip(imgs, cards)) + "</div>")
    body.append("<div id='lb'><img alt=''></div><script>const lb=document.getElementById('lb'),li=lb.querySelector('img');"
                "document.querySelectorAll('.imgs img').forEach(i=>i.addEventListener('click',()=>{li.src=i.src;lb.classList.add('on')}));"
                "lb.addEventListener('click',()=>lb.classList.remove('on'));</script>")
    (SITE / "compare.html").write_text(page("画像と文字の比較", f"{len(by_store)}店舗 ・ {count}件（Vision＋Qwen）",
                                            f"<style>{COMPARE_CSS}</style>" + "".join(body), ""), encoding="utf-8")
    return count


def write_hints(info: dict[str, dict]) -> int:
    """hints.html: evening machine-hint cards (scripts/line_hints.py) - store, day, frame colour, machine."""
    path = ROOT / "data" / "line_pc_hints" / "hints.jsonl"
    if not path.exists():
        return 0
    rows = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    esc = html.escape
    big = SITE / "img_big"
    big.mkdir(exist_ok=True)
    by_store: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_store[row["hall_id"]].append(row)
    body = ["<style>.hint td{vertical-align:middle}.sw{display:inline-block;width:14px;height:14px;border-radius:3px;border:1px solid var(--line);vertical-align:-2px;margin-right:4px}"
            ".hint img{width:90px;border-radius:4px;cursor:zoom-in}#lb{position:fixed;inset:0;background:rgba(0,0,0,.85);display:none;align-items:center;justify-content:center;z-index:9}"
            "#lb.on{display:flex}#lb img{max-width:min(96vw,600px);max-height:94vh;border-radius:6px}</style>",
            "<nav class='top'><a href='index.html'>← 店舗一覧</a> ・ <a href='compare.html'>画像と文字の比較</a></nav>",
            "<p style='font-size:12px;color:var(--muted)'>夕方〜夜に届く「設置機種ご案内」「機種情報」などの機種カード。枠の色は画素から測定（LLMなし）、機種名は Vision＋Qwen。</p>"]
    for hall, items in sorted(by_store.items(), key=lambda kv: info.get(kv[0], {}).get("store_name") or kv[0]):
        items.sort(key=lambda r: (r.get("posted_date") or "", r.get("posted_time") or ""), reverse=True)
        body.append(f"<h2 class='store' style='font-size:16px;margin:18px 0 6px'>{esc(info.get(hall, {}).get('store_name') or hall)}</h2>"
                    "<table class='hint'><thead><tr><th>届いた日時</th><th>枠の色</th><th>機種</th><th>種別</th><th>画像</th></tr></thead><tbody>")
        for r in items:
            name = Path(r["image"]).stem + ".webp"
            if not (big / name).exists():
                with Image.open(POSTS / r["image"]) as im:
                    im = im.convert("RGB")
                    if im.width > 600:
                        im = im.resize((600, round(im.height * 600 / im.width)), Image.LANCZOS)
                    im.save(big / name, "WEBP", quality=60, method=6)
            rgb = r.get("rgb") or [200, 200, 200]
            body.append(f"<tr><td>{day_label(r.get('posted_date'))} {esc(r.get('posted_time') or '')}</td>"
                        f"<td><span class='sw' style='background:rgb({rgb[0]},{rgb[1]},{rgb[2]})'></span>{esc(r.get('colour') or '')}</td>"
                        f"<td>{esc(r.get('machine') or '（読めず）')}</td><td>{esc(r.get('kind') or '')}</td>"
                        f"<td><img loading='lazy' src='img_big/{name}' alt=''></td></tr>")
        body.append("</tbody></table>")
    body.append("<div id='lb'><img alt=''></div><script>const lb=document.getElementById('lb'),li=lb.querySelector('img');"
                "document.querySelectorAll('.hint img').forEach(i=>i.addEventListener('click',()=>{li.src=i.src;lb.classList.add('on')}));"
                "lb.addEventListener('click',()=>lb.classList.remove('on'));</script>")
    (SITE / "hints.html").write_text(page("機種カード（示唆）", f"{len(by_store)}店舗 ・ {len(rows)}枚", "".join(body), ""), encoding="utf-8")
    return len(rows)


def short_day(value: str) -> str:
    if not value:
        return "不明"
    d = date.fromisoformat(value)
    return f"{d.month}/{d.day}{WEEKDAY[d.weekday()]}"


def write_matrix(rows: list, by_store: dict[str, list[dict]], info: dict[str, dict]) -> None:
    """One table: a row per store, a column per posting day, small thumbnails in each cell."""
    days = sorted({p.get("posted_date") or "" for posts in by_store.values() for p in posts}, reverse=True)
    head = "".join(f"<th>{html.escape(short_day(d))}</th>" for d in days)
    body = []
    for _last, hall, name, _meta, count, _days in rows:
        cells = []
        for d in days:
            items = []
            for post in sorted((p for p in by_store[hall] if (p.get("posted_date") or "") == d), key=lambda r: r.get("posted_time") or "99:99"):
                srcs = post.get("_srcs") or []
                if not srcs:
                    continue
                data = html.escape(json.dumps(["img/" + x for x in srcs]), quote=True)
                cap = html.escape(f"{name} ・ {day_label(d) if d else '日付不明'} {post.get('posted_time') or ''}")
                when = f"<i>{html.escape(post['posted_time'])}</i>" if post.get("posted_time") else ""
                # every card of a side-by-side post gets its own thumbnail; a frame keeps them together
                thumbs = "".join(f"<a class='th' data-imgs=\"{data}\" data-cap=\"{cap}\"><img loading='lazy' src='img/{src}' alt=''>{when if i == 0 else ''}</a>"
                                 for i, src in enumerate(srcs))
                items.append(f"<span class='g'>{thumbs}</span>" if len(srcs) > 1 else thumbs)
            cells.append(f"<td class='c'><div class='t'>{''.join(items)}</div></td>" if items else "<td class='c'></td>")
        body.append(f"<tr><th class='s'><a href='stores/{html.escape(hall)}.html' title='{html.escape(name)}'>{html.escape(name)}</a> <small>{count}</small></th>{''.join(cells)}</tr>")
    # registered stores with nothing captured yet, so the table shows the whole roster
    quiet = sorted((meta.get("store_name") or hall, hall) for hall, meta in info.items() if hall not in by_store and meta.get("store_name"))
    for name, hall in quiet:
        body.append(f"<tr class='q'><th class='s'>{html.escape(name)} <small>0</small></th>{'<td class=c></td>' * len(days)}</tr>")
    script = ("<div id='lb'><p></p><div class='in'></div></div><script>"
              "const lb=document.getElementById('lb'),inn=lb.querySelector('.in'),cap=lb.querySelector('p');"
              "document.querySelectorAll('.th').forEach(a=>a.addEventListener('click',()=>{inn.innerHTML='';"
              "JSON.parse(a.dataset.imgs).forEach(s=>{const i=document.createElement('img');i.src=s;inn.appendChild(i)});"
              "cap.textContent=a.dataset.cap;lb.classList.add('on')}));"
              "lb.addEventListener('click',()=>lb.classList.remove('on'));"
              "document.addEventListener('keydown',e=>{if(e.key==='Escape')lb.classList.remove('on')});"
              "const sizes={'極小':'20px','小':'30px','中':'44px','大':'64px'};"
              "function setSize(k){document.documentElement.style.setProperty('--s',sizes[k]);document.body.classList.toggle('big',k==='大'||k==='中');"
              "document.querySelectorAll('.bar button').forEach(b=>b.classList.toggle('on',b.textContent===k));try{localStorage.setItem('mSize',k)}catch(e){}}"
              "document.querySelectorAll('.bar button').forEach(b=>b.addEventListener('click',()=>setSize(b.textContent)));"
              "let k0='小';try{k0=localStorage.getItem('mSize')||'小'}catch(e){};setSize(sizes[k0]?k0:'小');</script>")
    bar = "<div class='bar'><a href='index.html'>← 店舗一覧</a><span style='flex:1'></span>画像サイズ " + "".join(f"<button>{k}</button>" for k in ("極小", "小", "中", "大")) + "</div>"
    content = (f"<style>{MATRIX_CSS}</style>{bar}"
               f"<div class='wrap'><table class='m'><thead><tr><th class='s'>店舗</th>{head}</tr></thead>"
               f"<tbody>{''.join(body)}</tbody></table></div>{script}")
    (SITE / "matrix.html").write_text(page("日付×店舗の一覧表", f"投稿あり{len(rows)}店舗 ／ 登録{len(rows) + len(quiet)}店舗 ・ {len(days)}日 ・ 画像をクリックで拡大", content, ""), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--since")
    args = parser.parse_args()
    print(json.dumps(build(args.since), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
