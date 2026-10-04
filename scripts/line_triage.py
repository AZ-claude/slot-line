"""Sort every LINE post image into what is worth reading, in three cheap-to-dear steps (Mac).

    .venv/bin/python scripts/line_triage.py [--since 2026-09-25] [--limit-stage2 N]

Step 1 - no LLM, every image (each card of a side-by-side post on its own):
  * an image this store already sent (same picture, dHash) reuses the earlier
    verdict - nothing is sent to a model again, but the new date is recorded
  * macOS Vision reads the text (build/vision_ocr)
  * routine notices (opening/draw times, prizes, member info ...) with no machine
    words are set aside as "routine" without a model
Step 2 - fast Qwen (qwen3.6:35b) puts the rest into one category:
  machine_hint      a card/picture that just shows a machine (evening teasers,
                    設置機種ご案内, 機種情報 ...)
  recommend_period  machines named as オススメ/推し for a stated period
  event_day         a specific day's event (取材, 周年, 特定日 ...)
  other             everything else
Step 3 - accurate Qwen (qwen3.8) reads machine names (and period/colour) for
  machine_hint and recommend_period only.

Plain-text bubbles go to step 2 as text (no image). Results are cached per image
in data/line_pc_triage/ (git-ignored); triage.jsonl has one row per image and day.
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from line_hints import frame_colour  # noqa: E402
from line_pc_posts import fingerprint, hamming  # noqa: E402

POSTS = ROOT / "data" / "line_pc_posts"
OUT = ROOT / "data" / "line_pc_triage"
VISION = ROOT / "build" / "vision_ocr"
FAST, ACCURATE = "qwen3.6:35b", "qwen3.8:latest"
CATEGORIES = ("machine_hint", "recommend_period", "event_day", "other")

ROUTINE = re.compile(r"営業時間|抽選|開店|入場|整列|公約|会員|アプリ|景品|交換会|感謝|友だち|友達|通知|駐車場|ご来店|お待ちして|OPEN|オープン")
SIGNAL = re.compile(r"機種|オススメ|おすすめ|オスス|推し|推|注目|設置|系|末尾|並び|全台|台番|ジャグ|喰種|リコリス|北斗|GOD|エヴァ|スマスロ|パチスロ|ぱちんこ")

SORT_PROMPT = """パチンコ店「{store}」の公式LINEに{when}に届いた{what}です。{ocr_note}
次のどれか1つに分類してください。
- machine_hint: 特定の機種だけを見せる画像（「設置機種ご案内」「機種情報」、夜に届く機種の画像、機種を伏せた予告など）。翌日の狙い目を示唆している可能性があるもの
- recommend_period: 「オススメ」「推し」「注目」などとして、期間（今週・今月・○日〜○日・毎日）つきで機種を名指ししているもの
- event_day: 特定の日のイベント（取材・来店・周年・○の日など）の告知
- other: 上のどれでもないもの（営業時間・抽選・景品・会員案内・挨拶・新台入替の案内など）
JSONで返してください: {{"category": "machine_hint|recommend_period|event_day|other", "reason": "理由を短く"}}
{text}"""

READ_PROMPT = """パチンコ店「{store}」の公式LINEに{when}に届いた画像です。下の「OCR結果」は別の文字認識の結果で誤りを含みます。
画像とOCR結果から、名指しされている機種名と、期間（あれば）を答えてください。画像に無い機種名を作らないでください。読めない機種は省いてください。
JSONで返してください: {{"machines": ["機種名"], "period": "期間（例: 2026-09-28〜2026-10-04、今週、今月、毎日。無ければ空）", "note": "補足を短く"}}

