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
from datetime import date, datetime, timezone, timedelta
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
SCROLL_NOTCHES = 3  # ~342 px: every ~340 px carousel row is wholly visible on some page
CAROUSEL_MAX_CLICKS = 9
CAROUSEL_CLICK_ATTEMPTS = 3  # a ">" click that did not move the row is retried before giving up
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
    # voiced marks (ぷ/ぶ) and long-vowel dashes (ー/-) are the commonest misreads
    folded = "".join(c for c in unicodedata.normalize("NFD", folded) if c not in "\u3099\u309a")
    return "".join("ー" if c in "-−‐―ｰ一" else c for c in unicodedata.normalize("NFC", folded))


def similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, ocr_fold(a), ocr_fold(b)).ratio()


def name_score(seen: str, name: str) -> float:
    """Similarity of an OCR'd chat name to a store name. A longer name that merely
    contains it (くいーぷ東戸塚店 for くいーぷ) is another store of the chain."""
    a, b = ocr_fold(seen), ocr_fold(name)
    if b and b in a and len(a) - len(b) >= 2:
        return 0.0
    return similarity(seen, name)


NOISE_RE = __import__("re").compile(
    r"^(既読\d*|今日|昨日|[〒午前後]*\d{1,2}[:：]?\d{2}|\d{1,2}月\d{1,2}日.*|[0-9:]+|保存.*|.*転送)$")


def is_message_line(line: str) -> bool:
    """False for read receipts, times and date separators, which change without a reply."""
    return bool(line) and not NOISE_RE.match(norm(line))


DIVIDER_RE = __import__("re").compile(r"^(?:(\d{4})[./年])?(\d{1,2})[./月](\d{1,2})日?(?:\(.\))?$|^(\d)(\d{2})\(.\)$|^(1[0-2])(\d{2})\(.\)$")


def divider_date(line: dict[str, Any], today: date, page=None) -> date | None:
    """The date of a centred date divider ("今日", "昨日", "9.30(水)", "2025.12.31(水)").

    With the page image (grayscale), the divider must sit on the white chat
    background, so a date printed inside a picture is not taken for one."""
    x0, y0, x1, y1 = line["box"]
    if abs((x0 + x1) / 2 - 320) > 70 or y1 - y0 > 30:
        return None
    if page is not None:
        y = (y0 + y1) // 2
        sides = [page.crop((max(0, x0 - 60), y - 3, max(1, x0 - 25), y + 3)),
                 page.crop((min(page.width - 1, x1 + 25), y - 3, min(page.width, x1 + 60), y + 3))]
        if any(side.getextrema()[0] < 235 for side in sides):
            return None
    text = norm(line["text"])
    if text == "今日":
        return today
    if text == "昨日":
        return today - timedelta(days=1)
    m = DIVIDER_RE.match(text)
    if not m:
        return None
    year, month, day = (m.group(1), m.group(2), m.group(3)) if m.group(2) else \
        (None, m.group(4), m.group(5)) if m.group(4) else (None, m.group(6), m.group(7))
    try:
        found = date(int(year) if year else today.year, int(month), int(day))
    except ValueError:
        return None
    if found > today:
        if year or not (today.month == 1 and found.month == 12):
            return None  # a future date is not a divider (only December seen in January is last year)
        found = found.replace(year=today.year - 1)
    return found


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
    # Ordinary posts never reach these columns, so any non-white pixel there counts;
    # a cut card can be mostly white at its edge (maps, notices).
    edge = np.maximum((pixels[:, 626:632] < 245).any(axis=1), (pixels[:, 0:6] < 245).any(axis=1)).astype(float)
    window = 41  # smooth over bright details inside card images
    smooth = np.convolve(edge, np.ones(window) / window, mode="same")
    rows = smooth > 0.5
    spans, start = [], None
    for y, value in enumerate(list(rows) + [False]):
        if value and start is None:
            start = y
        elif not value and start is not None:
            if y - start >= 150:
                spans.append(card_extent(pixels, edge, start, y - 1))
            start = None
    return spans


