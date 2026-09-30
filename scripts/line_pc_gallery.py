"""Build a one-file HTML gallery of cut LINE posts, grouped by store (no LLM).

    .venv/bin/python scripts/line_pc_gallery.py [--since 2026-09-30] [--output data/line_pc_posts/gallery.html]

Images are downscaled and embedded, so the file can be opened anywhere.
The output lives under data/line_pc_posts/ (git-ignored).
"""

from __future__ import annotations

import argparse
import base64
import html
import io
import json
from collections import defaultdict
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
POSTS = ROOT / "data" / "line_pc_posts"
THUMB_WIDTH = 360


def thumb(path: Path) -> str:
    with Image.open(path) as image:
        image = image.convert("RGB")
        if image.width > THUMB_WIDTH:
            image = image.resize((THUMB_WIDTH, round(image.height * THUMB_WIDTH / image.width)))
        buffer = io.BytesIO()
        image.save(buffer, "JPEG", quality=72)
    return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode()


def store_names() -> dict[str, dict]:
    names = {}
    targets = ROOT / "data" / "line_targets.json"
    plan = ROOT / "data" / "line_collection_plan.json"
    if targets.exists():
        for row in json.loads(targets.read_text(encoding="utf-8"))["targets"]:
            names[row["hall_id"]] = {"name": row.get("store_name") or row["hall_id"]}
    if plan.exists():
        for row in json.loads(plan.read_text(encoding="utf-8"))["stores"]:
            names.setdefault(row["hall_id"], {"name": row["hall_id"]}).update(
                collection_type=row["collection_type"], text_trigger=row["text_trigger"])
    return names


TYPE_LABEL = {"type_a_passive": "A", "type_b_passive_plus_active": "B", "type_c_passive_external_web": "C", "unresolved": "未分類"}

CSS = """
:root{--bg:#f6f6f4;--fg:#1d1d1b;--muted:#6b6b66;--card:#fff;--line:#e2e1dc;--accent:#1f6f5c}
@media (prefers-color-scheme:dark){:root{--bg:#161615;--fg:#ecebe6;--muted:#a3a29b;--card:#20201e;--line:#34332f;--accent:#6fc2a8}}
*{box-sizing:border-box}body{margin:0;font:14px/1.5 -apple-system,"Hiragino Sans","Noto Sans JP",sans-serif;background:var(--bg);color:var(--fg)}
header{position:sticky;top:0;z-index:2;background:var(--bg);border-bottom:1px solid var(--line);padding:12px 16px}
h1{font-size:18px;margin:0 0 8px}nav{display:flex;flex-wrap:wrap;gap:6px}
nav a{font-size:12px;padding:3px 8px;border:1px solid var(--line);border-radius:999px;color:var(--fg);text-decoration:none;background:var(--card)}
nav a b{color:var(--accent)}input{width:100%;max-width:420px;margin:0 0 8px;padding:6px 10px;border:1px solid var(--line);border-radius:6px;background:var(--card);color:var(--fg)}
section{padding:16px}h2{font-size:16px;margin:8px 0 4px}.meta{color:var(--muted);font-size:12px;margin-bottom:10px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:12px}
figure{margin:0;background:var(--card);border:1px solid var(--line);border-radius:8px;overflow:hidden}
figure img{display:block;width:100%;height:auto}.cards{display:flex;gap:4px;overflow-x:auto;padding:4px}.cards img{width:120px;flex:none;border-radius:4px}
figcaption{padding:6px 8px;font-size:12px}figcaption .when{font-weight:600}
details{color:var(--muted)}details pre{white-space:pre-wrap;margin:4px 0 0;font:11px/1.4 ui-monospace,monospace}
"""


def build(since: str | None) -> str:
    records = [json.loads(line) for line in (POSTS / "posts.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    if since:
        records = [r for r in records if (r.get("posted_date") or r["capture_date"]) >= since]
    names = store_names()
    by_store: dict[str, list[dict]] = defaultdict(list)
    for record in records:
        by_store[record["hall_id"]].append(record)
    order = sorted(by_store, key=lambda h: -len(by_store[h]))
    parts = [f"<!doctype html><html lang='ja'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
             f"<title>LINE投稿一覧</title><style>{CSS}</style></head><body><header><h1>LINE投稿一覧 — {len(records)}件 / {len(order)}店舗</h1>"
             "<input id='q' placeholder='店名・OCR文字で絞り込み'><nav>"]
    for hall in order:
        info = names.get(hall, {"name": hall})
        parts.append(f"<a href='#{html.escape(hall)}'>{html.escape(info['name'])} <b>{len(by_store[hall])}</b></a>")
    parts.append("</nav></header>")
    for hall in order:
        info = names.get(hall, {"name": hall})
        posts = sorted(by_store[hall], key=lambda r: ((r.get("posted_date") or ""), (r.get("posted_time") or "")), reverse=True)
        label = TYPE_LABEL.get(info.get("collection_type", ""), "")
        trigger = {"daily": "毎日「最新情報」送信", "verify_once": "送信確認中", "off": "送信なし"}.get(info.get("text_trigger", ""), "")
        parts.append(f"<section id='{html.escape(hall)}' data-store='{html.escape(info['name'])}'><h2>{html.escape(info['name'])}</h2>"
                     f"<div class='meta'>{html.escape(hall)} ・ Type {label} ・ {trigger} ・ {len(posts)}件</div><div class='grid'>")
        for record in posts:
            when = f"{record.get('posted_date') or '日付不明'} {record.get('posted_time') or ''}".strip()
            cards = "".join(f"<img loading='lazy' src='{thumb(POSTS / c)}'>" for c in record.get("cards", []) if (POSTS / c).exists())
            ocr = html.escape(record.get("ocr_text") or "")
            parts.append(f"<figure data-text='{ocr}'><img loading='lazy' src='{thumb(POSTS / record['image'])}'>"
                         + (f"<div class='cards'>{cards}</div>" if cards else "")
                         + f"<figcaption><span class='when'>{html.escape(when)}</span> ・ 取得 {record['capture_date']}"
                         + (f"<details><summary>OCR</summary><pre>{ocr}</pre></details>" if ocr else "")
                         + "</figcaption></figure>")
        parts.append("</div></section>")
    parts.append("""<script>
const q=document.getElementById('q');q.addEventListener('input',()=>{const v=q.value.trim();
document.querySelectorAll('section').forEach(s=>{let any=false;s.querySelectorAll('figure').forEach(f=>{
const hit=!v||s.dataset.store.includes(v)||(f.dataset.text||'').includes(v);f.style.display=hit?'':'none';any=any||hit});
s.style.display=any?'':'none'})});
</script></body></html>""")
    return "".join(parts)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--since")
    parser.add_argument("--output", type=Path, default=POSTS / "gallery.html")
    args = parser.parse_args()
    args.output.write_text(build(args.since), encoding="utf-8")
    print(args.output, round(args.output.stat().st_size / 1e6, 2), "MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
