"""How well does local Qwen read LINE post images, with and without help?

Variants (all temperature 0, thinking off):
  vision   : macOS Vision OCR alone (no LLM) - the helper's own score
  raw      : Qwen sees the image as captured
  tiles    : image enlarged 2x and cut into overlapping tiles; Qwen reads each tile
  hint     : Qwen sees the 2x image plus Vision's OCR lines as a (possibly wrong) reference
Scores = share of reference facts (truth.json, read by Claude) found in the output.
"""
import base64, io, json, sys, time, unicodedata, subprocess, urllib.request
from pathlib import Path
from PIL import Image

HERE = Path(__file__).resolve().parents[1] / "data" / "qwen_ocr_study"  # truth, samples, results; scratch image
VISION = Path("/Users/eita/projects/slot-line/build/vision_ocr")
MODEL = sys.argv[1] if len(sys.argv) > 1 else "qwen3.8:latest"
VARIANTS = sys.argv[2].split(",") if len(sys.argv) > 2 else ["vision", "raw", "tiles", "hint"]
ONLY = sys.argv[3].split(",") if len(sys.argv) > 3 else None
truth = json.loads((HERE / "truth.json").read_text())
samples = json.loads((HERE / "samples.json").read_text())

PROMPT = ("これはパチンコ店の公式LINEに届いた画像です。画像に書かれている文字を、上から順にすべてそのまま書き起こしてください。"
          "機種名・日付・時刻・数字・取材名は特に正確に。読めない部分は推測せず「?」としてください。書き起こした文字だけを出力してください。")
HINT = ("これはパチンコ店の公式LINEに届いた画像です。下の「OCR結果」は別の文字認識で読んだもので、誤りや抜けを含みます。"
        "画像をよく見て、OCR結果を参考にしながら、画像に書かれている文字を上から順に正しく書き起こしてください。"
        "機種名・日付・時刻・数字・取材名は特に正確に。画像にない文字は書かないでください。書き起こした文字だけを出力してください。\n\nOCR結果:\n")


def norm(text: str) -> str:
    return "".join(unicodedata.normalize("NFKC", text).split()).lower()


def score(sample: str, text: str) -> tuple[int, int, list[str]]:
    facts = truth[sample]["facts"]
    t = norm(text)
    missed = [name for name, alts in facts.items() if not any(all(norm(k) in t for k in alt) for alt in alts)]
    return len(facts) - len(missed), len(facts), missed


def b64(image: Image.Image) -> str:
    buf = io.BytesIO()
    image.convert("RGB").save(buf, "PNG")
    return base64.b64encode(buf.getvalue()).decode()


def qwen(prompt: str, image: Image.Image) -> tuple[str, float]:
    body = {"model": MODEL, "stream": False, "think": False,
            "options": {"temperature": 0, "num_predict": 1200, "num_ctx": 8192},
            "messages": [{"role": "user", "content": prompt, "images": [b64(image)]}]}
    req = urllib.request.Request("http://localhost:11434/api/chat", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    start = time.time()
    with urllib.request.urlopen(req, timeout=900) as resp:
        out = json.loads(resp.read())
    return out["message"]["content"], time.time() - start


def vision(image: Image.Image) -> str:
    path = HERE / "_vision_tmp.png"
    image.save(path)
    out = subprocess.run([str(VISION), str(path)], capture_output=True, text=True).stdout
    lines = json.loads(out.splitlines()[0])["lines"]
    lines.sort(key=lambda l: (l["box"][1] // 12, l["box"][0]))
    return "\n".join(l["text"] for l in lines)


def tiles(image: Image.Image, height: int = 420, overlap: int = 70) -> list[Image.Image]:
    parts, top = [], 0
    while True:
        bottom = min(image.height, top + height)
        parts.append(image.crop((0, top, image.width, bottom)))
        if bottom >= image.height:
            return parts
        top = bottom - overlap


results_path = HERE / f"run_{MODEL.replace(':', '_')}.jsonl"
for s in samples:
    name = s["sample"]
    if ONLY and name not in ONLY:
        continue
    image = Image.open(Path(__file__).resolve().parents[1] / s["image"]).convert("RGB")
    big = image.resize((image.width * 2, image.height * 2), Image.LANCZOS)
    for variant in VARIANTS:
        start = time.time()
        if variant == "vision":
            text, secs = vision(big), time.time() - start
        elif variant == "raw":
            text, secs = qwen(PROMPT, image)
        elif variant == "tiles":
            texts, secs = [], 0.0
            for part in tiles(image):
                t, dt = qwen(PROMPT, part.resize((part.width * 2, part.height * 2), Image.LANCZOS))
                texts.append(t); secs += dt
            text = "\n".join(texts)
        elif variant == "hint":
            text, secs = qwen(HINT + vision(big), big)
        got, total, missed = score(name, text)
        row = {"sample": name, "variant": variant, "model": MODEL, "got": got, "total": total, "missed": missed,
               "seconds": round(secs, 1), "text": text}
        with results_path.open("a") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(f"{name} {variant:7s} {got}/{total} {secs:6.1f}s missed={missed}", flush=True)