def card_extent(pixels, edge, y0: int, y1: int) -> tuple[int, int]:
    """Grow an edge-detected span to the card row's real top and bottom.

    The edge columns can be bright in parts of a card, so the smoothed span may
    sit off the card. The row is bounded by white rows above (the store icon has
    a gap before the cards) and below (only the time stamp, right of x=520).
    """
    import numpy as np

    content = ((pixels[:, 0:520] < 245).mean(axis=1) > 0.01) | (edge > 0)
    middle = (y0 + y1) // 2
    top = bottom = middle
    gap = 0
    while top > 0 and gap <= 6:
        top -= 1
        gap = 0 if content[top] else gap + 1
    top += gap
    gap = 0
    while bottom < len(content) - 1 and gap <= 6:
        bottom += 1
        gap = 0 if content[bottom] else gap + 1
    bottom -= gap
    height = 2 * CAROUSEL_CARD_HALF + 2
    if bottom - top > height + 6:
        # The store icon above or a stamp below joined in: keep the card-height
        # window with the most edge rows (only cut cards reach the edges).
        hits = np.concatenate(([0], np.cumsum(edge[top:bottom + 1] > 0)))
        best = max(range(bottom - top - height + 2), key=lambda k: hits[k + height] - hits[k])
        top, bottom = top + best, top + best + height - 1
    return (top, bottom)


OWN_BUBBLE_RGB = (195, 246, 157)  # LINE PC's green for messages we sent


