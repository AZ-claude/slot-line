"""Turn cut LINE post images into text with Vision + Qwen (on the Mac, no cloud).

    .venv/bin/python scripts/line_post_text.py --halls nakayama-uno,pia-keiky-kawasaki --since 2026-09-28

For every post image (and every card of a side-by-side post):
  1. macOS Vision reads the text (build/vision_ocr; no LLM)
  2. local Qwen (Ollama) gets the image enlarged 2x plus Vision's lines as a
     reference that may contain mistakes, and returns JSON: a short summary,
     recommended machines, coverage visits (取材), dated events, new machines
     and a transcript
  3. machine / coverage names that do not resemble anything Vision read are
     marked "unverified" (Qwen invents plausible names on unreadable text)

Results are cached as data/line_pc_text/<image stem>.json (git-ignored).
"""

from __future__ import annotations

import argparse
import base64
import difflib
import io
import json
import subprocess
import time
import unicodedata
import urllib.request
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
POSTS = ROOT / "data" / "line_pc_posts"
OUT = ROOT / "data" / "line_pc_text"
VISION = ROOT / "build" / "vision_ocr"
MODEL = "qwen3.8:latest"

PROMPT = """これはパチンコ店「{store}」の公式LINEに{date}に届いた画像です。
下の「OCR結果」は別の文字認識で読んだもので、誤りや抜けを含みます。画像をよく見て、OCR結果を参考にしながら、画像に書かれている内容を次のJSONで返してください。
画像に書かれていないことは書かないでください。読めない機種名は推測せず省いてください。日付は分かれば YYYY-MM-DD（年は{year}年）にしてください。

{{
 "summary": "何の案内かを1〜2文で",
 "recommended_machines": ["オススメ・推し・注目として挙げられている機種名"],
 "coverage": [{{"name": "取材・来店の名前（媒体名や演者名）", "date": "日付"}}],
 "events": [{{"date": "日付", "content": "その日の内容（開店時刻・抽選・イベントなど）"}}],
 "new_machines": [{{"name": "新台・増台の機種名", "units": "台数（分かれば）"}}],
 "transcript": "画像の文字を上から順に書き起こしたもの"
}}

OCR結果:
{ocr}"""


def fold(text: str) -> str:
    return "".join(unicodedata.normalize("NFKC", text).split()).lower()


def supported(name: str, ocr: str) -> bool:
    """Does the name (roughly) appear in what Vision read? Partial matches count."""
    a, b = fold(name), fold(ocr)
    if not a:
        return False
    if a in b:
        return True
    window = len(a)
    best = max((difflib.SequenceMatcher(None, a, b[i:i + window]).ratio() for i in range(0, max(1, len(b) - window + 1))), default=0)
    return best >= 0.6


def vision(image: Image.Image, scratch: Path) -> str:
    path = scratch / "_vision.png"
    image.save(path)
    out = subprocess.run([str(VISION), str(path)], capture_output=True, text=True, timeout=120).stdout
    lines = json.loads(out.splitlines()[0])["lines"]
    lines.sort(key=lambda l: (l["box"][1] // 12, l["box"][0]))
    return "\n".join(l["text"] for l in lines)


def qwen(prompt: str, image: Image.Image) -> dict:
    buf = io.BytesIO()
    image.convert("RGB").save(buf, "PNG")
    body = {"model": MODEL, "stream": False, "think": False, "format": "json",
            "options": {"temperature": 0, "num_predict": 1500, "num_ctx": 8192, "repeat_penalty": 1.1},
            "messages": [{"role": "user", "content": prompt, "images": [base64.b64encode(buf.getvalue()).decode()]}]}
    req = urllib.request.Request("http://localhost:11434/api/chat", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=900) as resp:
        content = json.loads(resp.read())["message"]["content"]
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return {"summary": "", "transcript": content, "parse_error": True}


def read_image(path: Path, store: str, date: str | None) -> dict:
    cache = OUT / f"{path.stem}.json"
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    OUT.mkdir(parents=True, exist_ok=True)
    image = Image.open(path).convert("RGB")
    big = image.resize((image.width * 2, image.height * 2), Image.LANCZOS)
    ocr = vision(big, OUT)
    start = time.time()
    result = qwen(PROMPT.format(store=store, date=date or "日付不明", year=(date or "2026")[:4], ocr=ocr or "（なし）"), big)
    names = [m for m in result.get("recommended_machines") or [] if isinstance(m, str)]
    names += [m.get("name", "") for m in result.get("new_machines") or [] if isinstance(m, dict)]
    names += [c.get("name", "") for c in result.get("coverage") or [] if isinstance(c, dict)]
    result["unverified"] = sorted({n for n in names if n and not supported(n, ocr)})
    result.update(image=str(path.relative_to(ROOT)), vision_text=ocr, model=MODEL, seconds=round(time.time() - start, 1))
    cache.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--halls", required=True, help="comma-separated hall_ids")
    parser.add_argument("--since", default=None, help="only posts on or after this date")
    parser.add_argument("--limit", type=int, default=15, help="newest posts per store")
    args = parser.parse_args()
    names = {t["hall_id"]: t.get("store_name") or t["hall_id"] for t in json.loads((ROOT / "data" / "line_targets.json").read_text(encoding="utf-8"))["targets"]}
    records = [json.loads(l) for l in (POSTS / "posts.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    for hall in args.halls.split(","):
        posts = [r for r in records if r["hall_id"] == hall and (not args.since or (r.get("posted_date") or "") >= args.since)]
        posts.sort(key=lambda r: (r.get("posted_date") or "", r.get("posted_time") or ""), reverse=True)
        for post in posts[:args.limit]:
            images = [POSTS / c for c in post.get("cards", [])] or [POSTS / post["image"]]
            for path in images:
                result = read_image(path, names.get(hall, hall), post.get("posted_date"))
                print(json.dumps({"hall": hall, "image": path.name, "seconds": result.get("seconds"),
                                  "summary": (result.get("summary") or "")[:60], "unverified": result.get("unverified")},
                                 ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
