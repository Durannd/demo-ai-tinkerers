"""Prepara cenas de foto para o parallax 2.5D (render/src/cenas/Parallax.tsx).

Quando: visual.movimento == "parallax", ou "auto" (padrão) com config render.parallax == "auto":
  ~40% das fotos elegíveis (seed da cena), nunca duas seguidas, só com duração ≥ 3,5 s e foto grande.
O que faz: aplica o tratamento de cor do canal na foto, calcula a profundidade (Depth Anything V2 Small),
põe o plano focal no assunto (saliência) e grava o mapa de deslocamento (R = x, G = y).
"""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image

import estilo
import movimento
import profundidade
from common import config, log, rodar

EXT_IMG = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff"}
TIPOS = {"stock_imagem", "arquivo_historico", "ia_imagem", "foto", "local"}


def elegivel(c, fps: int, h: int) -> bool:
    if not c.midia or c.midia.suffix.lower() not in EXT_IMG or c.dado["visual"]["tipo"] not in TIPOS:
        return False
    if c.dado["visual"].get("colagem"):  # colagem pedida tem prioridade (pipeline/colagem.py)
        return False
    with Image.open(c.midia) as im:
        grande = im.height >= h * 0.75 or im.width >= h * 1.3
    return grande and c.frames / fps >= 3.5


def escolher(cenas: list, fps: int, h: int) -> list:
    modo = config().get("render", {}).get("parallax", "auto")
    if modo is False or not profundidade.disponivel():
        return []
    out, anterior = [], False
    for c in cenas:
        mov = c.dado.get("movimento") or "auto"
        pedido = mov == "parallax"
        auto = modo == "auto" and mov == "auto" and estilo.rng(c.dado, "parallax").random() < 0.4
        if elegivel(c, fps, h) and (pedido or (auto and not anterior)):
            out.append(c)
            anterior = True
        else:
            anterior = False
    return out


def preparar(ep: Path, c) -> None:
    """Converte a cena em tipo 'parallax' para o Remotion (c.dado é copiado, o storyboard não muda)."""
    import numpy as np

    pasta = ep / "build" / "parallax"
    pasta.mkdir(parents=True, exist_ok=True)
    chave = f"{c.id}_{int(c.midia.stat().st_mtime)}"
    graduada = pasta / f"{chave}_cor.jpg"
    if not graduada.exists():
        rodar(["ffmpeg", "-y", "-v", "error", "-i", str(c.midia), "-vf",
               f"scale='min(3840,iw)':-2,{estilo.filtro_tratamento(c.dado)}", "-q:v", "2", str(graduada)])
    prof = pasta / f"{chave}_prof.png"
    if not prof.exists():
        profundidade.profundidade(c.midia, prof)
    r = estilo.rng(c.dado, "parallax-dir")
    cx, cy, _ = movimento.saliencia(c.midia)
    mapa_p = pasta / f"{chave}_desloc.png"
    if not mapa_p.exists():
        d = np.asarray(Image.open(prof).convert("L"), dtype=np.float32) / 255.0
        hh, ww = d.shape
        foco = float(np.median(d[int(cy * hh * 0.8):int(cy * hh * 0.8 + hh * 0.2) + 1,
                                 int(cx * ww * 0.8):int(cx * ww * 0.8 + ww * 0.2) + 1]))
        rel = np.clip(d - foco, -0.5, 0.5)
        ang = math.radians(r.choice([0, 180, 12, 168, -12, 192]))  # quase horizontal, sentido varia
        R = np.clip(128 + rel * 255 * math.cos(ang), 0, 255).astype(np.uint8)
        G = np.clip(128 + rel * 255 * math.sin(ang), 0, 255).astype(np.uint8)
        B = np.full_like(R, 128)
        Image.fromarray(np.dstack([R, G, B]), "RGB").save(mapa_p)
    v = dict(c.dado["visual"])
    v["tipo"] = "parallax"
    v["parallax"] = {"amplitude": round(r.uniform(0.012, 0.02), 4), "dolly": round(r.uniform(0.03, 0.07), 3),
                     "sentido_dolly": r.choice(["entra", "entra", "sai"]), "foco_x": round(cx, 3), "foco_y": round(cy, 3)}
    c.dado = {**c.dado, "visual": v}
    c.extras["imagens_remotion"] = [graduada, mapa_p]
    c.extras["movimento"] = "parallax"
    log(f"  {c.id}: parallax 2.5D (foco {cx:.2f},{cy:.2f})")