def detect_store_reply(image_path: Path) -> dict[str, Any]:
    """Decide from a bottom-of-chat screenshot whether the store posted after our message.

    Our own bubble is green on the right. Store posts (images, avatar, bubbles)
    start at the left edge, so non-white content in columns 12-100 below the
    lowest green bubble means a reply. If no green bubble is visible, replies
    have pushed it off the top of the view.
    """
    import numpy as np
    from PIL import Image

    pixels = np.asarray(Image.open(image_path).convert("RGB")).astype(int)
    green = (np.abs(pixels - np.array(OWN_BUBBLE_RGB)).sum(axis=2) < 24)[:, 300:]
    own_rows = np.where(green.sum(axis=1) >= 20)[0]
    if len(own_rows) == 0:
        return {"reply": True, "reason": "own_message_scrolled_out_by_newer_posts"}
    own_bottom = int(own_rows.max())
    below = pixels[own_bottom + 5:, 12:100]
    content_rows = int(((below.min(axis=2) < 225).sum(axis=1) >= 3).sum())
    return {"reply": content_rows >= 25, "reason": "store_content_below_own_message" if content_rows >= 25
            else "nothing_below_own_message", "own_bubble_bottom": own_bottom, "content_rows_below": content_rows}


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
        self.today_date = date.fromisoformat(self.today)
        self.verify_results: dict[str, dict] = {}
        aliases_path = repo / "data" / "line_ocr_aliases.json"
        self.aliases: dict[str, list[str]] = (json.loads(aliases_path.read_text(encoding="utf-8"))["stores"]
                                              if aliases_path.exists() else {})
        self.tmp = repo / "data" / "tmp_line_pc"
        self.tmp.mkdir(parents=True, exist_ok=True)

    def names_for(self, hall: str, name: str) -> list[str]:
        return [name, *self.aliases.get(hall, [])]

    def open_chat(self, name: str, hall: str = "") -> dict[str, Any]:
        names = self.names_for(hall, name)
        pc = self.pc
        pc.click(*CHATS_TAB)
        time.sleep(0.8)
        pc.click(*SEARCH_BOX)
        pc.key("ctrl+a")
        pc.paste(name)
        time.sleep(2.0)
        best, best_y = 0.0, None
        result_lines: list[str] = []
        for _ in range(3):  # the result list can take a moment to appear
            results = pc.shot(self.tmp / "results.png", RESULTS_BOX)
            # read twice (enlarged on the darkest channel, and as shown): each misses some names
            lines = ocr_lines(results, scale=2) + ocr_lines(results)
            result_lines = [line["text"] for line in lines]
            for line in lines:
                score = max(name_score(line["text"], n) for n in names)
                if score > best:
                    best, best_y = score, (line["box"][1] + line["box"][3]) // 2
            if best >= HEADER_MIN_SIMILARITY:
                break
            time.sleep(1.5)
        empty = False
        if best < HEADER_MIN_SIMILARITY:  # the "no results" note sits lower in the list pane
            panel = pc.shot(self.tmp / "results_panel.png", (RESULTS_BOX[0], RESULTS_BOX[1], RESULTS_BOX[2], 760))
            empty = any("検索結果がありません" in line["text"] for line in ocr_lines(panel))
        if empty:
            # LINE PC lists only chats that hold a message; a store that never sent one is not there
            return {"ok": False, "reason": "no_chat_yet", "result_ocr": result_lines[:8]}
        if best < HEADER_MIN_SIMILARITY:
            # OCR text only (no image) so a skipped store can be fixed with data/line_ocr_aliases.json
            return {"ok": False, "reason": "no_matching_search_result", "best_result_similarity": round(best, 2),
                    "result_ocr": result_lines[:8]}
        # click the matching row itself: the list can hold section titles, other chats with a
        # similar name and message hits above it
        pc.click(FIRST_RESULT[0], RESULTS_BOX[1] + best_y)
        time.sleep(2.5)
        score, header_text = 0.0, ""
        for attempt in range(3):  # a short name is sometimes not read at all on the first try
            header = pc.shot(self.tmp / "header.png", HEADER_BOX)
            for scale in (2, 1, 4):  # a short name ("グリーン") is sometimes read only when much larger
                text = "".join(line["text"] for line in ocr_lines(header, scale=scale))
                text_score = max(name_score(text, n) for n in names)
                if text_score >= score:
                    score, header_text = text_score, text
                if score >= HEADER_MIN_SIMILARITY:
                    break
            if score >= HEADER_MIN_SIMILARITY:
                break
            time.sleep(1.5)
        if score < HEADER_MIN_SIMILARITY:
            return {"ok": False, "reason": "chat_header_mismatch", "header_similarity": round(score, 2),
                    "header_ocr": header_text[:60], "result_ocr": result_lines[:8]}
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

    def capture_pages(self, store_dir: Path, checkpoint: list[str], since: date | None = None) -> dict[str, Any]:
        """Screenshot from the newest message upwards.

        Stops at the top of the history, at the previous run's bottom lines
        (checkpoint), or - for stores that post only images and so have no
        text checkpoint - at a date divider older than the previous capture
        day (`since`): everything after that divider was captured before."""
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
            if since:
                from PIL import Image
                with Image.open(png) as page_image:
                    gray = page_image.convert("L")
                    dividers = [d for d in (divider_date(line, self.today_date, gray) for line in lines) if d]
                if dividers and min(dividers) < since:
                    pages[-1]["divider_dates"] = sorted(str(d) for d in dividers)
                    stop = "reached_day_before_previous_capture"
                    break
            pc.scroll(*MESSAGES_ANCHOR, SCROLL_NOTCHES)
            self.wait_until_still()
        return {"pages": pages, "stop": stop}

    def wait_until_still(self, timeout: float = 4.0) -> None:
        """Wait for the smooth-scroll animation to finish (two identical frames)."""
        time.sleep(0.5)
        previous = None
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            digest = file_hash(self.pc.shot(self.tmp / "still.png", MESSAGES_BOX))
            if digest == previous:
                return
            previous = digest
            time.sleep(0.35)

    def capture_carousels(self, page: Path, store_dir: Path, stem: str) -> list[dict[str, Any]]:
        """Click each carousel's ">" and save every further card; never clicks elsewhere."""
        import win32gui

        pc = self.pc
        results = []
        for number, (y0, y1) in enumerate(find_carousels(page)):
            if y0 < 4 or y1 > MESSAGES_BOX[3] - MESSAGES_BOX[1] - 10 or y1 - y0 < 2 * CAROUSEL_CARD_HALF - 6:
                continue  # partly off-screen; it will be complete on the next page
            y_center = MESSAGES_BOX[1] + (y0 + y1) // 2  # the arrows sit at the card's mid-height
            band = (MESSAGES_BOX[0], MESSAGES_BOX[1] + max(0, y0 - 10), MESSAGES_BOX[2], MESSAGES_BOX[1] + min(y1 + 10, MESSAGES_BOX[3] - MESSAGES_BOX[1]))
            from PIL import Image

            def edge_cut(path: Path, x0: int, x1: int) -> bool:
                with Image.open(path) as image:
                    strip = image.convert("L").crop((x0, 20, x1, image.height - 20))
                    return sum(strip.tobytes()) / max(1, strip.width * strip.height) < 235

            def left_cut(path: Path) -> bool:
                return edge_cut(path, 0, 6)

            def right_cut(path: Path) -> bool:  # a card still runs past the right edge
                return edge_cut(path, 626, 632)

            def press(x: int) -> None:
                # The arrows only react after a real mouse move onto them (hover state),
                # so come in from the side instead of clicking where the cursor already is.
                pc.move(MESSAGES_BOX[0] + x - 60, y_center - 60)
                pc.move(MESSAGES_BOX[0] + x, y_center)
                pc.click(MESSAGES_BOX[0] + x, y_center)

            # Rewind to the first card: LINE keeps a carousel's last horizontal position.
            first = pc.shot(store_dir / f"{stem}_c{number}_00.jpg", band)
            rewinds = 0
            while left_cut(first) and rewinds < CAROUSEL_MAX_CLICKS:
                press(CAROUSEL_BACK_X)
                time.sleep(1.0)
                if win32gui.GetForegroundWindow() != pc.hwnd:
                    pc.key("esc")
                    time.sleep(0.8)
                    pc.prepare()
                    break
                before = file_hash(first)
                first = pc.shot(store_dir / f"{stem}_c{number}_00.jpg", band)
                rewinds += 1
                if file_hash(first) == before:
                    break  # "<" did nothing: already at the first card
            previous = file_hash(first)
            shots = [first.name]
            stop = "max_clicks"
            retries = 0
            for click in range(1, CAROUSEL_MAX_CLICKS + 1):
                left_window = False
                for attempt in range(CAROUSEL_CLICK_ATTEMPTS):
                    press(CAROUSEL_ARROW_X)
                    time.sleep(1.2 + attempt * 0.8)
                    if win32gui.GetForegroundWindow() != pc.hwnd:
                        if not pc.close_dialogs():
                            pc.key("esc")  # an image viewer or browser opened: close it and stop
                            time.sleep(0.8)
                        pc.prepare()
                        left_window = True
                        break
                    shot = pc.shot(store_dir / f"{stem}_c{number}_{click:02d}.jpg", band)
                    digest = file_hash(shot)
                    if digest != previous:
                        break
                    shot.unlink()
                    if not right_cut(store_dir / shots[-1]):
                        break  # the last card is wholly shown: this is the real end
                    retries += 1
                if left_window:
                    stop = "left_the_chat_window"
                    break
                if digest == previous:
                    stop = "stuck_before_last_card" if right_cut(store_dir / shots[-1]) else "no_more_cards"
                    break
                previous = digest
                texts = [line["text"] for line in ocr_lines(shot)]
                shots.append(shot.name)
                if any("もっと見る" in text for text in texts):
                    stop = "more_link_reached"
                    break
            results.append({"span": [y0, y1], "rewinds": rewinds, "cards": shots, "stop": stop, "click_retries": retries})
        return results

    def run_store(self, store: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
        hall = store["hall_id"]
        record: dict[str, Any] = {"hall_id": hall, "search_name": store["search_name"],
                                  "text_trigger": store["text_trigger"]}
        record["dialogs_closed"] = self.pc.close_dialogs()
        self.pc.prepare()  # re-assert position, foreground and top-most for every store
        opened = self.open_chat(store["search_name"], hall)
        record["open"] = opened
        if not opened["ok"]:
            record["status"] = "no_messages_yet" if opened["reason"] == "no_chat_yet" else "skipped"
            return record
        hall_state = state.setdefault(hall, {})
        before = self.bottom_lines()
        before_hash = file_hash(self.tmp / "bottom.png")
        mode = store["text_trigger"]
        if mode == "verify_once" and hall_state.get("verify_result") == "reply":
            mode = "daily"  # verified by an earlier run on this machine
        elif mode == "verify_once" and hall_state.get("verify_result") == "no_reply":
            mode = "off"
        record["text_trigger_effective"] = mode
        verify_now = self.verify and mode == "verify_once" and not hall_state.get("verify_sent_at")
        want_send = mode == "daily" or verify_now
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
                reply = detect_store_reply(self.tmp / "bottom.png")
                if file_hash(self.tmp / "bottom.png") == before_hash:
                    reply = {"reply": False, "reason": "screen_unchanged_send_not_confirmed"}
                record["trigger"] = {"status": "sent", "sent_at": sent_at, "text": store["trigger_text"],
                                     "new_lines_after_send": new_lines[:20],
                                     "reply_observed": reply["reply"], "reply_check": reply}
                if verify_now:
                    hall_state["verify_result"] = "reply" if reply["reply"] else "no_reply"
                    self.verify_results[hall] = {"result": hall_state["verify_result"], "sent_at": sent_at,
                                                 "reply_check": reply, "checked_by": "line_pc_collect"}
        elif want_send:
            record["trigger"] = {"status": "not_sent_without_--send"}
        store_dir = self.raw_root / self.today / hall / "line_pc"
        last = hall_state.get("last_capture_date") or (hall_state.get("last_capture_run") or "")[:8]
        since = date.fromisoformat(f"{last[:4]}-{last[4:6]}-{last[6:8]}" if len(last) == 8 else last) if last else None
        capture = self.capture_pages(store_dir, hall_state.get("checkpoint_lines", []), since)
        record["capture"] = capture
        record["raw_dir"] = str(store_dir.relative_to(self.raw_root))
        first = store_dir / f"{self.run_id}_p00.json"
        if first.exists():
            lines = [line["text"] for line in json.loads(first.read_text(encoding="utf-8"))]
            hall_state["checkpoint_lines"] = lines[-6:]
            hall_state["last_capture_run"] = self.run_id
            hall_state["last_capture_date"] = self.today_date.isoformat()
        record["status"] = "captured"
        return record


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--raw-root", type=Path, default=None,
                        help="where screenshots and manifests go (default <repo>/data/raw; the daily task uses D:\\slot-line\\raw)")
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
    collector.raw_root = args.raw_root or repo / "data" / "raw"
    LinePC.hide_own_console()
    time.sleep(1.5)  # a console opened by the task launcher may still be appearing
    prepared = collector.pc.prepare()
    manifest = {"run_id": run_id, "started_at": datetime.now(timezone.utc).isoformat(), "send": args.send,
                "verify": args.verify, "window": prepared, "stores": []}
    manifest_path = collector.raw_root / collector.today / f"line_pc_run_{run_id}.json"
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
    collector.pc.release()
    manifest["finished_at"] = datetime.now(timezone.utc).isoformat()
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    counts: dict[str, int] = {}
    for record in manifest["stores"]:
        counts[record["status"]] = counts.get(record["status"], 0) + 1
    failed = [{"hall_id": r["hall_id"], "status": r["status"],
               "reason": r.get("error") or (r.get("open") or {}).get("reason")}
              for r in manifest["stores"] if r["status"] not in ("captured", "no_messages_yet")]
    incomplete = [{"hall_id": r["hall_id"], "page": page["page"], "carousel": c["cards"][0], "stop": c["stop"]}
                  for r in manifest["stores"] for page in (r.get("capture") or {}).get("pages", [])
                  for c in page.get("carousels", []) if c["stop"] in ("stuck_before_last_card", "max_clicks")]
    manifest["summary"] = {"status": counts, "failed": failed, "incomplete_carousels": incomplete}
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    if collector.verify_results:
        results_path = repo / "data" / "line_text_trigger_results.json"
        results = json.loads(results_path.read_text(encoding="utf-8")) if results_path.exists() else {"schema_version": 1, "stores": {}}
        results["stores"].update(collector.verify_results)
        results_path.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    write_alert(repo, manifest_path, len(stores), failed)
    print(json.dumps({"manifest": str(manifest_path), "status": counts, "failed": len(failed),
                      "incomplete_carousels": len(incomplete)}, ensure_ascii=False))
    return 0


