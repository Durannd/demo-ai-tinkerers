"""Folha de contato (contact sheet) para conferir um render, e comparação antes × depois.

Uso:
  python pipeline/folha.py <video.mp4> [--n 8] [--saida folha.jpg]
  python pipeline/folha.py <depois.mp4> --antes <antes.mp4> [--n 6] [--saida comparacao.jpg]
  python pipeline/folha.py <video.mp4> --tempos 2,9.5,14      # tempos exatos

Os quadros saem rotulados com o tempo. Na comparação, cada linha é o mesmo instante nos dois vídeos.
"""
from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from common import duracao, rodar
from estilo import caminho_fonte


def quadro(video: Path, t: float, destino: Path, largura: int) -> Image.Image:
    rodar(["ffmpeg", "-y", "-v", "error", "-ss", f"{t:.3f}", "-i", str(video), "-frames:v", "1",
           "-vf", f"scale={largura}:-2", str(destino)])
    return Image.open(destino).convert("RGB")


def rotular(img: Image.Image, texto: str) -> Image.Image:
    d = ImageDraw.Draw(img)
    f = ImageFont.truetype(caminho_fonte("rotulo"), max(12, img.width // 28))
    d.rectangle([0, 0, d.textlength(texto, font=f) + 16, f.size + 12], fill=(0, 0, 0))
    d.text((8, 5), texto, font=f, fill=(255, 220, 80))
    return img


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--antes")
    ap.add_argument("--n", type=int, default=8)
    ap.add_argument("--tempos")
    ap.add_argument("--largura", type=int, default=480)
    ap.add_argument("--saida")
    a = ap.parse_args()

    depois = Path(a.video)
    dur = duracao(depois)
    if a.tempos:
        tempos = [float(x) for x in a.tempos.split(",")]
    else:
        tempos = [dur * (i + 0.5) / a.n for i in range(a.n)]
    saida = Path(a.saida) if a.saida else depois.with_name(depois.stem + ("_comparacao.jpg" if a.antes else "_folha.jpg"))

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        if a.antes:
            antes = Path(a.antes)
            linhas = []
            for i, t in enumerate(tempos):
                ta = min(t, duracao(antes) - 0.1)
                linhas.append((rotular(quadro(antes, ta, tmp / f"a{i}.jpg", a.largura), f"ANTES {t:.1f}s"),
                               rotular(quadro(depois, t, tmp / f"d{i}.jpg", a.largura), f"DEPOIS {t:.1f}s")))
            w, h = linhas[0][1].size
            folha = Image.new("RGB", (w * 2 + 6, (h + 6) * len(linhas)), (20, 20, 20))
            for i, (x, y) in enumerate(linhas):
                folha.paste(x.resize((w, h)), (0, i * (h + 6)))
                folha.paste(y, (w + 6, i * (h + 6)))
        else:
            imgs = [rotular(quadro(depois, t, tmp / f"q{i}.jpg", a.largura), f"{t:.1f}s") for i, t in enumerate(tempos)]
            w, h = imgs[0].size
            cols = 4 if len(imgs) > 4 else len(imgs)
            rows = (len(imgs) + cols - 1) // cols
            folha = Image.new("RGB", ((w + 6) * cols, (h + 6) * rows), (20, 20, 20))
            for i, im in enumerate(imgs):
                folha.paste(im, ((i % cols) * (w + 6), (i // cols) * (h + 6)))
        folha.save(saida, quality=88)
    print(saida)


if __name__ == "__main__":
    main()
