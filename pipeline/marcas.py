"""Marcações desenhadas sobre foto/vídeo real (cena.marca): círculo à mão, seta, sublinhado, caixa e foco.

O traço se desenha na palavra-âncora (~0,55 s), fica e some no fim do plano (ou na palavra `ate`).
Coordenadas RELATIVAS À IMAGEM (0–1, não à tela): a marca acompanha a câmera (movimento.clipe devolve a
trajetória quadro a quadro) e o punch-in. Sai uma camada RGBA (MOV/PNG) que o montar.py sobrepõe ao mezanino
DEPOIS do tratamento de cor (senão o vermelho viraria cinza nas fotos históricas).

  circulo     x, y = centro; largura (fração da largura da imagem, padrão 0,2); altura opcional (oval)
  sublinhado  x, y = centro da linha; largura (padrão 0,3)
  seta        x, y = PONTA (o que se aponta); de = [x, y] da cauda (padrão: embaixo à esquerda)
  caixa       x, y = centro; largura, altura (padrão 0,3 × 0,25)
  foco        x, y = centro; largura/altura da elipse iluminada — o resto da imagem escurece
  texto       opcional (≤ 4 palavras): etiqueta curta junto da marca
"""
from __future__ import annotations

import math
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from common import log
from estilo import rng, tokens

TIPOS = ("circulo", "seta", "sublinhado", "caixa", "foco")
DESENHO = 0.55       # s para o traço se desenhar
SAI = 0.3            # s do fade de saída
TEXTO_ATRASO = 0.35  # a etiqueta entra depois do traço


def lista(cena: dict) -> list[dict]:
    m = cena.get("marca")
    if not m:
        return []
    return [x for x in (m if isinstance(m, list) else [m]) if isinstance(x, dict) and x.get("tipo") in TIPOS]


def _hex(c: str) -> tuple[int, int, int]:
    c = c.lstrip("#")
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)


def _ease(u: float) -> float:
    u = min(1.0, max(0.0, u))
    return 1 - (1 - u) ** 3 if u > 0.0 else 0.0


def janelas(c, fps: int) -> list[tuple[dict, float, float]]:
    """[(marca, início, fim)] em segundos relativos ao 1º quadro do clipe (inclui a alça de entrada). Marcas cuja
    âncora não é dita NESTA parte da cena (sub-cortes) ficam de fora."""
    import remotion
    pal = (c.extras.get("meta") or {}).get("palavras") or []
    corpo = c.frames / fps
    t0 = c.alca_antes / fps
    out = []
    for m in lista(c.dado):
        if m.get("ancora"):
            ti = remotion.achar_na_fala(pal, m["ancora"], 0.0)
            if ti is None or ti > corpo - 0.6:
                continue
        else:
            ti = 0.4
        tf = remotion.achar_na_fala(pal, m.get("ate"), ti + 0.05) if m.get("ate") else None
        tf = corpo - 0.15 if tf is None else tf
        tf = min(corpo + c.alca_depois / fps, max(tf, ti + DESENHO + 0.8))
        out.append((m, t0 + max(0.0, ti - 0.05), t0 + tf))
    return out


# ---------------------------------------------------------------- geometria (pixels de saída)
def _pts_circulo(cx, cy, rx, ry, r) -> np.ndarray:
    """Volta e 1/8 com raio que 'respira' um pouco e abre no fim (traço de caneta, não elipse de CAD)."""
    a0 = math.radians(r.uniform(-150, -110))
    giro = 2 * math.pi * 1.12
    f1, f2 = r.uniform(0, 6.28), r.uniform(0, 6.28)
    inc = math.radians(r.uniform(-12, -4))
    pts = []
    for k in range(160):
        s = k / 159
        a = a0 + giro * s
        rr = 1 + 0.035 * math.sin(2 * a + f1) + 0.02 * math.sin(3 * a + f2) + 0.07 * s
        x, y = rx * rr * math.cos(a), ry * rr * math.sin(a)
        pts.append((cx + x * math.cos(inc) - y * math.sin(inc), cy + x * math.sin(inc) + y * math.cos(inc)))
    return np.array(pts)


