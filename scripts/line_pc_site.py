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
                    imgs = "".join(f"<img loading='lazy' src='../img/{webp(POSTS / c, SITE / 'img' / (Path(c).stem + '.webp'))}' alt=''>" for c in cards)
                    media, cls = f"<div class='cards'>{imgs}</div>", "post wide"
                else:
                    src = webp(POSTS / post["image"], SITE / "img" / (post["post_id"] + ".webp"))
                    media, cls = f"<img loading='lazy' src='../img/{src}' alt=''>", "post"
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
    table = ["<input id='q' placeholder='店名で絞り込み'><table><thead><tr><th>店舗</th><th>最新の投稿</th>"
             "<th class='n'>件数</th><th class='n'>日数</th><th>Type</th><th>最新情報の送信</th></tr></thead><tbody>"]
    for last, hall, name, meta, count, days in rows:
        table.append(f"<tr data-name='{html.escape(name)}'><td><a href='stores/{html.escape(hall)}.html'>{html.escape(name)}</a></td>"
                     f"<td>{day_label(last) if last else '—'}</td><td class='n'>{count}</td><td class='n'>{days}</td>"
                     f"<td><span class='chip'>{TYPE.get(meta.get('collection_type', ''), '')}</span></td>"
                     f"<td>{TRIGGER.get(meta.get('text_trigger', ''), '')}</td></tr>")
    table.append("</tbody></table><script>const q=document.getElementById('q');q.addEventListener('input',()=>{"
                 "document.querySelectorAll('tbody tr').forEach(r=>{r.style.display=r.dataset.name.includes(q.value.trim())?'':'none'})})</script>")
    (SITE / "index.html").write_text(page("LINE投稿タイムライン", f"{len(rows)}店舗 ・ {len(records)}件", "".join(table), ""), encoding="utf-8")
    size = sum(p.stat().st_size for p in SITE.rglob("*") if p.is_file())
    return {"stores": len(rows), "posts": len(records), "site_mb": round(size / 1e6, 2)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--since")
    args = parser.parse_args()
    print(json.dumps(build(args.since), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
