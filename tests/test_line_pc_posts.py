import importlib.util
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

HAS_IMAGING = bool(importlib.util.find_spec("PIL") and importlib.util.find_spec("numpy"))


@unittest.skipUnless(HAS_IMAGING, "needs Pillow and numpy: run with .venv/bin/python")
class LinePcPostsTests(unittest.TestCase):
    def setUp(self):
        from scripts import line_pc_posts
        self.m = line_pc_posts

    def test_dates_and_times_from_ocr(self):
        today = date(2026, 10, 1)
        self.assertEqual(self.m.parse_date("今日", today), "2026-10-01")
        self.assertEqual(self.m.parse_date("昨日", today), "2026-09-30")
        self.assertEqual(self.m.parse_date("9.25(金)", today), "2026-09-25")
        self.assertEqual(self.m.parse_date("925(全)", today), "2026-09-25")
        self.assertEqual(self.m.parse_date("12月31日(木)", today), "2025-12-31")
        self.assertEqual(self.m.parse_time("午後 9:26"), "21:26")
        self.assertEqual(self.m.parse_time("午前 12:05"), "00:05")
        self.assertIsNone(self.m.parse_time("第をア"))

    def _page(self, draw_fn):
        from PIL import Image, ImageDraw

        image = Image.new("RGB", (640, 700), (255, 255, 255))
        draw_fn(ImageDraw.Draw(image))
        path = Path(tempfile.mkdtemp()) / "run_p00.png"
        image.save(path)
        return path

    def test_consecutive_images_and_time_stamp_become_separate_posts(self):
        def draw(d):
            d.rectangle((12, 10, 620, 300), fill=(200, 30, 30))      # image 1
            d.rectangle((12, 318, 620, 600), fill=(30, 30, 200))     # image 2, 17 px below
            d.rectangle((570, 610, 620, 624), fill=(150, 150, 150))  # time stamp of image 2
        page = self._page(draw)
        posts = self.m.cut_run("hall", "run", date(2026, 10, 1), [page], {"capture": {"stop": "top_of_history"}})
        store_posts = [p for p in posts if not p["own"]]
        self.assertEqual(len(store_posts), 2)
        self.assertLess(store_posts[0]["y1"], store_posts[1]["y0"])
        self.assertGreaterEqual(store_posts[1]["y1"], 610)

    def test_own_green_message_is_not_a_store_post(self):
        def draw(d):
            d.rectangle((12, 10, 620, 300), fill=(200, 30, 30))
            d.rectangle((500, 400, 620, 440), fill=(195, 246, 157))
        posts = self.m.cut_run("hall", "run", date(2026, 10, 1), [self._page(draw)], {"capture": {"stop": "top_of_history"}})
        self.assertEqual([p["own"] for p in posts], [False, True])

    def test_stitch_places_older_page_above(self):
        import numpy as np

        base = np.random.default_rng(1).integers(0, 255, (1270, 640, 3), dtype=np.uint8)
        from PIL import Image

        folder = Path(tempfile.mkdtemp())
        Image.fromarray(base[570:1270]).save(folder / "r_p00.png")  # newest, lower
        Image.fromarray(base[0:700]).save(folder / "r_p01.png")     # older, 570 px higher
        strip, offsets = self.m.stitch([folder / "r_p00.png", folder / "r_p01.png"])
        self.assertEqual(strip.shape[0], 1270)
        self.assertEqual(offsets, [570, 0])
        self.assertTrue((strip == base).all())

    def test_same_banner_on_another_day_is_a_new_post(self):
        fp = "0f0f0f0f0f0f0f0f"
        self.assertTrue(self.m.is_same_post(fp, "2026-09-27 20:00", f"{fp}|2026-09-27 20:00"))
        self.assertTrue(self.m.is_same_post(fp, "? 20:00", f"{fp}|2026-09-27 20:00"))
        self.assertFalse(self.m.is_same_post(fp, "2026-09-28 20:00", f"{fp}|2026-09-27 20:00"))
        self.assertFalse(self.m.is_same_post("f0f0f0f0f0f0f0f0", "2026-09-27 20:00", f"{fp}|2026-09-27 20:00"))

    def test_fingerprint_ignores_recompression(self):
        from PIL import Image
        import io

        image = Image.new("RGB", (600, 400))
        for x in range(0, 600, 40):
            image.paste((x % 255, 80, 200 - x % 200), (x, 0, x + 20, 400))
        buffer = io.BytesIO()
        image.save(buffer, "JPEG", quality=40)
        again = Image.open(io.BytesIO(buffer.getvalue()))
        self.assertLessEqual(self.m.hamming(self.m.fingerprint(image), self.m.fingerprint(again)), self.m.DUPLICATE_BITS)


if __name__ == "__main__":
    unittest.main()
