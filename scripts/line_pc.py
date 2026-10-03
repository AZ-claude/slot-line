"""Drive the Windows LINE desktop app (runs ON Windows, in the logged-in session).

LINE PC exposes no text through UI Automation, so this module works with the
window geometry, the clipboard, the keyboard and Windows' built-in Japanese
OCR. It never reads LINE's local data files.

Library use:
    pc = LinePC(); pc.prepare(); png = pc.shot(Path("x.png")); lines = ocr_lines(png)

Command line (for exploration / remote checks):
    python line_pc.py actions.json result.json
where actions.json is a list such as
    [{"do": "prepare"}, {"do": "click", "x": 60, "y": 150}, {"do": "shot", "path": "a.png", "ocr": true}]
"""

from __future__ import annotations

import asyncio
import ctypes
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

WINDOW_X, WINDOW_Y = 40, 40
WINDOW_W, WINDOW_H = 1100, 980


def _dpi_aware() -> None:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def normalize_ocr(text: str) -> str:
    """Windows OCR puts spaces between Japanese characters; drop all whitespace."""
    return re.sub(r"\s+", "", text)


def ocr_lines(png: Path, crop: tuple[int, int, int, int] | None = None, scale: int = 1) -> list[dict[str, Any]]:
    """OCR a PNG (optionally a crop box in image pixels). Returns lines with boxes.

    scale > 1 enlarges the image first: Windows OCR misreads small UI text
    (chat names in the search list) far less when it is bigger. Boxes stay in
    the original pixels."""
    from PIL import Image
    from winrt.windows.globalization import Language
    from winrt.windows.graphics.imaging import BitmapDecoder
    from winrt.windows.media.ocr import OcrEngine
    from winrt.windows.storage import FileAccessMode, StorageFile

    source = png
    if crop or scale > 1:
        source = png.with_name(png.stem + "_ocr.png")
        with Image.open(png) as image:
            image = image.crop(crop) if crop else image
            if scale > 1:
                # the darkest channel turns coloured text (LINE highlights search matches in
                # green) black, which Windows OCR reads far better
                from PIL import ImageChops
                r, g, b = image.convert("RGB").split()
                image = ImageChops.darker(ImageChops.darker(r, g), b)
                image = image.resize((image.width * scale, image.height * scale), Image.LANCZOS)
            image.save(source)

    async def run() -> list[dict[str, Any]]:
        file = await StorageFile.get_file_from_path_async(str(source.resolve()))
        stream = await file.open_async(FileAccessMode.READ)
        decoder = await BitmapDecoder.create_async(stream)
        bitmap = await decoder.get_software_bitmap_async()
        engine = OcrEngine.try_create_from_language(Language("ja"))
        if engine is None:
            raise RuntimeError("ja_ocr_not_available")
        result = await engine.recognize_async(bitmap)
        lines = []
        for line in result.lines:
            words = list(line.words)
            x0 = min(w.bounding_rect.x for w in words)
            y0 = min(w.bounding_rect.y for w in words)
            x1 = max(w.bounding_rect.x + w.bounding_rect.width for w in words)
            y1 = max(w.bounding_rect.y + w.bounding_rect.height for w in words)
            ox, oy = (crop[0], crop[1]) if crop else (0, 0)
            lines.append({"text": normalize_ocr(line.text), "raw": line.text,
                          "box": [int(x0 / scale + ox), int(y0 / scale + oy), int(x1 / scale + ox), int(y1 / scale + oy)]})
        return lines

    try:
        return asyncio.run(run())
    finally:
        if source != png:
            source.unlink(missing_ok=True)


