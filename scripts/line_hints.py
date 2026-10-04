"""Record the machine-hint cards some stores send in the evening (Mac, no cloud).

    .venv/bin/python scripts/line_hints.py [--since 2026-09-25]

UNO-group stores (中山UNO, ZoRoN, 相模大野UNO, 小田急相模原UNO) send 「設置機種ご案内」/
「機種情報」 cards in the evening; regulars read the machine and the frame colour
(gold, red, ...) as a hint for the next day even though the stores add a "公約等は
当店と関係ありません" notice. グリーン and SKIP関内店 send similar machine-only cards.

For each such card: the frame colour is measured from pixels (no LLM) and the
machine name is read by Vision + local Qwen. Results go to
data/line_pc_hints/hints.jsonl (git-ignored) and the site's hints.html.
"""

from __future__ import annotations

import argparse
import base64
import colorsys
import io
import json
import re
import subprocess
import urllib.request
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
POSTS = ROOT / "data" / "line_pc_posts"
OUT = ROOT / "data" / "line_pc_hints"
VISION = ROOT / "build" / "vision_ocr"
MODEL = "qwen3.8:latest"

# store -> how its hint cards are recognised
HINT_STORES = {
    "nakayama-uno": "ask",                 # UNO group: Vision garbles the label, Qwen decides
    "hall-67af17de3fd85a54": "ask",        # ZoRoN (UNO group)
    "sagami-no-uno": "ask",
    "odaky-sagamihara-uno": "ask",
    "gur-n": "keyword",                    # グリーン: 設置機種のご案内
    "hall-ee471f0e0e99e2a4": "all_cards",  # SKIP関内店: nightly machine carousel
}
# Vision often garbles the slanted 「設置機種ご案内」 label (穖種 / 設導 / ご楽内), so match loosely
# and leave out the store's other cards (draw times, opening hours, notices)
KEYWORD = re.compile(r"設置機種|機種情報|機種のご案内|[機穖][種穜]|設[置導]|ご[案楽]内")
# the UNO cards' slanted label as Vision reads it: a short line starting with ご (ご案内 / ご楽内 / ご親)
# or a garbled 機種 (穖種, 機蓮, 機麺); 機種情報 on ZoRoN
LABEL = re.compile(r"(^|\n)ご.{0,2}(\n|$)|[機穖][種穜蓮麺]|機種情報")
EXCLUDE = re.compile(r"抽選|入場|営業時間|公約|フォロワー|開店|整列|LINE@|登録ありがとう")

PROMPT = """これはパチンコ店の公式LINEに届いた機種紹介のカード画像です。下の「OCR結果」は別の文字認識の結果で誤りを含みます。
画像に大きく描かれている機種（遊技機）の名前を、画像とOCR結果から答えてください。パチンコかスロット（スマスロ等）かも分かれば答えてください。
画像に機種名が無い、または読めない場合は machine を空にしてください。推測で作らないでください。
あわせて、このカードが「設置機種ご案内」「機種情報」のように機種を紹介するカードかどうか（営業時間・抽選・取材・注意書きなどではないか）を machine_card で答えてください。
JSONで返してください: {{"machine_card": true, "machine": "機種名", "kind": "パチンコ/スロット/不明"}}

OCR結果:
{ocr}"""


def frame_colour(path: Path) -> tuple[str, list[int]]:
    """Name of the card's frame colour, measured on a band just inside its edge."""
    a = np.asarray(Image.open(path).convert("RGB")).astype(float) / 255
    h, w, _ = a.shape
    band = np.concatenate([a[2:9].reshape(-1, 3), a[h - 9:h - 2].reshape(-1, 3),
                           a[:, 2:9].reshape(-1, 3), a[:, w - 9:w - 2].reshape(-1, 3)])
    hsv = np.array([colorsys.rgb_to_hsv(*p) for p in band[::5]])
    coloured = hsv[(hsv[:, 1] > 0.25) & (hsv[:, 2] > 0.25)]
    rgb = [int(v * 255) for v in np.median(band, axis=0)]
    if len(coloured) < len(hsv) * 0.3:
        value = float(np.median(hsv[:, 2]))
        return ("白・銀" if value > 0.75 else "黒" if value < 0.3 else "灰"), rgb
    hue = float(np.median(coloured[:, 0])) * 360
    if hue >= 345 or hue < 15:
        name = "赤"
    elif hue < 40:
        name = "橙"
    elif hue < 70:
        name = "金・黄"
    elif hue < 170:
        name = "緑"
    elif hue < 255:
        name = "青"
    elif hue < 290:
        name = "紫"
    else:
        name = "ピンク"
    picked = band[::5][(hsv[:, 1] > 0.25) & (hsv[:, 2] > 0.25)]
    return name, [int(v * 255) for v in np.median(picked, axis=0)]