def _pts_linha(x0, y0, x1, y1, curva, r, n=60) -> np.ndarray:
    """Linha levemente curva (bezier quadrática) com um tremido mínimo."""
    mx, my = (x0 + x1) / 2, (y0 + y1) / 2
    dx, dy = x1 - x0, y1 - y0
    L = math.hypot(dx, dy) or 1
    px, py = -dy / L, dx / L
    cx, cy = mx + px * curva * L, my + py * curva * L
    fase = r.uniform(0, 6.28)
    pts = []
    for k in range(n):
        s = k / (n - 1)
        x = (1 - s) ** 2 * x0 + 2 * (1 - s) * s * cx + s * s * x1
        y = (1 - s) ** 2 * y0 + 2 * (1 - s) * s * cy + s * s * y1
        w = 0.004 * L * math.sin(s * 9 + fase)
        pts.append((x + px * w, y + py * w))
    return np.array(pts)


def _pts_caixa(cx, cy, lw, lh, r) -> np.ndarray:
    x0, y0, x1, y1 = cx - lw / 2, cy - lh / 2, cx + lw / 2, cy + lh / 2
    j = lambda: r.uniform(-0.012, 0.012) * min(lw, lh)
    cantos = [(x0 + j(), y0 + j()), (x1 + j(), y0 + j()), (x1 + j(), y1 + j()), (x0 + j(), y1 + j()),
              (x0 + j(), y0 + j())]
    pts = []
    for (a, b), (c, d) in zip(cantos, cantos[1:]):
        for k in range(30):
            s = k / 30
            pts.append((a + (c - a) * s, b + (d - b) * s))
    a, b = cantos[-1]
    pts.append((a + (cantos[1][0] - a) * 0.08, b + (cantos[1][1] - b) * 0.08))  # passa um pouco do início
    return np.array(pts)


def _parcial(pts: np.ndarray, p: float) -> np.ndarray:
    """Trecho inicial do traço com comprimento p (0–1), com a ponta interpolada (sem degraus)."""
    seg = np.hypot(*np.diff(pts, axis=0).T)
    acum = np.concatenate([[0], np.cumsum(seg)])
    alvo = acum[-1] * p
    i = int(np.searchsorted(acum, alvo))
    if i <= 0:
        return pts[:1]
    if i >= len(pts):
        return pts
    u = (alvo - acum[i - 1]) / max(1e-6, seg[i - 1])
    return np.vstack([pts[:i], pts[i - 1] + (pts[i] - pts[i - 1]) * u])


