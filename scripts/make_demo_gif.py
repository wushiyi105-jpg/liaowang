"""生成 assets/demo.gif：960×600 终端风演示。

画面里的数字是真实跑出来的：12 条候选、6 条过线、6 条被过滤。
"""

from __future__ import annotations

import os

from PIL import Image, ImageDraw, ImageFont

W, H = 960, 600
BG, BAR, LINE = "#0b0f14", "#161b22", "#21262d"
GREEN, TEXT, DIM = "#7ee787", "#c9d1d9", "#8b949e"
BLUE, YELLOW, RED = "#79c0ff", "#e3b341", "#ff7b72"
FONT_PATH = r"C:\Windows\Fonts\msyh.ttc"
LINE_H, MAX_W = 25, 904
COLORS = {"cmd": GREEN, "out": TEXT, "dim": DIM, "cite": BLUE, "warn": YELLOW, "bad": RED}


def font(size: int):
    return ImageFont.truetype(FONT_PATH, size)


_M = ImageDraw.Draw(Image.new("RGB", (1, 1)))


def clip(text: str, size: int = 16) -> str:
    f = font(size)
    if _M.textlength(text, font=f) <= MAX_W:
        return text
    while text and _M.textlength(text + "…", font=f) > MAX_W:
        text = text[:-1]
    return text + "…"


def render(rows, cursor_row=None):
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, 36], fill=BAR)
    for i, c in enumerate(["#ff5f56", "#ffbd2e", "#27c93f"]):
        d.ellipse([16 + i * 22, 12, 28 + i * 22, 24], fill=c)
    d.text((92, 9), "liaowang — 情报简报", font=font(15), fill=DIM)
    d.line([0, 36, W, 36], fill=LINE)
    y = 54
    for idx, (style, text) in enumerate(rows):
        shown = clip(text)
        d.text((26, y), shown, font=font(16), fill=COLORS[style])
        if cursor_row == idx:
            w = _M.textlength(shown, font=font(16))
            d.rectangle([26 + w + 4, y + 2, 26 + w + 12, y + 19], fill=GREEN)
        y += LINE_H
        if y > H - 16:
            break
    return img


SCRIPT = [
    ("cmd", '> python -m liaowang watch add "RAG 框架" --topic "topic:rag" --min-stars 500'),
    ("out", "· 监控 [1] RAG 框架 —— github: topic:rag（star ≥ 500）"),
    ("dim", ""),
    ("cmd", "> python -m liaowang scan --id 1"),
    ("out", "=== 扫描 [1] RAG 框架 ==="),
    ("out", "抓到 12 条，新的 12 条，值得看 6，过滤 6"),
    ("cite", "一句话：真正对口的是 ragflow 和 graphify，前者成熟、后者是知识图谱检索的新思路。"),
    ("dim", "       LangChain 仍值得跟踪，但重心已偏 agent。"),
    ("dim", ""),
    ("cmd", "> python -m liaowang brief"),
    ("out", "共 12 条新条目：值得看 6、过滤 6、未评分 0"),
    ("out", "1. [95] infiniflow/ragflow（RAG 引擎 · 94645 star）"),
    ("dim", "   直接对标主题，agent-native RAG 引擎，做选型绕不开。"),
    ("out", "2. [82] Graphify-Labs/graphify（知识图谱 RAG · 152900 star）"),
    ("out", "3. [80] Mintplex-Labs/anything-llm（RAG 应用 · 68602 star）"),
    ("out", "4. [76] headroomlabs-ai/headroom（RAG 优化 · 80747 star）"),
    ("out", "5. [68] PaddlePaddle/PaddleOCR（OCR 工具 · 93138 star）"),
]
TAIL = [
    ("dim", ""),
    ("warn", "12 条里只留 6 条。剩下的 6 条被过滤，理由也存着——想查就查。"),
    ("dim", "awesome 清单、教程合集、纯 UI 层，模型都判为噪音。"),
]


def build():
    frames, shown = [], []
    for style, text in SCRIPT:
        if style == "cmd":
            for i in range(6, len(text) + 1, 6):
                frames.append(render(shown + [("cmd", text[:i])], cursor_row=len(shown)))
        shown = shown + [(style, text)]
        frames.append(render(shown))
    for _ in range(12):
        frames.append(render(shown + TAIL))
    frames = [f.quantize(colors=20, method=Image.MEDIANCUT) for f in frames]
    os.makedirs("assets", exist_ok=True)
    out = os.path.join("assets", "demo.gif")
    frames[0].save(out, save_all=True, append_images=frames[1:], duration=140, loop=0, optimize=True)
    print(f"ok -> {out}  {len(frames)} 帧  {os.path.getsize(out) / 1024:.1f} KB")


if __name__ == "__main__":
    build()