def vision(path: Path) -> str:
    image = Image.open(path).convert("RGB")
    big = OUT / "_vision.png"
    image.resize((image.width * 2, image.height * 2), Image.LANCZOS).save(big)
    out = subprocess.run([str(VISION), str(big)], capture_output=True, text=True, timeout=120).stdout
    lines = json.loads(out.splitlines()[0])["lines"]
    lines.sort(key=lambda l: (l["box"][1] // 12, l["box"][0]))
    return "\n".join(l["text"] for l in lines)


def qwen_machine(path: Path, ocr: str) -> dict:
    image = Image.open(path).convert("RGB")
    image = image.resize((image.width * 2, image.height * 2), Image.LANCZOS)
    buf = io.BytesIO()
    image.save(buf, "PNG")
    body = {"model": MODEL, "stream": False, "think": False, "format": "json",
            "options": {"temperature": 0, "num_predict": 200, "num_ctx": 4096},
            "messages": [{"role": "user", "content": PROMPT.format(ocr=ocr or "（なし）"),
                          "images": [base64.b64encode(buf.getvalue()).decode()]}]}
    req = urllib.request.Request("http://localhost:11434/api/chat", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as resp:
        content = json.loads(resp.read())["message"]["content"]
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return {"machine": "", "raw": content}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--since", default=None)
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    records = [json.loads(l) for l in (POSTS / "posts.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    rows = []
    for post in records:
        mode = HINT_STORES.get(post["hall_id"])
        if not mode or (args.since and (post.get("posted_date") or "") < args.since):
            continue
        images = [c for c in post.get("cards", [])] or [post["image"]]
        if mode == "all_cards" and not post.get("cards"):
            continue
        for rel in images:
            path = POSTS / rel
            cache = OUT / f"{path.stem}.json"
            if cache.exists():
                row = json.loads(cache.read_text(encoding="utf-8"))
            else:
                ocr = vision(path)
                if (mode == "keyword" and (not KEYWORD.search(ocr) or EXCLUDE.search(ocr))) or (mode == "ask" and EXCLUDE.search(ocr)):
                    row = {"hint": False, "vision_text": ocr}
                else:
                    colour, rgb = frame_colour(path)
                    answer = qwen_machine(path, ocr)
                    keep = bool(answer.get("machine")) and (mode != "ask" or answer.get("machine_card") is True)
                    row = {"hint": keep, "colour": colour, "rgb": rgb, **answer, "vision_text": ocr}
                cache.write_text(json.dumps(row, ensure_ascii=False, indent=1), encoding="utf-8")
            if row.get("hint") and mode == "ask" and not LABEL.search(row.get("vision_text") or ""):
                continue  # Qwen called it a machine card, but the card has no 設置機種ご案内/機種情報 label
            if row.get("hint") and mode == "ask" and row.get("rgb"):
                # UNO-group frames are red or gold: take the nearer of the two
                r_, g_, b_ = (v / 255 for v in row["rgb"])
                hue = colorsys.rgb_to_hsv(r_, g_, b_)[0] * 360
                row = dict(row, colour_detail=row.get("colour"),
                           colour="赤" if min(abs(hue - 355), 360 - abs(hue - 355)) < abs(hue - 50) else "金")
            if row.get("hint"):
                rows.append({"hall_id": post["hall_id"], "posted_date": post.get("posted_date"), "posted_time": post.get("posted_time"),
                             "image": rel, **{k: v for k, v in row.items() if k != "vision_text"}})
                print(json.dumps(rows[-1], ensure_ascii=False), flush=True)
    rows.sort(key=lambda r: (r["hall_id"], r.get("posted_date") or "", r.get("posted_time") or ""))
    with (OUT / "hints.jsonl").open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(json.dumps({"hint_cards": len(rows)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