# ---------------------------------------------------------------- camada
def _etiqueta(texto: str, h: int, cor_txt) -> Image.Image:
    import graficos
    f = graficos.fonte("rotulo_forte", int(h * 0.03))
    t = texto.upper()
    tr = h * 0.03 * 0.1
    larg = graficos.largura_espacada(None, t, f, tr)
    asc, desc = graficos._metricas(f)
    pad_x, pad_y = int(h * 0.016), int(h * 0.01)
    im = Image.new("RGBA", (int(larg + 2 * pad_x), int(asc + desc * 0.3 + 2 * pad_y)), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([0, 0, im.width - 1, im.height - 1], radius=int(h * 0.006), fill=(14, 14, 16, 205))
    graficos.texto_espacado(d, (pad_x, pad_y), t, f, cor_txt + (255,), tr)
    return im


def _alfa_traco(w, h, pts, esp) -> np.ndarray:
    import cv2
    m = np.zeros((h, w), np.uint8)
    if len(pts) >= 2:
        cv2.polylines(m, [np.round(pts * 4).astype(np.int32)], False, 255, int(esp), cv2.LINE_AA, shift=2)
        r = max(1, int(esp / 2))
        for x, y in (pts[0], pts[-1]):  # pontas arredondadas
            cv2.circle(m, (int(round(x * 4)), int(round(y * 4))), r * 4, 255, -1, cv2.LINE_AA, shift=2)
    return m


def quadro(w: int, h: int, marcas_t: list[tuple[dict, float, float]], tr: tuple, t: float, cache: dict) -> np.ndarray | None:
    """BGRA (h, w, 4) da camada no instante t (s desde o 1º quadro), ou None se vazia."""
    import cv2
    sx, sy, ox, oy = tr
    tk = tokens()
    mk = tk.get("marca") or {}
    cor = _hex(mk.get("cor") or tk["cores"]["destaque"])
    cor_txt = _hex(mk.get("texto") or tk["cores"]["texto"])
    esp = max(3.0, h * 0.0075)
    cor_a = np.zeros((h, w), np.float32)    # alfa do traço colorido
    som_a = np.zeros((h, w), np.float32)    # alfa da sombra/escurecimento (preto)
    rotulos = []
    algo = False
    for m, ti, tf in marcas_t:
        if t < ti or t > tf + SAI:
            continue
        algo = True
        p = _ease((t - ti) / DESENHO)
        fade = 1.0 - min(1.0, max(0.0, (t - tf) / SAI))
        r = rng({"id": str(m), "narracao": ""}, "marca")
        x, y = float(m.get("x", 0.5)), float(m.get("y", 0.5))
        cx, cy = ox + x * sx, oy + y * sy
        tipo = m["tipo"]
        if tipo == "foco":
            lw = float(m.get("largura", 0.35)) * sx
            lh = float(m.get("altura", 0) or 0) * sy or lw * 0.8
            esc = np.zeros((h // 4, w // 4), np.uint8)
            cv2.ellipse(esc, (int(cx / 4), int(cy / 4)), (max(1, int(lw / 8)), max(1, int(lh / 8))), 0, 0, 360, 255, -1)
            esc = cv2.GaussianBlur(esc, (0, 0), max(2.0, lw / 4 / 6))
            fora = 1 - cv2.resize(esc, (w, h), interpolation=cv2.INTER_LINEAR).astype(np.float32) / 255
            som_a = np.maximum(som_a, fora * 0.62 * p * fade)
            anc = (cx + lw / 2, cy - lh / 2)
        else:
            if tipo == "circulo":
                lw = float(m.get("largura", 0.2)) * sx
                lh = float(m.get("altura", 0) or 0) * sy or lw * 0.82
                pts = _pts_circulo(cx, cy, lw / 2, lh / 2, r)
                anc = (cx + lw * 0.5, cy + lh * 0.35)
            elif tipo == "sublinhado":
                lw = float(m.get("largura", 0.3)) * sx
                pts = _pts_linha(cx - lw / 2, cy + r.uniform(-0.004, 0.004) * h, cx + lw / 2, cy, -0.04, r)
                anc = (cx - lw / 2, cy + h * 0.025)
            elif tipo == "caixa":
                lw = float(m.get("largura", 0.3)) * sx
                lh = float(m.get("altura", 0.25)) * sy
                pts = _pts_caixa(cx, cy, lw, lh, r)
                anc = (cx - lw / 2, cy - lh / 2 - h * 0.055)
            else:  # seta: da cauda até perto da ponta, curva, e a cabeça desenhada no fim
                de = m.get("de") or [x - 0.16, y + 0.2]
                tx, ty = ox + float(de[0]) * sx, oy + float(de[1]) * sy
                L = math.hypot(cx - tx, cy - ty) or 1
                folga = min(0.025 * w, L * 0.15)
                ex, ey = cx - (cx - tx) / L * folga, cy - (cy - ty) / L * folga
                corpo = _pts_linha(tx, ty, ex, ey, 0.12, r)
                pts = _parcial(corpo, min(1.0, p / 0.8))
                if p > 0.8:  # cabeça: dois traços curtos a ±28° da direção de chegada
                    k = (p - 0.8) / 0.2
                    a = math.atan2(corpo[-1][1] - corpo[-4][1], corpo[-1][0] - corpo[-4][0])
                    lc = min(0.035 * w, L * 0.3) * k
                    for lado in (-1, 1):
                        b = a + math.pi + lado * math.radians(28)
                        ponta = np.array([corpo[-1], (corpo[-1][0] + lc * math.cos(b), corpo[-1][1] + lc * math.sin(b))])
                        cor_a = np.maximum(cor_a, _alfa_traco(w, h, ponta, esp).astype(np.float32) / 255 * fade)
                        sh = ponta + (esp * 0.35, esp * 0.5)
                        som_a = np.maximum(som_a, _alfa_traco(w, h, sh, esp * 1.9).astype(np.float32) / 255 * 0.45 * fade)
                anc = (tx, ty + h * 0.02)
            if tipo != "seta":
                pts = _parcial(pts, p)
            a_tr = _alfa_traco(w, h, pts, esp).astype(np.float32) / 255
            # sombra: o mesmo traço mais grosso, deslocado e borrado — lê em foto clara ou escura
            sh = _alfa_traco(w, h, pts + (esp * 0.35, esp * 0.5), esp * 1.9)
            sh = cv2.GaussianBlur(sh, (0, 0), esp * 0.6).astype(np.float32) / 255
            cor_a = np.maximum(cor_a, a_tr * fade)
            som_a = np.maximum(som_a, sh * 0.45 * fade)
        if m.get("texto"):
            chave = ("et", m["texto"])
            if chave not in cache:
                cache[chave] = _etiqueta(m["texto"], h, cor_txt)
            k = _ease((t - ti - DESENHO - TEXTO_ATRASO + 0.35) / 0.35) * fade
            if k > 0:
                rotulos.append((cache[chave], anc, k))
    if not algo:
        return None
    out = np.zeros((h, w, 4), np.float32)
    a = cor_a + som_a * (1 - cor_a)
    with np.errstate(invalid="ignore", divide="ignore"):
        for ch, v in enumerate(cor[::-1]):  # BGR
            out[..., ch] = np.where(a > 0, v * cor_a / np.maximum(a, 1e-6), 0)
    out[..., 3] = a * 255
    img = out.astype(np.uint8)
    for et, (axp, ayp), k in rotulos:
        e = np.asarray(et).astype(np.float32)
        e = e[..., [2, 1, 0, 3]]
        e[..., 3] *= k
        x0 = int(min(max(w * 0.03, axp), w * 0.97 - e.shape[1]))
        y0 = int(min(max(h * 0.04, ayp), h * 0.94 - e.shape[0]))
        x1, y1 = x0 + e.shape[1], y0 + e.shape[0]
        if x0 < 0 or y0 < 0 or x1 > w or y1 > h:
            continue
        base = img[y0:y1, x0:x1].astype(np.float32)
        ae, ab = e[..., 3:4] / 255, base[..., 3:4] / 255
        ao = ae + ab * (1 - ae)
        cor_o = (e[..., :3] * ae + base[..., :3] * ab * (1 - ae)) / np.maximum(ao, 1e-6)
        img[y0:y1, x0:x1, :3] = cor_o.astype(np.uint8)
        img[y0:y1, x0:x1, 3] = (ao[..., 0] * 255).astype(np.uint8)
    return img


def camada(marcas_t: list[tuple[dict, float, float]], trajeto: list[tuple], w: int, h: int, fps: int, n: int,
           saida: Path) -> Path:
    """Renderiza a camada inteira (n quadros) num MOV RGBA (PNG): vazio fora das janelas."""
    saida.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen(["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "bgra", "-s", f"{w}x{h}",
                             "-r", str(fps), "-i", "-", "-c:v", "png", "-pix_fmt", "rgba", "-f", "mov", str(saida)],
                            stdin=subprocess.PIPE)
    vazio = np.zeros((h, w, 4), np.uint8).tobytes()
    cache: dict = {}
    try:
        for i in range(n):
            tr = trajeto[min(i, len(trajeto) - 1)]
            q = quadro(w, h, marcas_t, tr, i / fps, cache)
            proc.stdin.write(vazio if q is None else q.tobytes())
    finally:
        proc.stdin.close()
        if proc.wait() != 0:
            raise RuntimeError(f"ffmpeg falhou ao gravar {saida}")
    log(f"  marca: {len(marcas_t)} marcação(ões) -> {saida.name}")
    return saida


def caixas(marcas_t: list[tuple[dict, float, float]], trajeto: list[tuple], w: int, h: int, fps: int) -> list[dict]:
    """Onde cada marcação fica NA TELA (frações 0–1 do quadro), no instante em que termina de se desenhar:
    [{"ti", "tf" (s desde o 1º quadro do clipe), "caixa": [x0, y0, x1, y1], "tipo"}]. Usado pelos Shorts para o
    recorte 9:16 não cortar a marcação (montar.py grava em build/cenas/<id>_marca.json)."""
    out = []
    for m, ti, tf in marcas_t:
        i = max(0, min(len(trajeto) - 1, int(round((ti + DESENHO) * fps)))) if trajeto else 0
        sx, sy, ox, oy = trajeto[i] if trajeto else (w, h, 0.0, 0.0)
        x, y = float(m.get("x", 0.5)), float(m.get("y", 0.5))
        cx, cy = ox + x * sx, oy + y * sy
        tipo = m["tipo"]
        if tipo == "seta":
            de = m.get("de") or [x - 0.16, y + 0.2]
            tx, ty = ox + float(de[0]) * sx, oy + float(de[1]) * sy
            x0, x1, y0, y1 = min(cx, tx), max(cx, tx), min(cy, ty), max(cy, ty)
        else:
            lw = float(m.get("largura", {"circulo": 0.2, "sublinhado": 0.3, "caixa": 0.3, "foco": 0.35}[tipo])) * sx
            lh = float(m.get("altura", 0) or 0) * sy or (lw * 0.82 if tipo in ("circulo", "foco") else
                                                         0.25 * sy if tipo == "caixa" else h * 0.02)
            x0, x1, y0, y1 = cx - lw / 2, cx + lw / 2, cy - lh / 2, cy + lh / 2
        if m.get("texto"):   # etiqueta: junto do canto da marca, ~0,03·h de corpo
            x1 = max(x1, x1 + len(str(m["texto"])) * h * 0.022)
            y1 = max(y1, y1 + h * 0.06)
        out.append({"ti": round(ti, 3), "tf": round(tf, 3), "tipo": tipo,
                    "caixa": [round(max(0.0, x0 / w), 4), round(max(0.0, y0 / h), 4),
                              round(min(1.0, x1 / w), 4), round(min(1.0, y1 / h), 4)]})
    return out


def trajeto_video(midia: Path, w: int, h: int, fatores=None) -> list[tuple]:
    """Vídeo de banco: escalado para cobrir w×h e cortado no centro (montar.render_cena); punch-in central."""
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                        "-of", "csv=p=0:s=x", str(midia)], capture_output=True, text=True)
    try:
        vw, vh = (int(x) for x in r.stdout.strip().split("\n")[0].split("x")[:2])
    except ValueError:
        vw, vh = w, h
    k = max(w / vw, h / vh)
    sx, sy = vw * k, vh * k
    ox, oy = (w - sx) / 2, (h - sy) / 2
    if fatores is None:
        return [(sx, sy, ox, oy)]
    return [(sx * f, sy * f, (ox - w / 2) * f + w / 2, (oy - h / 2) * f + h / 2) for f in fatores]