ALERT_MIN_FAILED = 3


def write_alert(repo: Path, manifest_path: Path, total: int, failed: list[dict]) -> None:
    """Append failures to data/line_pc_alerts.log and pop a Windows toast when many stores failed."""
    import subprocess

    stamp = datetime.now(JST).strftime("%Y-%m-%d %H:%M")
    line = f"{stamp} failed {len(failed)}/{total} manifest={manifest_path.name}"
    if failed:
        line += " " + ", ".join(f"{f['hall_id']}({f['reason']})" for f in failed)
    with (repo / "data" / "line_pc_alerts.log").open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")
    if len(failed) < ALERT_MIN_FAILED:
        return
    title = "slot-line LINE取得"
    body = f"{len(failed)}/{total} 店舗が取得できませんでした。data\\line_pc_alerts.log を確認してください。"
    script = (
        "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null;"
        "$t = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02);"
        f"$n = $t.GetElementsByTagName('text'); $n.Item(0).InnerText = '{title}'; $n.Item(1).InnerText = '{body}';"
        "$toast = [Windows.UI.Notifications.ToastNotification]::new($t);"
        "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('Windows PowerShell').Show($toast)"
    )
    try:
        subprocess.run(["powershell", "-NoProfile", "-Command", script], timeout=30, capture_output=True)
    except Exception:
        pass


if __name__ == "__main__":
    raise SystemExit(main())
