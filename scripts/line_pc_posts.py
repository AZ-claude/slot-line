"""Cut LINE PC capture pages into individual posts and drop duplicates (no LLM).

Input  (synced from Windows by line_pc_sync.py):
  data/line_pc_raw/<date>/line_pc_run_<run>.json
  data/line_pc_raw/<date>/<hall_id>/line_pc/<run>_pNN.jpg|png   (+ _pNN.json OCR, _pNN_cK_MM.jpg carousel cards)
Output (never committed; screenshots of chats):
  data/line_pc_posts/<hall_id>/<post_id>.jpg        one image per post
  data/line_pc_posts/<hall_id>/<post_id>_card_MM.jpg further carousel cards
  data/line_pc_posts/posts.jsonl                     one JSON record per new post
  data/line_pc_posts/index.json                      per-store fingerprints used for de-duplication

How a run is cut:
  1. pages are stitched into one tall strip (each page is ~570 px above the
     previous one; the exact shift is found by matching the overlap)
  2. the strip is split at horizontal white gaps into blocks
  3. blocks that are only a time / read mark are attached to the block above;
     date separators ("今日", "9月30日(水)") set the date of the posts below them;
     green blocks are our own messages (the trigger) and are not posts
  4. a post already seen for the store (same image fingerprint) is skipped

    .venv/bin/python scripts/line_pc_posts.py [--date 2026-10-01 ...]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "line_pc_raw"
OUT = ROOT / "data" / "line_pc_posts"

CONTENT_WIDTH = 626          # the scrollbar and floating "↓" button live to the right
BLANK_LEVEL = 245            # used when trimming a post's own edges
INK_LEVEL = 225              # darker than this counts as drawn content
GAP_SPLIT = 12               # blank rows that separate two posts (consecutive images sit 17 px apart)
FINE_GAP = 5                 # blank rows that separate parts of a post (image, time stamp, pill)
DEFAULT_SHIFT = 570          # 5 wheel notches
OWN_BUBBLE_RGB = np.array((195, 246, 157))
MIN_POST_HEIGHT = 30        # shorter leftovers are separators or noise
EDGE_ROWS = 20               # a post starting this close to the top of the strip may be cut off
DUPLICATE_BITS = 6           # max Hamming distance between fingerprints of the same post

TIME_RE = re.compile(r"^(既読\d*)?[〒午前後]*\d{1,2}[:：]?\d{2}$")
READ_RE = re.compile(r"^既読\d*$")
DATE_RE = re.compile(r"^(今日|昨日|(\d{4}[./年])?\d{1,2}[./月]\d{1,2}日?(\(.\))?.*|\d{3,4}\(.\))$")
# OCR often garbles the small grey time stamps ("〒ま9:26", "午畯リ:26"); short lines ending in 2 digits count too
LOOSE_TIME_RE = re.compile(r"^.{0,4}\d{0,2}[:：ま]?\d{2}$")
HOVER_BAR = "名前を付けて保存"
TIME_PARSE = re.compile(r"(午前|午後)?(\d{1,2})[:：]?(\d{2})$")


def norm(text: str) -> str:
    return "".join(text.split())


# ---------------------------------------------------------------- stitching
def load_page(path: Path) -> np.ndarray:
    return np.asarray(Image.open(path).convert("RGB"))


def find_shift(lower: np.ndarray, upper: np.ndarray) -> tuple[int, float]:
    """How far `upper` (the older page) sits above `lower` (the newer page)."""
    lo = lower[:, :600].mean(axis=2).astype(np.int16)
    up = upper[:, :600].mean(axis=2).astype(np.int16)
    height = min(lo.shape[0], up.shape[0])
    best = (1e9, DEFAULT_SHIFT)
    for shift in range(20, height - 20):
        overlap = height - shift
        diff = float(np.abs(up[shift:height, ::4] - lo[:overlap, ::4]).mean())
        if diff < best[0]:
            best = (diff, shift)
    return best[1], best[0]


def stitch(pages: list[Path]) -> tuple[np.ndarray, list[int]]:
    """Return the tall strip (oldest at top) and each page's top offset in it."""
    images = [load_page(p) for p in pages]
    shifts = [find_shift(images[i], images[i + 1])[0] for i in range(len(images) - 1)]
    height, width = images[0].shape[:2]
    total = height + sum(shifts)
    strip = np.full((total, width, 3), 255, dtype=np.uint8)
    offsets = []
    y = total - height
    for index, image in enumerate(images):
        offsets.append(y)
        if index < len(shifts):
            y -= shifts[index]
    # each page owns the rows down to the middle of its overlap with the newer page below,
    # which keeps seams away from the floating button and from half-scrolled edges
    for index, (image, top) in enumerate(zip(images, offsets)):
        start = 0 if index == len(images) - 1 else (height - shifts[index]) // 2
        end = height if index == 0 else height - (height - shifts[index - 1]) // 2
        strip[top + start:top + end] = image[start:end]
    return strip, offsets


