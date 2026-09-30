"""Daily LINE collection on the Windows LINE desktop app (runs ON Windows).

For each store in data/line_collection_plan.json:
  1. open its chat through LINE PC's chat search and verify the header by OCR
     (anything else - e.g. a personal chat - is left alone and nothing is saved)
  2. with --send only: type the trigger text ("最新情報") and press Enter for
     stores whose plan says text_trigger=daily (or verify_once in --verify mode),
     at most once per store per day
  3. screenshot the message area from the newest message upward until the
     previous run's last lines are reached (first run: up to --max-pages),
     OCR every page, and store PNG + OCR JSON as RAW

Nothing is read from LINE's local data files. Pages are screenshots, so
image posts are kept as pixels at screen resolution.

    python line_pc_collect.py --repo C:/Users/Public/slot-line [--only hall_a,hall_b] [--send] [--verify]
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import time
import unicodedata
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

try:
    from line_pc import LinePC, ocr_lines
except ImportError:
    from scripts.line_pc import LinePC, ocr_lines

JST = timezone(timedelta(hours=9))

# Layout of the LINE window after LinePC.prepare() (1100 x 980, window-relative pixels).
CHATS_TAB = (38, 135)
SEARCH_BOX = (245, 102)
FIRST_RESULT = (280, 200)
RESULTS_BOX = (90, 140, 445, 300)
HEADER_BOX = (460, 78, 1000, 124)
MESSAGES_BOX = (456, 126, 1096, 826)
MESSAGES_ANCHOR = (770, 470)
INPUT_BOX = (770, 872)
SCROLL_NOTCHES = 5
CAROUSEL_MAX_CLICKS = 9
CAROUSEL_CARD_HALF = 168  # carousel cards are ~337 px tall; the ">" sits at mid-height
CAROUSEL_ARROW_X = 597  # message-area x of the ">" button on a horizontal card carousel
CAROUSEL_BACK_X = 37  # message-area x of the "<" button
HEADER_MIN_SIMILARITY = 0.6


def norm(text: str) -> str:
    return "".join(unicodedata.normalize("NFKC", text).split()).lower()


# Windows OCR confuses these in store names (ＵＮＯ -> LJN0, I -> |).
OCR_CONFUSABLE = (("lj", "u"), ("ij", "u"), ("|", "l"), ("i", "l"), ("0", "o"), ("ブ", "プ"), ("ベ", "ペ"))


def ocr_fold(text: str) -> str:
    folded = norm(text)
    for src, dst in OCR_CONFUSABLE:
        folded = folded.replace(src, dst)
    return folded


def similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, ocr_fold(a), ocr_fold(b)).ratio()


NOISE_RE = __import__("re").compile(
    r"^(既読\d*|今日|昨日|[〒午前後]*\d{1,2}[:：]?\d{2}|\d{1,2}月\d{1,2}日.*|[0-9:]+|保存.*|.*転送)$")


def is_message_line(line: str) -> bool:
    """False for read receipts, times and date separators, which change without a reply."""
    return bool(line) and not NOISE_RE.match(norm(line))


def find_carousels(image_path: Path) -> list[tuple[int, int]]:
    """Vertical spans (message-area y) of card rows that run past the right edge.

    Ordinary bubbles end before x=625; a horizontal carousel's next card is cut
    off by the edge, so columns 626-629 stay non-white for the card height.
    Columns further right are skipped because the scrollbar lives there.
    """
    import numpy as np
    from PIL import Image

    pixels = np.asarray(Image.open(image_path).convert("L")).astype(int)
    # A card cut off at the right edge (more cards to the right) or at the left
    # edge (LINE remembered a scrolled position) marks a carousel row.
    edge = np.maximum((pixels[:, 626:632] < 235).mean(axis=1), (pixels[:, 0:6] < 235).mean(axis=1))
    window = 41  # smooth over bright details inside card images
    smooth = np.convolve(edge, np.ones(window) / window, mode="same")
    rows = smooth > 0.5
    spans, start = [], None
    for y, value in enumerate(list(rows) + [False]):
        if value and start is None:
            start = y
        elif not value and start is not None:
            if y - start >= 150:
                spans.append((start, y - 1))
            start = None
    return spans


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Collector:
    def __init__(self, repo: Path, run_id: str, send: bool, verify: bool, max_pages: int, log: list[dict]):
        self.repo = repo
        self.pc = LinePC()
        self.run_id = run_id
        self.send = send
        self.verify = verify
        self.max_pages = max_pages
        self.log = log
        self.today = datetime.now(JST).strftime("%Y-%m-%d")
        self.tmp = repo / "data" / "tmp_line_pc"
        self.tmp.mkdir(parents=True, exist_ok=True)

    def open_chat(self, name: str) -> dict[str, Any]:
        pc = self.pc
        pc.click(*CHATS_TAB)
        time.sleep(0.8)
        pc.click(*SEARCH_BOX)
        pc.key("ctrl+a")
        pc.paste(name)
        time.sleep(2.0)
        best = 0.0
        for _ in range(3):  # the result list can take a moment to appear
            results = pc.shot(self.tmp / "results.png", RESULTS_BOX)
            best = max((similarity(line["text"], name) for line in ocr_lines(results)), default=0.0)
            if best >= HEADER_MIN_SIMILARITY:
                break
            time.sleep(1.5)
        if best < HEADER_MIN_SIMILARITY:
            return {"ok": False, "reason": "no_matching_search_result", "best_result_similarity": round(best, 2)}
        pc.click(*FIRST_RESULT)
        time.sleep(2.5)
        header = pc.shot(self.tmp / "header.png", HEADER_BOX)
        header_text = "".join(line["text"] for line in ocr_lines(header))
        score = similarity(header_text, name)
        if score < HEADER_MIN_SIMILARITY:
            return {"ok": False, "reason": "chat_header_mismatch", "header_similarity": round(score, 2)}
        return {"ok": True, "header_ocr": header_text, "header_similarity": round(score, 2)}

    def to_bottom(self) -> None:
        """LINE PC reopens a chat at the last read position; wheel down to the newest message."""
        self.pc.scroll(*MESSAGES_ANCHOR, -80)
        time.sleep(1.0)

    def bottom_lines(self) -> list[str]:
        self.to_bottom()
        page = self.pc.shot(self.tmp / "bottom.png", MESSAGES_BOX)
        return [line["text"] for line in ocr_lines(page)]

    def send_trigger(self, text: str) -> str:
        pc = self.pc
        pc.click(*INPUT_BOX)
        pc.key("ctrl+a")
        pc.paste(text)
        time.sleep(0.3)
        pc.key("enter")
        return datetime.now(timezone.utc).isoformat()

    def capture_pages(self, store_dir: Path, checkpoint: list[str]) -> dict[str, Any]:
        pc = self.pc
        store_dir.mkdir(parents=True, exist_ok=True)
        self.to_bottom()
        pages = []
        previous_hash = None
        stop = "max_pages"
        wanted = {line for line in checkpoint if len(line) >= 4}
        for index in range(self.max_pages):
            png = pc.shot(store_dir / f"{self.run_id}_p{index:02d}.jpg", MESSAGES_BOX)
            digest = file_hash(png)
            if digest == previous_hash:
                png.unlink()
                stop = "top_of_history"
                break
            previous_hash = digest
            lines = ocr_lines(png)
            carousel = self.capture_carousels(png, store_dir, f"{self.run_id}_p{index:02d}")
            (store_dir / f"{self.run_id}_p{index:02d}.json").write_text(
                json.dumps(lines, ensure_ascii=False, indent=1), encoding="utf-8")
            pages.append({"page": index, "png": png.name, "sha256": digest, "lines": len(lines), "carousels": carousel})
            texts = {line["text"] for line in lines}
            if wanted and len(wanted & texts) >= min(2, len(wanted)):
                stop = "reached_previous_checkpoint"
                break
            pc.scroll(*MESSAGES_ANCHOR, SCROLL_NOTCHES)
            time.sleep(1.2)
        return {"pages": pages, "stop": stop}

    def capture_carousels(self, page: Path, store_dir: Path, stem: str) -> list[dict[str, Any]]:
        """Click each carousel's ">" and save every further card; never clicks elsewhere."""
        import win32gui

        pc = self.pc
        results = []
        for number, (y0, y1) in enumerate(find_carousels(page)):
            if y1 - 2 * CAROUSEL_CARD_HALF < 5 or y1 > MESSAGES_BOX[3] - MESSAGES_BOX[1] - 25:
                continue  # partly off-screen; it will be complete on the next page
            y_center = MESSAGES_BOX[1] + y1 - CAROUSEL_CARD_HALF  # the bottom edge is detected reliably
            y0 = max(0, y1 - 2 * CAROUSEL_CARD_HALF)
            band = (MESSAGES_BOX[0], MESSAGES_BOX[1] + max(0, y0 - 10), MESSAGES_BOX[2], MESSAGES_BOX[1] + min(y1 + 10, MESSAGES_BOX[3] - MESSAGES_BOX[1]))
            from PIL import Image

            def left_cut(path: Path) -> bool:
                with Image.open(path) as image:
                    strip = image.convert("L").crop((0, 20, 6, image.height - 20))
                    return sum(strip.tobytes()) / max(1, strip.width * strip.height) < 235

            # Rewind to the first card: LINE keeps a carousel's last horizontal position.
            first = pc.shot(store_dir / f"{stem}_c{number}_00.jpg", band)
            rewinds = 0
            while left_cut(first) and rewinds < CAROUSEL_MAX_CLICKS:
                pc.click(MESSAGES_BOX[0] + CAROUSEL_BACK_X, y_center)
                time.sleep(1.0)
                if win32gui.GetForegroundWindow() != pc.hwnd:
                    pc.key("esc")
                    time.sleep(0.8)
                    pc.prepare()
                    break
                first = pc.shot(store_dir / f"{stem}_c{number}_00.jpg", band)
                rewinds += 1
            previous = file_hash(first)
            shots = [first.name]
            stop = "max_clicks"
            for click in range(1, CAROUSEL_MAX_CLICKS + 1):
                pc.click(MESSAGES_BOX[0] + CAROUSEL_ARROW_X, y_center)
                time.sleep(1.2)
                if win32gui.GetForegroundWindow() != pc.hwnd:
                    pc.key("esc")  # an image viewer or browser opened: close it and stop
                    time.sleep(0.8)
                    pc.prepare()
                    stop = "left_the_chat_window"
                    break
                shot = pc.shot(store_dir / f"{stem}_c{number}_{click:02d}.jpg", band)
                digest = file_hash(shot)
                if digest == previous:
                    shot.unlink()
                    stop = "no_more_cards"
                    break
                previous = digest
                texts = [line["text"] for line in ocr_lines(shot)]
                shots.append(shot.name)
                if any("もっと見る" in text for text in texts):
                    stop = "more_link_reached"
                    break
            results.append({"span": [y0, y1], "rewinds": rewinds, "cards": shots, "stop": stop})
        return results

    def run_store(self, store: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
        hall = store["hall_id"]
        record: dict[str, Any] = {"hall_id": hall, "search_name": store["search_name"],
                                  "text_trigger": store["text_trigger"]}
        opened = self.open_chat(store["search_name"])
        record["open"] = opened
        if not opened["ok"]:
            record["status"] = "skipped"
            return record
        hall_state = state.setdefault(hall, {})
        before = self.bottom_lines()
        verify_now = self.verify and store["text_trigger"] == "verify_once" and not hall_state.get("verify_sent_at")
        want_send = store["text_trigger"] == "daily" or verify_now
        if want_send and self.send:
            if hall_state.get("last_trigger_date") == self.today:
                record["trigger"] = {"status": "skipped_already_sent_today"}
            else:
                sent_at = self.send_trigger(store["trigger_text"])
                hall_state["last_trigger_date"] = self.today
                if verify_now:
                    hall_state["verify_sent_at"] = sent_at  # a verify_once store is only ever sent to once
                time.sleep(30)
                after = self.bottom_lines()
                new_lines = [line for line in after if line not in before and is_message_line(line)
                             and norm(line) != norm(store["trigger_text"])]
                record["trigger"] = {"status": "sent", "sent_at": sent_at, "text": store["trigger_text"],
                                     "new_lines_after_send": new_lines[:20],
                                     "reply_observed": bool(new_lines)}
        elif want_send:
            record["trigger"] = {"status": "not_sent_without_--send"}
        store_dir = self.repo / "data" / "raw" / self.today / hall / "line_pc"
        capture = self.capture_pages(store_dir, hall_state.get("checkpoint_lines", []))
        record["capture"] = capture
        record["raw_dir"] = str(store_dir.relative_to(self.repo))
        first = store_dir / f"{self.run_id}_p00.json"
        if first.exists():
            lines = [line["text"] for line in json.loads(first.read_text(encoding="utf-8"))]
            hall_state["checkpoint_lines"] = lines[-6:]
            hall_state["last_capture_run"] = self.run_id
        record["status"] = "captured"
        return record


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--plan", type=Path, default=None)
    parser.add_argument("--state", type=Path, default=None)
    parser.add_argument("--only", default="", help="comma-separated hall_ids")
    parser.add_argument("--send", action="store_true", help="actually send trigger texts (default: never send)")
    parser.add_argument("--verify", action="store_true", help="also send once to text_trigger=verify_once stores")
    parser.add_argument("--max-pages", type=int, default=30)
    args = parser.parse_args()
    repo = args.repo
    plan_path = args.plan or repo / "data" / "line_collection_plan.json"
    state_path = args.state or repo / "data" / "line_pc_state.json"
    stores = json.loads(plan_path.read_text(encoding="utf-8"))["stores"]
    if args.only:
        wanted = {h.strip() for h in args.only.split(",") if h.strip()}
        stores = [s for s in stores if s["hall_id"] in wanted]
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
    run_id = datetime.now(JST).strftime("%Y%m%dT%H%M%S")
    log: list[dict] = []
    collector = Collector(repo, run_id, args.send, args.verify, args.max_pages, log)
    prepared = collector.pc.prepare()
    manifest = {"run_id": run_id, "started_at": datetime.now(timezone.utc).isoformat(), "send": args.send,
                "verify": args.verify, "window": prepared, "stores": []}
    manifest_path = repo / "data" / "raw" / collector.today / f"line_pc_run_{run_id}.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    for store in stores:
        try:
            record = collector.run_store(store, state)
        except Exception as exc:  # one store must not stop the others
            record = {"hall_id": store["hall_id"], "status": "error", "error": f"{type(exc).__name__}: {exc}"}
            try:
                collector.pc.key("esc")
            except Exception:
                pass
        manifest["stores"].append(record)
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
        state_path.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    manifest["finished_at"] = datetime.now(timezone.utc).isoformat()
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    counts: dict[str, int] = {}
    for record in manifest["stores"]:
        counts[record["status"]] = counts.get(record["status"], 0) + 1
    print(json.dumps({"manifest": str(manifest_path), "status": counts}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