OCR結果:
{ocr}"""


def vision(path: Path) -> str:
    image = Image.open(path).convert("RGB")
    big = OUT / "_vision.png"
    image.resize((image.width * 2, image.height * 2), Image.LANCZOS).save(big)
    out = subprocess.run([str(VISION), str(big)], capture_output=True, text=True, timeout=120).stdout
    lines = json.loads(out.splitlines()[0])["lines"]
    lines.sort(key=lambda l: (l["box"][1] // 12, l["box"][0]))
    return "\n".join(l["text"] for l in lines)


def ask(model: str, prompt: str, image: Image.Image | None, predict: int) -> dict:
    message = {"role": "user", "content": prompt}
    if image is not None:
        buf = io.BytesIO()
        image.convert("RGB").save(buf, "PNG")
        message["images"] = [base64.b64encode(buf.getvalue()).decode()]
    body = {"model": model, "stream": False, "think": False, "format": "json",
            "options": {"temperature": 0, "num_predict": predict, "num_ctx": 8192}, "messages": [message]}
    req = urllib.request.Request("http://localhost:11434/api/chat", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=900) as resp:
        content = json.loads(resp.read())["message"]["content"]
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return {"raw": content}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--since", default=None)
    parser.add_argument("--limit-stage2", type=int, default=0, help="stop after this many new model sorts (0: no limit)")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    names = {t["hall_id"]: t.get("store_name") or t["hall_id"]
             for t in json.loads((ROOT / "data" / "line_targets.json").read_text(encoding="utf-8"))["targets"]}
    records = [json.loads(l) for l in (POSTS / "posts.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    records.sort(key=lambda r: (r.get("posted_date") or "", r.get("posted_time") or ""))
    seen: dict[str, list[tuple[str, Path]]] = {}  # store -> (fingerprint, cache file) of images already judged
    rows, sorted_now, counts = [], 0, {}
    to_read: list[tuple[Path, Path, str, str]] = []
    for post in records:
        if args.since and (post.get("posted_date") or "") < args.since:
            continue
        hall = post["hall_id"]
        when = f"{post.get('posted_date') or '日付不明'} {post.get('posted_time') or ''}".strip()
        images = post.get("cards") or [post["image"]]
        text_bubble = not post.get("cards") and post["height"] < 260 and len(post.get("ocr_text") or "") > 40
        for rel in images:
            path = POSTS / rel
            image = Image.open(path).convert("RGB")
            fp = fingerprint(image)
            earlier = next((c for f, c in seen.get(hall, []) if hamming(f, fp) <= 6), None)
            cache = OUT / f"{path.stem}.json"
            if earlier and not cache.exists():
                result = dict(json.loads(earlier.read_text(encoding="utf-8")), repeat_of=earlier.stem)
                cache.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
            result = json.loads(cache.read_text(encoding="utf-8")) if cache.exists() else {}
            if "stage1" not in result:
                result["vision_text"] = (post.get("ocr_text") or "") if text_bubble else vision(path)
                text = result["vision_text"]
                if text_bubble:
                    result["stage1"] = "text_bubble"
                elif ROUTINE.search(text) and not SIGNAL.search(text):
                    result["stage1"] = "routine"
                    result["category"] = "other"
                else:
                    result["stage1"] = "candidate"
            if "category" not in result:
                if args.limit_stage2 and sorted_now >= args.limit_stage2:
                    continue
                text = result["vision_text"]
                if result["stage1"] == "text_bubble":
                    prompt = SORT_PROMPT.format(store=names.get(hall, hall), when=when, what="文字のメッセージ", ocr_note="",
                                                text=f"\nメッセージ:\n{text}")
                    answer = ask(FAST, prompt, None, 200)
                else:
                    prompt = SORT_PROMPT.format(store=names.get(hall, hall), when=when, what="画像",
                                                ocr_note="下の「OCR結果」は別の文字認識の結果で誤りを含みます。",
                                                text=f"\nOCR結果:\n{text or '（なし）'}")
                    answer = ask(FAST, prompt, image.resize((image.width * 2, image.height * 2), Image.LANCZOS), 200)
                category = answer.get("category") if answer.get("category") in CATEGORIES else "other"
                result.update(category=category, reason=answer.get("reason", ""), sorted_by=FAST)
                sorted_now += 1
            if result.get("category") in ("machine_hint", "recommend_period") and "machines" not in result and result["stage1"] != "text_bubble":
                to_read.append((cache, path, hall, when))  # step 3 runs after all sorting: switching models is slow
            cache.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
            seen.setdefault(hall, []).append((fp, cache))
            counts[result.get("stage1", "?") + "/" + result.get("category", "?")] = counts.get(result.get("stage1", "?") + "/" + result.get("category", "?"), 0) + 1
            rows.append({"hall_id": hall, "posted_date": post.get("posted_date"), "posted_time": post.get("posted_time"),
                         "image": rel, "post_id": post["post_id"], "stage1": result.get("stage1"), "category": result.get("category"),
                         "repeat_of": result.get("repeat_of"), "reason": result.get("reason"), "machines": result.get("machines"),
                         "period": result.get("period"), "colour": result.get("colour"), "rgb": result.get("rgb")})
    for cache, path, hall, when in to_read:
        result = json.loads(cache.read_text(encoding="utf-8"))
        image = Image.open(path).convert("RGB")
        answer = ask(ACCURATE, READ_PROMPT.format(store=names.get(hall, hall), when=when, ocr=result["vision_text"] or "（なし）"),
                     image.resize((image.width * 2, image.height * 2), Image.LANCZOS), 400)
        result.update(machines=[m for m in answer.get("machines") or [] if isinstance(m, str) and m],
                      period=answer.get("period", ""), note=answer.get("note", ""), read_by=ACCURATE)
        if result["category"] == "machine_hint":
            result["colour"], result["rgb"] = frame_colour(path)
        cache.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
        for row in rows:
            if Path(row["image"]).stem == path.stem:
                row.update(machines=result["machines"], period=result["period"], colour=result.get("colour"), rgb=result.get("rgb"))
    if args.since and (OUT / "triage.jsonl").exists():
        # keep the rows of earlier days that this run did not look at
        older = [json.loads(l) for l in (OUT / "triage.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
        rows = [r for r in older if (r.get("posted_date") or "") < args.since] + rows
    with (OUT / "triage.jsonl").open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(json.dumps({"images": len(rows), "sorted_now": sorted_now, "counts": counts}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