def page_ocr(page: Path, top: int) -> list[dict[str, Any]]:
    ocr_path = page.with_suffix(".json")
    if not ocr_path.exists():
        return []
    lines = []
    for line in json.loads(ocr_path.read_text(encoding="utf-8")):
        x0, y0, x1, y1 = line["box"]
        lines.append({"text": line["text"], "box": [x0, y0 + top, x1, y1 + top]})
    return lines


def merge_ocr(groups: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    for group in groups:
        for line in group:
            if any(line["text"] == m["text"] and abs(line["box"][1] - m["box"][1]) <= 6 for m in merged):
                continue
            merged.append(line)
    return sorted(merged, key=lambda l: (l["box"][1], l["box"][0]))


# ---------------------------------------------------------------- blocks
def ink(strip: np.ndarray) -> np.ndarray:
    """True where a pixel is clearly drawn (JPEG ringing around text stays above INK_LEVEL)."""
    return strip[:, :CONTENT_WIDTH].min(axis=2) < INK_LEVEL


def blank_rows(strip: np.ndarray) -> np.ndarray:
    """Rows of pure background. Bubble fills (~240) count as content; JPEG ringing is only a few pixels."""
    return (strip[:, :CONTENT_WIDTH].min(axis=2) < 250).sum(axis=1) <= 8


def split_blocks(strip: np.ndarray, gap: int = 18) -> list[tuple[int, int]]:
    blank = blank_rows(strip)
    blocks, start, gap_run = [], None, 0
    for y, is_blank in enumerate(list(blank) + [True] * (gap + 1)):
        if not is_blank:
            if start is None:
                start = y
            gap_run = 0
        elif start is not None:
            gap_run += 1
            if gap_run >= gap:
                blocks.append((start, y - gap_run))
                start, gap_run = None, 0
    return blocks


def is_own(strip: np.ndarray, y0: int, y1: int) -> bool:
    region = strip[y0:y1 + 1, 300:CONTENT_WIDTH].astype(int)
    green = (np.abs(region - OWN_BUBBLE_RGB).sum(axis=2) < 24).sum()
    return green > 0.2 * region.shape[0] * 40


def fingerprint(image: Image.Image) -> str:
    """64-bit difference hash of the post image."""
    small = np.asarray(image.convert("L").resize((9, 8), Image.BILINEAR)).astype(int)
    bits = (small[:, 1:] > small[:, :-1]).flatten()
    return "%016x" % int("".join("1" if b else "0" for b in bits), 2)


def hamming(a: str, b: str) -> int:
    return bin(int(a, 16) ^ int(b, 16)).count("1")


INCOMPLETE_CAROUSEL = {"stuck_before_last_card", "max_clicks"}
MIN_CAROUSEL_HEIGHT = 330  # carousel rows are ~338 px tall; shorter spans were cut by the page edge
CAROUSEL_STEP = 632  # the longest move of one ">" click (view width minus an 8 px overlap)


def carousel_step(previous: np.ndarray, current: np.ndarray) -> int | None:
    """How far the row moved between two bands: 0 for a repeated band, None when
    no overlap matches (the move was a full CAROUSEL_STEP, which shares no columns)."""
    best, step = None, None
    for dx in range(0, CONTENT_WIDTH - 20):
        overlap = CONTENT_WIDTH - dx
        diff = float(np.abs(previous[:, dx:dx + overlap] - current[:, :overlap]).mean())
        if best is None or diff < best:
            best, step = diff, dx
    return step if best is not None and best <= 12 else None


def carousel_panorama(bands: list[Image.Image]) -> Image.Image:
    """Join the band screenshots of one carousel side by side.

    A ">" click moves the row by a varying amount (632 px at most, less near the
    end), so every step is measured from the overlap. A band that did not move
    (only the hover arrows changed) is dropped.
    """
    arrays = [np.asarray(b.convert("RGB")) for b in bands]
    height = min(a.shape[0] for a in arrays)
    width = arrays[0].shape[1]
    grays = [a[:height, :CONTENT_WIDTH].mean(axis=2) for a in arrays]
    kept, offsets = [arrays[0]], [0]
    previous = grays[0]
    for array, gray in zip(arrays[1:], grays[1:]):
        step = carousel_step(previous, gray)
        if step == 0:
            continue
        offsets.append(offsets[-1] + (step if step is not None else CAROUSEL_STEP))
        kept.append(array)
        previous = gray
    panorama = np.full((height, offsets[-1] + width, 3), 255, dtype=np.uint8)
    for array, left in zip(kept, offsets):
        panorama[:, left:left + width] = array[:height]
    # later bands are painted over earlier ones; that is fine because shared columns match
    return Image.fromarray(panorama[:, :offsets[-1] + CONTENT_WIDTH])


def carousel_cards(bands: list[Image.Image]) -> list[Image.Image]:
    """Every card of a carousel once, left to right.

    Cards wholly visible on a single band are taken as they are; the panorama
    adds the cards that straddle two bands. A panorama card whose width does not
    match the single-band cards came from a bad join and is dropped.
    """
    direct = [card for band in bands for card in split_cards(band)]
    widths = sorted(card.width for card in direct)
    reference = widths[len(widths) // 2] if widths else None
    joined = [card for card in split_cards(carousel_panorama(bands), width=None)
              if reference is None or abs(card.width - reference) <= 12]
    cards, prints = [], []
    for card in joined + split_cards(bands[-1]):  # the last band holds the row's end as shown
        fp = fingerprint(card)
        if any(hamming(fp, old) <= DUPLICATE_BITS for old in prints):
            continue  # the same card is fully visible on two bands
        prints.append(fp)
        cards.append(card)
    return cards


def split_cards(band: Image.Image, width: int | None = CONTENT_WIDTH) -> list[Image.Image]:
    """Cut a carousel band screenshot into the cards that are wholly visible.

    Cards are separated by white columns; a card touching the left or right
    edge is cut off and is left for the band where it is fully shown. Brightness
    (not colour) decides white: JPEG smears saturated colours into the gaps, and a
    card can be mostly white (notices), so a gap is a column with almost no ink.
    """
    pixels = np.asarray(band.convert("RGB"))[:, :width]  # a screenshot band ends at the scrollbar
    right_edge = pixels.shape[1]
    content = ((np.asarray(band.convert("L"))[:, :width] < 245).sum(axis=0) > pixels.shape[0] * 0.03)
    cards, start = [], None
    for x, value in enumerate(list(content) + [False]):
        if value and start is None:
            start = x
        elif not value and start is not None:
            if x - start >= 200 and start > 2 and x < right_edge - 2:
                column = pixels[:, start:x]
                rows = np.where((column.min(axis=2) < 250).sum(axis=1) > (x - start) * 0.2)[0]
                if len(rows):
                    cards.append(Image.fromarray(pixels[rows[0]:rows[-1] + 1, start:x]))
            start = None
    return cards


def is_same_post(fp: str, when: str, seen_entry: str) -> bool:
    """Same image and same (or unknown) posting time. Daily template banners look alike
    from day to day, so an identical image on another day is a different post."""
    old_fp, _, old_when = seen_entry.partition("|")
    if hamming(fp, old_fp) > DUPLICATE_BITS:
        return False
    if not old_when:
        return True
    new_day, new_time = when.split(" ")
    old_day, old_time = old_when.split(" ")
    day_ok = "?" in (new_day, old_day) or new_day == old_day
    time_ok = "?" in (new_time, old_time) or new_time == old_time
    return day_ok and time_ok


def parse_date(text: str, capture: date) -> str | None:
    text = norm(text)
    if text.startswith("今日"):
        return capture.isoformat()
    if text.startswith("昨日"):
        return (capture - timedelta(days=1)).isoformat()
    m = re.match(r"(?:(\d{4})[./年])?(\d{1,2})[./月](\d{1,2})", text)
    squashed = re.match(r"^(\d{3,4})\(", text)  # "925(金)" = 9.25 with the dot lost
    if m:
        year = int(m.group(1)) if m.group(1) else capture.year
        month, day = int(m.group(2)), int(m.group(3))
    elif squashed:
        digits = squashed.group(1)
        year, month, day = capture.year, int(digits[:-2]), int(digits[-2:])
        if month > 12:
            return None
    else:
        return None
    if not (m and m.group(1)) and (month, day) > (capture.month, capture.day):
        year -= 1
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def parse_time(text: str) -> str | None:
    m = TIME_PARSE.search(norm(text))
    if not m:
        return None
    hour, minute = int(m.group(2)), int(m.group(3))
    if m.group(1) == "午後" and hour < 12:
        hour += 12
    if m.group(1) == "午前" and hour == 12:
        hour = 0
    if hour > 23 or minute > 59:
        return None
    return f"{hour:02d}:{minute:02d}"


# ---------------------------------------------------------------- one run
def cut_run(hall_id: str, run_id: str, capture_day: date, pages: list[Path], store_record: dict[str, Any]) -> list[dict[str, Any]]:
    strip, offsets = stitch(pages)
    ocr = merge_ocr([page_ocr(page, top) for page, top in zip(pages, offsets)])
    stop = (store_record.get("capture") or {}).get("stop")
    posts: list[dict[str, Any]] = []
    current_date: str | None = None

    def emit(a: int, b: int, time_text: str | None) -> None:
        rows = np.where(~blank_rows(strip[a:b + 1]))[0]
        if len(rows) == 0:
            return
        a, b = a + int(rows[0]), a + int(rows[-1])
        if b - a < MIN_POST_HEIGHT:
            return
        inside = [l for l in ocr if l["box"][1] >= a - 2 and l["box"][3] <= b + 2]
        texts = [l["text"] for l in inside if not TIME_RE.match(norm(l["text"])) and not READ_RE.match(norm(l["text"]))
                 and HOVER_BAR not in norm(l["text"])]
        if not texts and b - a < 60 and any(HOVER_BAR in norm(l["text"]) for l in inside):
            return  # the "保存 | 名前を付けて保存 | 転送" bar shown under a hovered image
        posts.append({"y0": a, "y1": b, "own": is_own(strip, a, b),
                      "partial": a <= EDGE_ROWS and stop != "top_of_history",
                      "posted_date": current_date, "posted_time": parse_time(time_text) if time_text else None,
                      "ocr_text": "\n".join(texts)})

    open_start: int | None = None
    open_end = 0
    open_time: str | None = None
    for a, b in split_blocks(strip, gap=FINE_GAP):
        dark_cols = np.where(ink(strip[a:b + 1]).sum(axis=0) > 0)[0]
        if len(dark_cols) == 0:  # only a faint fill (e.g. an empty bubble edge)
            dark_cols = np.where((strip[a:b + 1, :CONTENT_WIDTH].min(axis=2) < 250).any(axis=0))[0]
        x_min, x_max = (int(dark_cols.min()), int(dark_cols.max())) if len(dark_cols) else (0, CONTENT_WIDTH)
        height = b - a + 1
        inside = [l for l in ocr if l["box"][1] >= a - 3 and l["box"][3] <= b + 3]
        text = "".join(norm(l["text"]) for l in inside)
        if height <= 34 and x_min >= 180 and x_max <= 460:  # centred pill: date or "ここから未読"
            if open_start is not None:
                emit(open_start, open_end, open_time)
                open_start, open_time = None, None
            # overlapping pages OCR the same pill twice ("926(土)" and "9.26(土)"): read lines one by one
            for candidate in (norm(l["text"]) for l in inside):
                parsed = parse_date(candidate, capture_day) if DATE_RE.match(candidate) else None
                if parsed:
                    current_date = parsed
                    break
            continue
        if height <= 22 and x_min >= 380:  # right-aligned grey time stamp: ends the post above
            if open_start is not None:
                emit(open_start, b, text or None)
                open_start, open_time = None, None
            continue
        if HOVER_BAR in text and height <= 40:
            continue
        if open_start is not None and a - open_end >= GAP_SPLIT:
            emit(open_start, open_end, open_time)
            open_start, open_time = None, None
        if open_start is None:
            open_start = a
        open_end = b
        stamps = [l for l in inside if (TIME_RE.match(norm(l["text"])) or LOOSE_TIME_RE.match(norm(l["text"])))
                  and l["box"][3] - l["box"][1] < 22 and not READ_RE.match(norm(l["text"]))]
        if stamps:
            open_time = stamps[-1]["text"]
    if open_start is not None:
        emit(open_start, open_end, open_time)
    # carousel cards: manifest spans are in page coordinates
    for page_info in (store_record.get("capture") or {}).get("pages", []):
        index = page_info["page"]
        if index >= len(offsets):
            continue
        for carousel in page_info.get("carousels", []):
            if carousel.get("stop") in INCOMPLETE_CAROUSEL:
                continue  # the row could not be moved to its end; its bands may be misplaced
            y0, y1 = carousel["span"]
            y_mid = offsets[index] + (y0 + y1) // 2
            # the same row may be seen on overlapping pages: prefer a row captured whole
            # (not cut by the page edge), then the one with more bands
            score = (y1 - y0 >= MIN_CAROUSEL_HEIGHT, len(carousel["cards"]))
            for post in posts:
                if post["y0"] <= y_mid <= post["y1"] and score > post.get("cards_score", (False, 0)):
                    post["cards"], post["cards_score"] = list(carousel["cards"]), score
    return [dict(p, strip=strip) for p in posts]


def process(dates: list[str]) -> dict[str, Any]:
    OUT.mkdir(parents=True, exist_ok=True)
    index_path = OUT / "index.json"
    index: dict[str, list[str]] = json.loads(index_path.read_text(encoding="utf-8")) if index_path.exists() else {}
    done_runs = set(index.get("_runs", []))
    full_history: set[str] = set(index.get("_full_history", []))  # stores already read back to the first message
    summary = {"runs": 0, "new_posts": 0, "duplicates": 0, "own_messages": 0, "partial_skipped": 0, "superseded_runs": 0, "errors": []}
    with (OUT / "posts.jsonl").open("a", encoding="utf-8") as sink:
        for day in sorted(dates, reverse=True):
            # newest run first: later captures use the better tooling and win de-duplication
            used_today: set[str] = set()  # one capture per store and day: the newest one
            for manifest_path in sorted((RAW / day).glob("line_pc_run_*.json"), reverse=True):
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                run_id = manifest["run_id"]
                for store in manifest["stores"]:
                    key = f"{run_id}/{store['hall_id']}"
                    if store.get("status") != "captured" or key in done_runs:
                        continue
                    if store["hall_id"] in used_today:
                        done_runs.add(key)
                        summary["superseded_runs"] += 1
                        continue
                    used_today.add(store["hall_id"])
                    hall = store["hall_id"]
                    if hall in full_history and (store.get("capture") or {}).get("stop") != "reached_previous_checkpoint":
                        # a newer run already read this store's whole history with the current tooling;
                        # older full reads are superseded (only incremental runs add anything)
                        if run_id < index.get("_full_history_run", {}).get(hall, ""):
                            done_runs.add(key)
                            summary["superseded_runs"] += 1
                            continue
                    folder = RAW / day / hall / "line_pc"
                    pages = sorted(p for p in folder.glob(f"{run_id}_p[0-9][0-9].*") if p.suffix in {".jpg", ".png"})
                    if not pages:
                        continue
                    try:
                        posts = cut_run(hall, run_id, date.fromisoformat(day), pages, store)
                    except Exception as exc:  # one broken run must not stop the rest
                        summary["errors"].append({"run": key, "error": f"{type(exc).__name__}: {exc}"})
                        continue
                    seen = index.setdefault(hall, [])
                    target = OUT / hall
                    target.mkdir(parents=True, exist_ok=True)
                    for post in posts:
                        if post["own"]:
                            summary["own_messages"] += 1
                            continue
                        if post["partial"]:
                            summary["partial_skipped"] += 1
                            continue
                        crop = Image.fromarray(post["strip"][post["y0"]:post["y1"] + 1])
                        bands = [Image.open(folder / b) for b in post.get("cards", []) if (folder / b).exists()]
                        card_images = carousel_cards(bands) if bands else []
                        # a carousel row looks different depending on where LINE left it scrolled,
                        # so its first card identifies it
                        fp = fingerprint(card_images[0] if card_images else crop)
                        when = f"{post['posted_date'] or '?'} {post['posted_time'] or '?'}"
                        if any(is_same_post(fp, when, old) for old in seen):
                            summary["duplicates"] += 1
                            continue
                        seen.append(f"{fp}|{when}")
                        post_id = hashlib.sha1(f"{hall}:{fp}:{run_id}:{post['y0']}".encode()).hexdigest()[:16]
                        crop.save(target / f"{post_id}.jpg", quality=85)
                        cards = []
                        for card in card_images:
                            name = f"{post_id}_card_{len(cards) + 1:02d}.jpg"
                            card.convert("RGB").save(target / name, quality=85)
                            cards.append(name)
                        record = {"post_id": post_id, "hall_id": hall, "run_id": run_id, "capture_date": day,
                                  "posted_date": post["posted_date"], "posted_time": post["posted_time"],
                                  "image": f"{hall}/{post_id}.jpg", "cards": [f"{hall}/{c}" for c in cards],
                                  "height": post["y1"] - post["y0"] + 1, "ocr_text": post["ocr_text"],
                                  "fingerprint": fp, "source_pages": [p.name for p in pages]}
                        sink.write(json.dumps(record, ensure_ascii=False) + "\n")
                        summary["new_posts"] += 1
                    done_runs.add(key)
                    summary["runs"] += 1
                    if (store.get("capture") or {}).get("stop") == "top_of_history" and hall not in full_history:
                        full_history.add(hall)
                        index.setdefault("_full_history_run", {})[hall] = run_id
    index["_runs"] = sorted(done_runs)
    index["_full_history"] = sorted(full_history)
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--date", action="append", help="capture date folder(s); default: all synced dates")
    parser.add_argument("--rebuild", action="store_true", help="drop data/line_pc_posts/ and cut every synced run again")
    args = parser.parse_args()
    if args.rebuild and OUT.exists():
        shutil.rmtree(OUT)
    dates = args.date or sorted(p.name for p in RAW.iterdir() if p.is_dir() and re.match(r"\d{4}-\d{2}-\d{2}$", p.name))
    summary = process(dates)
    print(json.dumps(summary, ensure_ascii=False))
    return 1 if summary["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