class LinePC:
    def __init__(self) -> None:
        _dpi_aware()
        import win32api  # noqa: F401  (fail early when pywin32 is missing)
        self.hwnd: int | None = None

    # -- window -----------------------------------------------------------
    def find_window(self) -> int:
        import win32gui
        import win32process
        import win32api
        import win32con

        found: list[int] = []

        def visit(hwnd: int, _: Any) -> None:
            if not win32gui.IsWindowVisible(hwnd) or win32gui.GetWindowText(hwnd) != "LINE":
                return
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            try:
                handle = win32api.OpenProcess(win32con.PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
                exe = win32process.GetModuleFileNameEx(handle, 0)
            except Exception:
                return
            if exe.lower().endswith("\\line.exe"):
                found.append(hwnd)

        win32gui.EnumWindows(visit, None)
        if not found and not getattr(self, "_relaunched", False):
            # LINE closes its main window to the tray (e.g. on Esc); starting it again brings it back
            import os
            import subprocess
            launcher = Path(os.environ.get("LOCALAPPDATA", "")) / "LINE" / "bin" / "LineLauncher.exe"
            if launcher.exists():
                self._relaunched = True
                subprocess.Popen([str(launcher)])
                time.sleep(10)
                return self.find_window()
        if not found:
            raise RuntimeError("LINE_window_not_found")
        self._relaunched = False

        def area(hwnd: int) -> int:
            left, top, right, bottom = win32gui.GetWindowRect(hwnd)
            return (right - left) * (bottom - top)

        # LINE's modal dialogs are also titled "LINE"; the main window is the biggest one
        self.hwnd = max(found, key=area)
        self.dialogs = [h for h in found if h != self.hwnd and area(h) < 500 * 300]
        return self.hwnd

    def close_dialogs(self) -> int:
        """Close LINE's small modal dialogs (e.g. "スマートフォンでのみ確認可能なメッセージです")."""
        import win32con
        import win32gui

        self.find_window()
        for hwnd in self.dialogs:
            win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
        if self.dialogs:
            time.sleep(0.8)
        return len(self.dialogs)

    def prepare(self) -> dict[str, Any]:
        """Restore, bring to front and give the LINE window a fixed size and place."""
        import win32api
        import win32con
        import win32gui

        hwnd = self.find_window()
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        # SetForegroundWindow is refused unless we "own" input; a bare ALT press allows it.
        win32api.keybd_event(win32con.VK_MENU, 0, 0, 0)
        win32api.keybd_event(win32con.VK_MENU, 0, win32con.KEYEVENTF_KEYUP, 0)
        try:
            win32gui.SetForegroundWindow(hwnd)
        except Exception:
            pass
        # keep LINE above every other window while we screenshot it (undone by release())
        win32gui.SetWindowPos(hwnd, win32con.HWND_TOPMOST, WINDOW_X, WINDOW_Y, WINDOW_W, WINDOW_H, 0)
        time.sleep(0.8)
        return {"rect": self.rect(), "foreground": win32gui.GetForegroundWindow() == hwnd}

    def release(self) -> None:
        import win32con
        import win32gui

        if self.hwnd:
            win32gui.SetWindowPos(self.hwnd, win32con.HWND_NOTOPMOST, 0, 0, 0, 0,
                                  win32con.SWP_NOMOVE | win32con.SWP_NOSIZE)

    @staticmethod
    def hide_own_console() -> None:
        """Minimise the console this script runs in, so it cannot cover LINE."""
        console = ctypes.windll.kernel32.GetConsoleWindow()
        if console:
            ctypes.windll.user32.ShowWindow(console, 6)  # SW_MINIMIZE

    def rect(self) -> tuple[int, int, int, int]:
        import win32gui

        return win32gui.GetWindowRect(self.hwnd or self.find_window())

    # -- input (coordinates are relative to the window's top-left) ----------
    def click(self, x: int, y: int, double: bool = False) -> None:
        import win32api
        import win32con

        left, top, _, _ = self.rect()
        win32api.SetCursorPos((left + x, top + y))
        time.sleep(0.05)
        for _ in range(2 if double else 1):
            win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
            win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
            time.sleep(0.08)

    def move(self, x: int, y: int) -> None:
        import win32api

        left, top, _, _ = self.rect()
        win32api.SetCursorPos((left + x, top + y))
        time.sleep(0.6)

    def scroll(self, x: int, y: int, notches: int) -> None:
        """Positive notches scroll up (older messages), negative scroll down."""
        import win32api
        import win32con

        left, top, _, _ = self.rect()
        win32api.SetCursorPos((left + x, top + y))
        for _ in range(abs(notches)):
            win32api.mouse_event(win32con.MOUSEEVENTF_WHEEL, 0, 0, 120 if notches > 0 else -120, 0)
            time.sleep(0.05)

    def hscroll(self, x: int, y: int, notches: int) -> None:
        """Horizontal wheel over (x, y); positive scrolls right. Never clicks."""
        import win32api

        MOUSEEVENTF_HWHEEL = 0x01000
        left, top, _, _ = self.rect()
        win32api.SetCursorPos((left + x, top + y))
        for _ in range(abs(notches)):
            win32api.mouse_event(MOUSEEVENTF_HWHEEL, 0, 0, 120 if notches > 0 else -120, 0)
            time.sleep(0.05)

    def shift_wheel(self, x: int, y: int, notches: int) -> None:
        """Shift + vertical wheel over (x, y): horizontal scrolling in many Qt views."""
        import win32api
        import win32con

        left, top, _, _ = self.rect()
        win32api.SetCursorPos((left + x, top + y))
        win32api.keybd_event(win32con.VK_SHIFT, 0, 0, 0)
        try:
            for _ in range(abs(notches)):
                win32api.mouse_event(win32con.MOUSEEVENTF_WHEEL, 0, 0, -120 if notches > 0 else 120, 0)
                time.sleep(0.05)
        finally:
            win32api.keybd_event(win32con.VK_SHIFT, 0, win32con.KEYEVENTF_KEYUP, 0)

    def paste(self, text: str) -> None:
        import win32clipboard
        import win32con

        win32clipboard.OpenClipboard()
        try:
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, text)
        finally:
            win32clipboard.CloseClipboard()
        self.key("ctrl+v")

    def key(self, combo: str) -> None:
        import win32api
        import win32con

        names = {"ctrl": win32con.VK_CONTROL, "enter": win32con.VK_RETURN, "esc": win32con.VK_ESCAPE,
                 "a": ord("A"), "v": ord("V"), "f": ord("F"), "home": win32con.VK_HOME, "end": win32con.VK_END,
                 "pgup": win32con.VK_PRIOR, "pgdn": win32con.VK_NEXT, "down": win32con.VK_DOWN,
                 "up": win32con.VK_UP, "back": win32con.VK_BACK, "tab": win32con.VK_TAB,
                 "delete": win32con.VK_DELETE}
        codes = [names[part] for part in combo.lower().split("+")]
        for code in codes:
            win32api.keybd_event(code, 0, 0, 0)
        for code in reversed(codes):
            win32api.keybd_event(code, 0, win32con.KEYEVENTF_KEYUP, 0)
        time.sleep(0.15)

    # -- capture ------------------------------------------------------------
    def shot(self, path: Path, box: tuple[int, int, int, int] | None = None) -> Path:
        """Screenshot the window (or a window-relative box) to PNG."""
        from PIL import ImageGrab

        left, top, right, bottom = self.rect()
        bbox = (left, top, right, bottom) if box is None else (left + box[0], top + box[1], left + box[2], top + box[3])
        path.parent.mkdir(parents=True, exist_ok=True)
        image = ImageGrab.grab(bbox=bbox, all_screens=True)
        if path.suffix.lower() in {".jpg", ".jpeg"}:
            image.convert("RGB").save(path, quality=75)
        else:
            image.save(path)
        return path


def run_actions(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    pc = LinePC()
    results = []
    for action in actions:
        do = action["do"]
        entry: dict[str, Any] = {"do": do}
        try:
            if do == "prepare":
                entry.update(pc.prepare())
            elif do == "click":
                pc.click(action["x"], action["y"], action.get("double", False))
            elif do == "shiftwheel":
                pc.shift_wheel(action["x"], action["y"], action["notches"])
            elif do == "hscroll":
                pc.hscroll(action["x"], action["y"], action["notches"])
            elif do == "move":
                pc.move(action["x"], action["y"])
            elif do == "scroll":
                pc.scroll(action["x"], action["y"], action["notches"])
            elif do == "paste":
                pc.paste(action["text"])
            elif do == "key":
                pc.key(action["key"])
            elif do == "wait":
                time.sleep(action["s"])
            elif do == "fgshot":
                # screenshot whatever window is in front (e.g. LINE's image viewer)
                import win32gui
                from PIL import ImageGrab
                hwnd = win32gui.GetForegroundWindow()
                rect = win32gui.GetWindowRect(hwnd)
                ImageGrab.grab(bbox=rect, all_screens=True).save(action["path"])
                entry.update(path=action["path"], title=win32gui.GetWindowText(hwnd), rect=list(rect),
                             is_line_main=hwnd == pc.hwnd)
            elif do == "screen":
                from PIL import ImageGrab
                ImageGrab.grab(all_screens=True).save(action["path"])
                entry["path"] = action["path"]
            elif do == "close_dialogs":
                entry["closed"] = pc.close_dialogs()
            elif do == "shot":
                png = pc.shot(Path(action["path"]), tuple(action["box"]) if action.get("box") else None)
                entry["path"] = str(png)
                if action.get("ocr"):
                    entry["lines"] = ocr_lines(png)
            else:
                raise ValueError(f"unknown action {do}")
            entry["ok"] = True
        except Exception as exc:  # report and stop: never keep clicking blind
            entry.update(ok=False, error=f"{type(exc).__name__}: {exc}")
            results.append(entry)
            break
        results.append(entry)
    return results


if __name__ == "__main__":
    actions = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    Path(sys.argv[2]).write_text(json.dumps(run_actions(actions), ensure_ascii=False, indent=1), encoding="utf-8")
