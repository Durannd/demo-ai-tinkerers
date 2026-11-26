"""Thumbnail do episódio (1280×720) a partir de meta.thumbnail e da mídia já baixada (licença registrada).

Três variações com LAYOUTS DIFERENTES, para teste A/B no YouTube:
  seta    A | B em corte diagonal, uma seta grossa desenhada à mão entre os dois; o texto vira etiquetas
          ("VULCÃO" sobre A, "BICICLETA?" sobre B — o "=" é a seta) ou um bloco grande no lado com espaço.
  heroi   o sujeito recortado (remoção de fundo, ISNet) ENORME, com contorno creme, brilho e sombra, sobre o
          outro lado da história desfocado e escurecido; texto empilhado gigante no lado vazio.
  domino  A e B como fotos inclinadas (ou recortes) sobre fundo de papel escuro, ligados por uma fileira de
          dominós caindo (a marca do canal); texto grande no topo.
Tudo com contraste/saturação puxados, vinheta e grão; paleta de tokens.domino / tokens.thumbnail do canal.

Escolha (score de clicabilidade): `candidatas` ordena as cenas por similaridade com `ideia_visual`
(+ nitidez). Cenas com `rotulo.tipo = "pessoa"` são o protagonista real e ganham prioridade de herói;
rosto genérico de banco (Haar) não divide a thumbnail com ele, e sem protagonista entra no máximo um
rosto. Sem `layouts` explícito, `heroi` abre quando há protagonista recortável. Texto >4 palavras ou
linha <80px dispara aviso (leitura no celular). Cada geração grava final/ctr_log.json (features por
variante); `--ctr-log` consolida em canais/<id>/ctr_log.csv p/ atribuir o resultado do Teste e compare.

meta.thumbnail:
  texto         até ~4 palavras, ex. "VULCÃO = BICICLETA?" — destaque: o que vem antes de = → : (ou a ÚLTIMA palavra)
  ideia_visual  descrição livre; uma frase por elemento ("À esquerda, ...". "À direita, ..."): escolhe as cenas
  cenas         opcional: ["c12", "c43"] força A e B (a 1ª é a causa/esquerda)
  destaque      opcional: palavra(s) do texto que saem na cor de destaque (substitui a regra automática)
  sujeito       opcional: cena cujo objeto é recortado no layout "heroi" (padrão: o melhor recorte entre A e B)
  marcacao      opcional: {"cena": "c43", "x": 0.62, "y": 0.70, "raio": 0.12} — círculo vermelho à mão
                em volta de um detalhe (x, y, raio em fração da imagem ORIGINAL da cena)
  layouts       opcional: ordem/escolha das variações, ex. ["heroi", "seta", "domino"] (a 1ª vira thumbnail.jpg)

Gera <saida>/thumbnail_1..3.jpg, thumbnail.jpg (= a 1ª) e thumbnail_previa.jpg (as três em 320×180 e
168×94, para conferir a leitura em tamanho de celular). <saida> padrão: final/. Imagens CC BY usadas aqui já
têm crédito na descrição, porque vêm das cenas do vídeo.

Recorte: modelo ISNet (DIS, Apache 2.0, ONNX ~170 MB, baixado na 1ª vez para assets/modelos/), roda na CPU
pelo onnxruntime que já existe (sem rembg). Sem o modelo, os layouts usam fotos emolduradas no lugar do recorte.

Fundo por IA local (--fundo-local, desligado por padrão): gera um fundo SEM TEXTO com o modelo de imagem local
(pipeline/ia_local.py, Flux 2 Klein 4B na GPU, ~1 min) a partir de --prompt-fundo (ou de ideia_visual), sem rosto
de pessoa real; ele vira o fundo dos layouts heroi/domino. Fica em final/thumbnail_fundo_ia.png (reaproveitado).

Uso: python pipeline/thumbnail.py <slug> [--cenas c12,c50] [--saida pasta] [--fundo-local [--prompt-fundo "..."]]
"""
from __future__ import annotations

import argparse
import csv
import math
import random
import re
import subprocess
import time
import unicodedata
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps

from common import RAIZ, baixar, duracao, ler_json, ler_storyboard, log, pasta_episodio, salvar_json
from estilo import tokens

W, H = 1280, 720
EXT_IMG = {".jpg", ".jpeg", ".png", ".webp"}
EXT_VID = {".mp4", ".webm", ".mov"}
TIPOS_MIDIA = {"stock_video", "stock_imagem", "arquivo_historico", "ia_imagem", "ia_video", "local"}
LAYOUTS = ("seta", "heroi", "domino")
OPERADORES = {"=", "→", ":", "->", "+", "VS", "X"}

MODELO_RECORTE = RAIZ / "assets" / "modelos" / "isnet-general-use.onnx"
URL_RECORTE = "https://github.com/danielgatis/rembg/releases/download/v0.0.0/isnet-general-use.onnx"


# ───────────────────────────── paleta e fonte ─────────────────────────────

def _rgb(hexa: str) -> tuple:
    h = hexa.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in range(0, 6, 2))


def paleta() -> dict:
    """escuro/claro/acento/ouro do canal: tokens.thumbnail > tokens.domino > tokens.cores."""
    tk = tokens()
    th, dom, cor = tk.get("thumbnail") or {}, tk.get("domino") or {}, tk.get("cores") or {}

    def pega(*opcoes, padrao):
        for o in opcoes:
            if o:
                return _rgb(o)
        return _rgb(padrao)
    return {
        "escuro": pega(th.get("escuro"), dom.get("fundo"), cor.get("tinta"), padrao="#0E0E10"),
        "claro": pega(th.get("claro"), dom.get("marfim"), cor.get("texto"), padrao="#F2E8D5"),
        "acento": pega(th.get("acento"), dom.get("tijolo"), cor.get("destaque"), padrao="#C8432B"),
        "ouro": pega(th.get("ouro"), dom.get("ouro"), cor.get("secundaria"), padrao="#C9A55C"),
        "tinta": pega(dom.get("tinta"), cor.get("tinta"), padrao="#1C1813"),
    }


def fonte_thumb(tam: int) -> ImageFont.FreeTypeFont:
    tk = tokens()
    rel = (tk.get("thumbnail") or {}).get("fonte") or tk["fontes"]["rotulo_forte"]
    return ImageFont.truetype(str(RAIZ / rel), max(8, int(tam)))


# ───────────────────────────── escolha das cenas (igual à versão anterior) ─────────────────────────────

def norm(s: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFD", (s or "").lower()) if ch.isalnum() or ch == " ")


VAZIAS = {"quase", "sobre", "fundo", "dois", "duas", "tons", "esquer", "direit", "contra", "alto", "muito",
          "entre", "como", "para", "pelo", "pela", "com", "cada", "mais", "menos", "outro", "outra", "lado",
          "imagem", "image", "foto", "visual", "tela", "centro", "meio", "frente", "atras", "caindo", "fileir",
          # en
          "left", "right", "with", "from", "about", "behind", "front", "photo", "background", "center", "middle",
          "over", "under", "into", "side", "each", "other", "showing"}


def palavras(s: str) -> set[str]:
    return {w[:6] for w in norm(s).split() if len(w) >= 4 and w[:6] not in VAZIAS}


def midia_da_cena(ep: Path, cid: str) -> Path | None:
    for p in sorted((ep / "midia").glob(f"{cid}.*")):
        if p.suffix.lower() in EXT_IMG | EXT_VID:
            return p
    return None


def quadro(ep: Path, arq: Path) -> Image.Image:
    """Imagem: ela mesma. Vídeo: o quadro mais nítido entre 5 amostras."""
    if arq.suffix.lower() in EXT_IMG:
        return ImageOps.exif_transpose(Image.open(arq)).convert("RGB")
    import cv2
    (ep / "build").mkdir(exist_ok=True)
    dur = max(1.0, duracao(arq))
    melhor, nota = None, -1.0
    for k in range(5):
        t = dur * (0.15 + 0.17 * k)
        tmp = ep / "build" / f"_thumb_{arq.stem}_{k}.png"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{t:.2f}", "-i", str(arq), "-frames:v", "1", str(tmp)])
        if not tmp.exists():
            continue
        img = cv2.imread(str(tmp))
        n = cv2.Laplacian(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), cv2.CV_64F).var() if img is not None else 0
        if n > nota:
            melhor, nota = tmp, n
    if melhor is None:
        raise RuntimeError(f"não consegui extrair quadro de {arq.name}")
    with Image.open(melhor) as im:
        return im.convert("RGB")


def cenas_com_midia(ep: Path, sb: dict) -> list[tuple[int, dict, Path]]:
    out = []
    for i, c in enumerate(sb["cenas"]):
        if c["visual"]["tipo"] not in TIPOS_MIDIA:
            continue
        arq = midia_da_cena(ep, c["id"])
        if not arq:
            continue
        if arq.suffix.lower() in EXT_IMG:
            try:
                with Image.open(arq) as im:
                    if min(im.size) < 500:
                        continue
            except Exception:
                continue
        out.append((i, c, arq))
    return out


def candidatas(ep: Path, sb: dict) -> list[tuple[float, str, Path]]:
    """Uma cena por frase da ideia visual ("À esquerda, a erupção..." / "À direita, a máquina..."),
    sem repetir cena; depois as demais pela semelhança geral. Gancho ganha um empurrão no desempate."""
    ideia = (sb["meta"].get("thumbnail") or {}).get("ideia_visual", "")
    frases = [palavras(f) for f in re.split(r"[.;]|entre", ideia, flags=re.I) if palavras(f)]
    cenas = cenas_com_midia(ep, sb)

    textos = {c["id"]: palavras(c["narracao"] + " " + (c.get("rotulo") or {}).get("texto", "")) for c in sb["cenas"]}
    df = {}
    for ws in textos.values():
        for w in ws:
            df[w] = df.get(w, 0) + 1

    def nota(alvo: set, i: int, c: dict) -> float:
        # palavra rara no roteiro ("Laufmaschine") vale mais que palavra que aparece em toda parte
        n = sum(3 / df.get(w, 1) ** 0.5 for w in alvo & textos[c["id"]])
        return n + (0.5 if c.get("bloco") == "gancho" else 0) - i * 0.002

    escolhidas, usadas = [], set()
    for alvo in frases:
        melhor = max(((nota(alvo, i, c), c["id"], arq) for i, c, arq in cenas if c["id"] not in usadas),
                     default=None, key=lambda x: x[0])
        if melhor and melhor[0] >= 1:
            escolhidas.append(melhor)
            usadas.add(melhor[1])
    geral = set().union(*frases) if frases else set()
    resto = sorted(((nota(geral, i, c), c["id"], arq) for i, c, arq in cenas if c["id"] not in usadas),
                   key=lambda x: -x[0])
    return escolhidas + resto


# ───────────────────────────── imagem: realce, encaixe, recorte ─────────────────────────────

def realcar(img: Image.Image, forca: float = 1.0) -> Image.Image:
    """Contraste e saturação puxados + nitidez (thumbnail é vista pequena)."""
    img = ImageOps.autocontrast(img, cutoff=(0.6, 0.6))
    img = ImageEnhance.Contrast(img).enhance(1 + 0.18 * forca)
    img = ImageEnhance.Color(img).enhance(1 + 0.3 * forca)
    return img.filter(ImageFilter.UnsharpMask(radius=2, percent=int(70 * forca), threshold=2))


def encaixar(img: Image.Image, w: int, h: int, centro: tuple[float, float] = (0.5, 0.45)):
    """Recorta/escala a imagem para (w, h) mirando `centro` (fração). Devolve (imagem, escala, x0, y0) para
    converter coordenadas da imagem original: x_quadro = x_orig * escala - x0."""
    s = max(w / img.width, h / img.height)
    nw, nh = max(w, round(img.width * s)), max(h, round(img.height * s))
    x0 = int(min(max(centro[0] * nw - w / 2, 0), nw - w))
    y0 = int(min(max(centro[1] * nh - h / 2, 0), nh - h))
    return img.resize((nw, nh), Image.LANCZOS).crop((x0, y0, x0 + w, y0 + h)), s, x0, y0


@lru_cache(maxsize=1)
def _sessao_recorte():
    import onnxruntime as ort
    if not MODELO_RECORTE.exists():
        log("  thumbnail: baixando modelo de recorte ISNet (~170 MB, Apache 2.0)...")
        tmp = MODELO_RECORTE.with_suffix(".parcial")
        try:
            baixar(URL_RECORTE, tmp)
            tmp.replace(MODELO_RECORTE)
        except Exception:
            tmp.unlink(missing_ok=True)
            _sessao_falhou.append(True)
            raise
    # CPU: ~2 s por imagem e não disputa a GPU com render/IA local
    return ort.InferenceSession(str(MODELO_RECORTE), providers=["CPUExecutionProvider"])


_sessao_falhou: list = []   # download do modelo falhou nesta execução: não tenta de novo a cada imagem


class Midia:
    """Uma cena usada na thumbnail: quadro, máscara do objeto principal e nota do recorte."""

    def __init__(self, cid: str, img: Image.Image):
        self.cid, self.img = cid, img
        self.mascara: Image.Image | None = None
        self.bbox: tuple[int, int, int, int] | None = None
        self.nota = 0.0
        self.centro = (0.5, 0.45)
        self.toca_base = False
        self.pessoa = False   # rotulo.tipo == "pessoa" no storyboard = protagonista real
        self.rosto = False    # rosto detectado na imagem (pessoa OU humano genérico de banco)
        try:
            self._recortar()
        except Exception as e:
            log(f"  thumbnail: recorte indisponível para {cid} ({e})")

    def _recortar(self) -> None:
        import cv2
        if _sessao_falhou:
            return
        s = _sessao_recorte()
        x = np.asarray(self.img.resize((1024, 1024), Image.BILINEAR), dtype=np.float32)
        x = x / max(float(x.max()), 1e-6) - np.array([0.485, 0.456, 0.406], dtype=np.float32)
        y = s.run(None, {s.get_inputs()[0].name: x.transpose(2, 0, 1)[None]})[0][0, 0]
        y = (y - y.min()) / max(1e-6, float(y.max() - y.min()))
        m = np.asarray(Image.fromarray((y * 255).astype(np.uint8)).resize(self.img.size, Image.BILINEAR),
                       dtype=np.float32) / 255
        cru = (m > 0.5).astype(np.uint8)
        ab = max(3, int(0.006 * max(self.img.size)) | 1)  # abertura só para ESCOLHER as peças (fiapos não contam)
        bin_ = cv2.morphologyEx(cru, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (ab, ab)))
        n, rot, est, _ = cv2.connectedComponentsWithStats(bin_, connectivity=8)
        if n <= 1:
            return
        areas = est[1:, cv2.CC_STAT_AREA]
        maior = int(areas.max())
        # o objeto = a maior peça + as que encostam nela (roda solta); some o que está longe (2º desenho, grade)
        r = max(5, int(0.025 * max(self.img.size)))
        perto = cv2.dilate((rot == 1 + int(areas.argmax())).astype(np.uint8),
                           cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1)))
        ids = [k for k in range(1, n) if est[k, cv2.CC_STAT_AREA] >= maior * 0.03 and (perto[rot == k]).any()]
        escolhidas = np.isin(rot, ids)
        # devolve os detalhes finos (raios da roda) que a abertura tirou: peças do cru que tocam as escolhidas
        n2, rot2 = cv2.connectedComponents(cru, connectivity=8)
        ids2 = np.unique(rot2[escolhidas])
        manter = np.isin(rot2, ids2[ids2 > 0]).astype(np.uint8)
        manter = cv2.dilate(manter, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9)))
        areas = est[ids, cv2.CC_STAT_AREA] if len(ids) else areas
        alfa = np.clip((m - 0.12) / 0.76, 0, 1) * manter
        area = float((alfa > 0.5).mean())
        partilha = int(areas.sum()) / max(1, int(bin_.sum()))
        incerto = float(((m > 0.15) & (m < 0.85)).mean()) / max(area, 0.02)
        ys, xs = np.where(alfa > 0.5)
        if len(xs) == 0:
            return
        x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
        bh, bw = y1 - y0 + 1, x1 - x0 + 1
        bordas = sum([x0 <= 2, y0 <= 2, x1 >= self.img.width - 3, y1 >= self.img.height - 3])
        nota = 1.0
        nota *= 1.0 if 0.04 <= area <= 0.6 else 0.4
        nota *= min(1.0, partilha / 0.8) ** 2
        nota *= max(0.2, 1 - max(0.0, incerto - 0.25) * 2)
        nota *= 1.0 if bordas <= 2 else 0.35            # encosta em 3–4 bordas: é paisagem, não objeto
        nota *= min(1.0, max(bh, bw) / 520) ** 0.7       # objeto pequeno demais vira borrão ampliado
        self.nota = round(nota, 2)
        self.mascara = Image.fromarray((alfa * 255).astype(np.uint8), "L")
        self.bbox = (int(x0), int(y0), int(x1) + 1, int(y1) + 1)
        self.centro = (float(xs.mean()) / self.img.width, float(ys.mean()) / self.img.height)
        self.toca_base = y1 >= self.img.height - 3

    @property
    def recortavel(self) -> bool:
        return self.mascara is not None and self.nota >= 0.45

    def recorte(self) -> Image.Image:
        """RGBA só do objeto, cortado na caixa dele (com folga)."""
        x0, y0, x1, y1 = self.bbox
        f = int(0.02 * max(self.img.size))
        caixa = (max(0, x0 - f), max(0, y0 - f), min(self.img.width, x1 + f), min(self.img.height, y1 + f))
        rgba = realcar(self.img, 1.1).convert("RGBA")
        rgba.putalpha(self.mascara)
        return rgba.crop(caixa)


MODELO_ROSTO = RAIZ / "assets" / "modelos" / "face_detection_yunet_2023mar.onnx"
URL_ROSTO = ("https://github.com/opencv/opencv_zoo/raw/main/models/"
             "face_detection_yunet/face_detection_yunet_2023mar.onnx")


@lru_cache(maxsize=1)
def _detector_rosto():
    """YuNet (ONNX ~230 KB, MIT, baixado na 1ª vez) — detecta rosto frontal e de perfil.
    Sem modelo/cv2: devolve None e a regra anti-genérico fica desligada (degrada graciosamente)."""
    import cv2
    if not hasattr(cv2, "FaceDetectorYN"):
        return None
    if not MODELO_ROSTO.exists():
        log("  thumbnail: baixando detector de rosto YuNet (~230 KB, MIT)...")
        tmp = MODELO_ROSTO.with_suffix(".parcial")
        try:
            baixar(URL_ROSTO, tmp)
            tmp.replace(MODELO_ROSTO)
        except Exception:
            tmp.unlink(missing_ok=True)
            return None
    return cv2.FaceDetectorYN.create(str(MODELO_ROSTO), "", (640, 640), score_threshold=0.85)


def _tem_rosto(img: Image.Image) -> bool:
    """Há rosto na imagem? Rosto genérico (banco de imagem) NÃO divide a thumbnail com o real."""
    det = _detector_rosto()
    if det is None:
        return False
    import cv2
    im = img.resize((640, max(1, int(img.height * 640 / img.width))))
    det.setInputSize(im.size)
    _, faces = det.detect(cv2.cvtColor(np.asarray(im), cv2.COLOR_RGB2BGR))
    return faces is not None and len(faces) > 0


# ───────────────────────────── efeitos de acabamento ─────────────────────────────

def grao(img: Image.Image, forca: float = 7.0, seed: int = 7) -> Image.Image:
    rng = np.random.default_rng(seed)
    a = np.asarray(img.convert("RGB"), dtype=np.float32)
    a += rng.normal(0, forca, a.shape[:2])[..., None]
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))


def vinheta(img: Image.Image, forca: float = 0.55, cx: float = 0.5, cy: float = 0.5) -> Image.Image:
    yy, xx = np.mgrid[0:img.height, 0:img.width].astype(np.float32)
    d = np.sqrt(((xx / img.width - cx) / 0.75) ** 2 + ((yy / img.height - cy) / 0.75) ** 2)
    f = 1 - forca * np.clip(d - 0.25, 0, 1) ** 1.6
    a = np.asarray(img.convert("RGB"), dtype=np.float32) * f[..., None]
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))


def tingir(img: Image.Image, escuro: tuple, cor: tuple, mistura: float = 0.55) -> Image.Image:
    """Duotone parcial: sombras vão para `escuro`, luzes para `cor` (fundo de layout)."""
    cinza = ImageOps.grayscale(img)
    duo = ImageOps.colorize(cinza, escuro, cor)
    return Image.blend(img.convert("RGB"), duo, mistura)


def fundo_papel(cor: tuple, luz: tuple = (0.5, 0.42), seed: int = 3, cor_luz: tuple | None = None) -> Image.Image:
    """Fundo escuro com textura de papel (ruído de baixa frequência) e um foco de luz."""
    rng = np.random.default_rng(seed)
    baixo = np.asarray(Image.fromarray((rng.random((H // 40, W // 40)) * 255).astype(np.uint8))
                       .resize((W, H), Image.BICUBIC), dtype=np.float32) / 255 - 0.5
    fibras = np.asarray(Image.fromarray((rng.random((H // 3, W // 3)) * 255).astype(np.uint8))
                        .resize((W, H), Image.BICUBIC), dtype=np.float32) / 255 - 0.5
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    foco = np.exp(-(((xx / W - luz[0]) / 0.42) ** 2 + ((yy / H - luz[1]) / 0.5) ** 2))
    base = np.array(cor, dtype=np.float32)[None, None]
    if cor_luz:  # foco de luz colorido (ex.: brilho na cor de destaque atrás do objeto)
        a = base + foco[..., None] * np.array(cor_luz, dtype=np.float32)[None, None] * 0.55
    else:
        a = base * (1 + 1.6 * foco[..., None])
    a = a + (baixo * 16 + fibras * 7)[..., None]
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))


def _dilatar(alfa: Image.Image, r: int) -> Image.Image:
    import cv2
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1))
    return Image.fromarray(cv2.dilate(np.asarray(alfa), k))


def colar_adesivo(can: Image.Image, obj: Image.Image, xy: tuple[int, int], pal: dict,
                  borda: int = 9, brilho: bool = True) -> None:
    """Cola um RGBA recortado com contorno creme, brilho na cor de destaque e sombra projetada."""
    m = max(borda * 4, 40)
    alfa = Image.new("L", (obj.width + 2 * m, obj.height + 2 * m))
    alfa.paste(obj.getchannel("A"), (m, m))
    alfa = alfa.point(lambda v: 255 if v > 110 else int(v * 2.3))
    contorno = _dilatar(alfa, borda).filter(ImageFilter.GaussianBlur(1.2))
    x, y = xy[0] - m, xy[1] - m
    camada = Image.new("RGBA", can.size, (0, 0, 0, 0))
    sombra = Image.new("RGBA", contorno.size, (0, 0, 0, 0))
    sombra.putalpha(contorno.filter(ImageFilter.GaussianBlur(14)).point(lambda v: int(v * 0.8)))
    _colar(camada, sombra, x + 14, y + 18)
    if brilho:
        g = Image.new("RGBA", contorno.size, pal["acento"] + (0,))
        g.putalpha(_dilatar(contorno, 10).filter(ImageFilter.GaussianBlur(20)).point(lambda v: int(v * 0.85)))
        _colar(camada, g, x, y)
    c = Image.new("RGBA", contorno.size, pal["claro"] + (0,))
    c.putalpha(contorno)
    _colar(camada, c, x, y)
    _colar(camada, obj, xy[0], xy[1])
    base = can.convert("RGBA")
    base.alpha_composite(camada)
    can.paste(base.convert("RGB"))


def _colar(dest: Image.Image, src: Image.Image, x: int, y: int) -> None:
    """alpha_composite aceitando posição negativa/fora do quadro."""
    sx0, sy0 = max(0, -x), max(0, -y)
    dx0, dy0 = max(0, x), max(0, y)
    w = min(src.width - sx0, dest.width - dx0)
    h = min(src.height - sy0, dest.height - dy0)
    if w > 0 and h > 0:
        dest.alpha_composite(src.crop((sx0, sy0, sx0 + w, sy0 + h)), (dx0, dy0))


def foto_moldura(img: Image.Image, w: int, h: int, pal: dict, angulo: float, centro=(0.5, 0.45),
                 borda: int = 12) -> Image.Image:
    """Foto com moldura creme, inclinada, com sombra (RGBA)."""
    f, *_ = encaixar(realcar(img), w, h, centro)
    card = Image.new("RGBA", (w + 2 * borda, h + 2 * borda), pal["claro"] + (255,))
    card.paste(f, (borda, borda))
    card = card.rotate(angulo, Image.BICUBIC, expand=True)
    m = 40
    out = Image.new("RGBA", (card.width + 2 * m, card.height + 2 * m), (0, 0, 0, 0))
    sombra = Image.new("RGBA", card.size, (0, 0, 0, 0))
    sombra.putalpha(card.getchannel("A").point(lambda v: int(v * 0.75)))
    out.alpha_composite(sombra, (m + 12, m + 16))
    out = out.filter(ImageFilter.GaussianBlur(10))
    out.alpha_composite(card, (m, m))
    return out


# ───────────────────────────── desenho: seta, círculo, dominós ─────────────────────────────

SS = 2  # supersampling dos vetores


def _bezier(p0, p1, p2, n=60):
    return [((1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t ** 2 * p2[0],
             (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t ** 2 * p2[1]) for t in (i / n for i in range(n + 1))]


def seta(can: Image.Image, p0, p2, curva: float, largura: float, pal: dict, cor=None) -> None:
    """Seta grossa curva, estilo marcador: corpo afinando no início, ponta larga, contorno escuro."""
    cor = cor or pal["acento"]
    p0 = (p0[0] * SS, p0[1] * SS)
    p2 = (p2[0] * SS, p2[1] * SS)
    lg = largura * SS
    mx, my = (p0[0] + p2[0]) / 2, (p0[1] + p2[1]) / 2
    dx, dy = p2[0] - p0[0], p2[1] - p0[1]
    dist = math.hypot(dx, dy)
    nx, ny = -dy / dist, dx / dist
    p1 = (mx + nx * curva * dist, my + ny * curva * dist)
    cab = lg * 2.3
    pts = _bezier(p0, p1, p2)
    # corta a curva antes da ponta
    corpo = [p for p in pts if math.hypot(p[0] - p2[0], p[1] - p2[1]) > cab * 0.9]
    esq, dir_ = [], []
    for i, p in enumerate(corpo):
        q = corpo[min(i + 1, len(corpo) - 1)] if i < len(corpo) - 1 else p
        r = corpo[i - 1] if i else p
        tx, ty = q[0] - r[0], q[1] - r[1]
        tn = math.hypot(tx, ty) or 1
        ox, oy = -ty / tn, tx / tn
        meia = lg * (0.28 + 0.22 * i / max(1, len(corpo) - 1))
        esq.append((p[0] + ox * meia, p[1] + oy * meia))
        dir_.append((p[0] - ox * meia, p[1] - oy * meia))
    b = corpo[-1]
    tx, ty = p2[0] - b[0], p2[1] - b[1]
    tn = math.hypot(tx, ty) or 1
    ux, uy = tx / tn, ty / tn
    ox, oy = -uy, ux
    ponta = [(b[0] + ox * cab * 0.62, b[1] + oy * cab * 0.62), (p2[0] + ux * cab * 0.25, p2[1] + uy * cab * 0.25),
             (b[0] - ox * cab * 0.62, b[1] - oy * cab * 0.62)]
    poly = esq + [ponta[0], ponta[1], ponta[2]] + dir_[::-1]
    _vetor(can, lambda d, c: d.polygon(poly, fill=c), cor, pal, contorno=int(lg * 0.16))


def circulo_mao(can: Image.Image, cx: float, cy: float, rx: float, ry: float, pal: dict, esp: int = 9) -> None:
    """Círculo vermelho "feito à mão": 1,15 volta com raio irregular."""
    rnd = random.Random(int(cx * 7 + cy * 13))
    fase = rnd.random() * 6.28
    pts = []
    n = 90
    for i in range(int(n * 1.15)):
        a = fase + 2 * math.pi * i / n
        k = 1 + 0.06 * math.sin(3 * a + fase) + 0.04 * (i / n)
        pts.append(((cx + rx * k * math.cos(a)) * SS, (cy + ry * k * math.sin(a)) * SS))
    _vetor(can, lambda d, c: d.line(pts, fill=c, width=esp * SS, joint="curve"), pal["acento"], pal,
           contorno=int(esp * SS * 0.45))


def _vetor(can: Image.Image, desenha, cor, pal: dict, contorno: int = 0) -> None:
    """Desenha numa camada 2× (antisserrilhado), com contorno escuro e sombra, e compõe no quadro."""
    m = Image.new("L", (can.width * SS, can.height * SS))
    desenha(ImageDraw.Draw(m), 255)
    camada = Image.new("RGBA", m.size, (0, 0, 0, 0))
    if contorno:
        borda = _dilatar(m, contorno)
        sombra = Image.new("RGBA", m.size, (0, 0, 0, 0))
        sombra.putalpha(borda.filter(ImageFilter.GaussianBlur(10 * SS)).point(lambda v: int(v * 0.7)))
        camada.alpha_composite(sombra, (8 * SS, 10 * SS))
        e = Image.new("RGBA", m.size, pal["tinta"] + (0,))
        e.putalpha(borda)
        camada.alpha_composite(e)
    c = Image.new("RGBA", m.size, tuple(cor) + (0,))
    c.putalpha(m)
    camada.alpha_composite(c)
    base = can.convert("RGBA")
    base.alpha_composite(camada.resize(can.size, Image.LANCZOS))
    can.paste(base.convert("RGB"))


def _peca_domino(tw: int, th: int, pal: dict, primeira: bool) -> Image.Image:
    """Uma peça (RGBA) em pé: marfim com pontos escuros; a 1ª na cor de destaque (o gatilho)."""
    s = SS
    im = Image.new("RGBA", (tw * s, th * s), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    corpo = pal["acento"] if primeira else pal["claro"]
    ponto = pal["claro"] if primeira else pal["tinta"]
    d.rounded_rectangle((0, 0, tw * s - 1, th * s - 1), radius=int(tw * s * 0.16), fill=pal["tinta"])
    e = max(2, int(tw * s * 0.07))
    d.rounded_rectangle((e, e, tw * s - 1 - e, th * s - 1 - e), radius=int(tw * s * 0.12), fill=corpo)
    d.line((tw * s * 0.2, th * s / 2, tw * s * 0.8, th * s / 2), fill=ponto, width=max(2, int(tw * s * 0.05)))
    r = tw * s * 0.085
    for (fx, fy) in [(0.3, 0.13), (0.7, 0.37), (0.5, 0.25), (0.3, 0.63), (0.7, 0.63), (0.3, 0.87), (0.7, 0.87)]:
        d.ellipse((fx * tw * s - r, fy * th * s - r, fx * tw * s + r, fy * th * s + r), fill=ponto)
    return im.resize((tw, th), Image.LANCZOS)


def domino(can: Image.Image, x0: float, x1: float, chao: float, pal: dict, alt: int = 120) -> None:
    """Fileira de dominós caindo da esquerda para a direita (as primeiras já tombadas)."""
    tw = int(alt * 0.5)
    camada = Image.new("RGBA", can.size, (0, 0, 0, 0))
    # sombra no chão
    sb = Image.new("L", can.size)
    ImageDraw.Draw(sb).ellipse((x0 - 20, chao - 14, x1 + tw + 20, chao + 18), fill=170)
    sombra = Image.new("RGBA", can.size, (0, 0, 0, 0))
    sombra.putalpha(sb.filter(ImageFilter.GaussianBlur(14)))
    camada.alpha_composite(sombra)
    passo = alt * 0.62
    n = max(3, int((x1 - x0 - tw) / passo) + 1)
    angulos = [66, 47, 24]                                # as primeiras tombando, apoiadas na seguinte
    for i in range(n):
        ang = angulos[i] if i < len(angulos) else 0.0
        peca = _peca_domino(tw, alt, pal, i == 0)
        lado = 2 * alt + tw
        tela = Image.new("RGBA", (lado, lado), (0, 0, 0, 0))
        cx = cy = lado // 2
        tela.alpha_composite(peca, (cx - tw, cy - alt))  # canto inferior direito no centro (pivô)
        tela = tela.rotate(-ang, Image.BICUBIC, center=(cx, cy))
        px, py = int(x0 + i * passo + tw), int(chao)
        _colar(camada, tela, px - cx, py - cy)
    base = can.convert("RGBA")
    base.alpha_composite(camada)
    can.paste(base.convert("RGB"))


# ───────────────────────────── texto ─────────────────────────────

def segmentos(texto: str, destaque: str | None) -> list[tuple[str, bool]]:
    """Palavras do texto (operador colado na palavra seguinte) e se vão em destaque."""
    ws = texto.strip().upper().replace("->", "→").split()
    alvo = {norm(w) for w in (destaque or "").upper().split()}
    op = next((i for i, w in enumerate(ws) if w in OPERADORES or (w.endswith(":") and i < len(ws) - 1)), None)
    segs: list[tuple[str, bool]] = []
    for i, w in enumerate(ws):
        if alvo:
            dest = norm(w) in alvo
        elif op is not None:
            dest = i < op or (w.endswith(":") and i == op)
        else:
            dest = i == len(ws) - 1
        segs.append((w, dest))
    # junta operador isolado à palavra seguinte ("=" + "BICICLETA?")
    out = []
    i = 0
    while i < len(segs):
        w, d = segs[i]
        if w in OPERADORES and i + 1 < len(segs):
            out.append((f"{w} {segs[i + 1][0]}", segs[i + 1][1]))
            i += 2
            continue
        out.append((w, d))
        i += 1
    return out


def dividir_operador(texto: str) -> tuple[str, str] | None:
    """'VULCÃO = BICICLETA?' → ('VULCÃO', 'BICICLETA?'); sem operador → None."""
    m = re.match(r"^\s*(.+?)\s*(?:=|→|->|:|\bVS\.?\b|\bX\b)\s*(.+)$", texto.strip(), flags=re.I)
    return (m.group(1).upper(), m.group(2).upper()) if m else None


def _palavra(w: str, tam: int, destaque: bool, pal: dict, cor=None) -> tuple[Image.Image, int]:
    """Uma palavra renderizada (RGBA) e a linha de base dentro dela."""
    f = fonte_thumb(tam)
    asc, desc = f.getmetrics()
    sw = max(3, tam // 11)
    som = max(3, tam // 15)
    pad = sw + som + 4
    tem_seta = "→" in w
    texto_w = w.replace("→", "")
    larg = int(f.getlength(texto_w)) + (int(tam * 0.9) if tem_seta else 0)
    if destaque:
        bx, by = int(tam * 0.16), int(tam * 0.06)
        im = Image.new("RGBA", (larg + 2 * bx + 2 * pad, asc + desc + 2 * by + 2 * pad), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        topo = pad + int(asc * 0.16)
        x0, y0, x1, y1 = pad, topo - by, pad + larg + 2 * bx, pad + asc + by
        incl = int(tam * 0.06)
        d.polygon([(x0 + incl + som, y0 + som), (x1 + som, y0 + som), (x1 - incl + som, y1 + som), (x0 + som, y1 + som)],
                  fill=pal["tinta"])
        d.polygon([(x0 + incl, y0), (x1, y0), (x1 - incl, y1), (x0, y1)], fill=cor or pal["acento"])
        d.text((pad + bx, pad + asc), texto_w, font=f, anchor="ls", fill=pal["claro"],
               stroke_width=max(2, tam // 30), stroke_fill=pal["tinta"])
        return im, pad + asc
    im = Image.new("RGBA", (larg + 2 * pad, asc + desc + 2 * pad), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    x = pad
    if tem_seta:  # nenhuma das fontes tem →: desenha
        cy, e, w_ = pad + asc * 0.6, max(6, tam * 0.2), tam * 0.85
        pts = [(x, cy - e / 2), (x + w_ * 0.5, cy - e / 2), (x + w_ * 0.5, cy - e * 1.4), (x + w_, cy),
               (x + w_ * 0.5, cy + e * 1.4), (x + w_ * 0.5, cy + e / 2), (x, cy + e / 2)]
        for dx, dy, c in ((som, som, (0, 0, 0, 200)), (0, 0, None)):
            d.polygon([(px + dx, py + dy) for px, py in pts], fill=c or (cor or pal["claro"]),
                      outline=pal["tinta"], width=sw if c is None else 0)
        x += int(tam * 0.9)
    d.text((x + som, pad + asc + som), texto_w, font=f, anchor="ls", fill=(0, 0, 0, 210),
           stroke_width=sw, stroke_fill=(0, 0, 0, 210))
    d.text((x, pad + asc), texto_w, font=f, anchor="ls", fill=cor or pal["claro"],
           stroke_width=sw, stroke_fill=pal["tinta"])
    return im, pad + asc


def _particoes(n: int, max_linhas: int):
    """Todas as divisões de n itens em 1..max_linhas linhas contíguas."""
    for k in range(1, min(n, max_linhas) + 1):
        for cortes in _combinacoes(range(1, n), k - 1):
            b = [0, *cortes, n]
            yield [(b[i], b[i + 1]) for i in range(k)]


def _combinacoes(it, k):
    from itertools import combinations
    return combinations(it, k)


def _linha(segs: list[tuple[str, bool]], tam: int, pal: dict) -> Image.Image:
    """Uma linha de palavras (RGBA), cortada no que foi desenhado."""
    ims = [_palavra(w, tam, d, pal) for w, d in segs]
    gap = int(tam * 0.02)
    base = max(b for _, b in ims)
    desc = max(im.height - b for im, b in ims)
    ln = Image.new("RGBA", (sum(im.width for im, _ in ims) + gap * (len(ims) - 1), base + desc), (0, 0, 0, 0))
    x = 0
    for im, b in ims:
        ln.alpha_composite(im, (x, base - b))
        x += im.width + gap
    return ln.crop(ln.getbbox() or (0, 0, 1, 1))


def bloco_texto(segs: list[tuple[str, bool]], larg: int, alt: int, pal: dict, alinhar: str = "esq",
                angulo: float = 0.0, max_linhas: int = 3, tam_max: int = 230, justificar: bool = True,
                k_max: float = 1.7) -> Image.Image:
    """Maior bloco de texto que cabe em (larg, alt). Testa todas as quebras de linha; com `justificar`, cada
    linha cresce até a largura da mais longa (palavra curta fica maior, estilo cartaz)."""
    ref = 100
    cache: dict = {}

    def med(i, j):
        if (i, j) not in cache:
            cache[(i, j)] = _linha(segs[i:j], ref, pal).size
        return cache[(i, j)]
    rad = math.radians(abs(angulo))
    melhor = None
    for part in _particoes(len(segs), max_linhas):
        ws = [med(i, j) for i, j in part]
        mw = max(w for w, _ in ws)
        ks = [min(k_max, mw / w) if justificar else 1.0 for w, _ in ws]
        gap = ref * 0.06
        bw = max(w * k for (w, _), k in zip(ws, ks))
        bh = sum(h * k for (_, h), k in zip(ws, ks)) + gap * (len(part) - 1)
        s = min(larg / (bw * math.cos(rad) + bh * math.sin(rad)), alt / (bh * math.cos(rad) + bw * math.sin(rad)))
        s = min(s, tam_max / (ref * max(ks)))
        nota = (min(ref * s * k for k in ks), -len(part))
        if melhor is None or nota > melhor[0]:
            melhor = (nota, part, s, ks)
    _, part, s, ks = melhor
    # menor linha em px finais — checagem de legibilidade (a 168 px de largura, ~8× menor)
    bloco_texto.min_linha = min(getattr(bloco_texto, "min_linha", 10 ** 9), int(ref * s * min(ks)))
    linhas = [_linha(segs[i:j], int(ref * s * k), pal) for (i, j), k in zip(part, ks)]
    gap = int(ref * s * 0.06)
    bw = max(ln.width for ln in linhas)
    bloco = Image.new("RGBA", (bw, sum(ln.height for ln in linhas) + gap * (len(linhas) - 1)), (0, 0, 0, 0))
    y = 0
    for ln in linhas:
        x = {"esq": 0, "centro": (bw - ln.width) // 2, "dir": bw - ln.width}[alinhar]
        bloco.alpha_composite(ln, (x, y))
        y += ln.height + gap
    if angulo:
        bloco = bloco.rotate(angulo, Image.BICUBIC, expand=True)
    return bloco


def colar_bloco(can: Image.Image, bloco: Image.Image, caixa: tuple[int, int, int, int], alinhar: str = "esq",
                vertical: str = "centro") -> tuple[int, int, int, int]:
    x0, y0, x1, y1 = caixa
    k = min(1.0, (x1 - x0) / bloco.width, (y1 - y0) / bloco.height)
    if k < 1:  # estimativa passou do espaço: encolhe para caber
        bloco = bloco.resize((int(bloco.width * k), int(bloco.height * k)), Image.LANCZOS)
    x = {"esq": x0, "centro": (x0 + x1 - bloco.width) // 2, "dir": x1 - bloco.width}[alinhar]
    y = {"topo": y0, "centro": (y0 + y1 - bloco.height) // 2, "base": y1 - bloco.height}[vertical]
    base = can.convert("RGBA")
    _colar(base, bloco, x, y)
    can.paste(base.convert("RGB"))
    return x, y, x + bloco.width, y + bloco.height


# ───────────────────────────── layouts ─────────────────────────────

def _marcar(can, m: Midia, marcacao: dict | None, escala: float, ox: float, oy: float, pal: dict) -> None:
    """Círculo à mão sobre o detalhe de meta.thumbnail.marcacao, se for desta cena."""
    if not marcacao or marcacao.get("cena") != m.cid:
        return
    cx = marcacao["x"] * m.img.width * escala + ox
    cy = marcacao["y"] * m.img.height * escala + oy
    r = marcacao.get("raio", 0.12) * max(m.img.size) * escala
    circulo_mao(can, cx, cy, r * 1.1, r * 0.85, pal)


def layout_seta(a: Midia, b: Midia, texto: str, segs, pal: dict, marcacao=None) -> Image.Image:
    """A | B em diagonal; seta grossa cruzando o corte; etiquetas A e B (ou bloco de texto no lado mais vazio)."""
    can = Image.new("RGB", (W, H), pal["escuro"])
    topo, base = int(W * 0.56), int(W * 0.44)
    lw = int(W * 0.62)
    # A à esquerda
    fa, sa, xa, ya = encaixar(realcar(a.img), lw, H, a.centro)
    can.paste(fa, (0, 0))
    # B à direita: se o objeto recorta bem, fundo = ele mesmo desfocado/escurecido e o recorte salta à frente
    fb, sbb, xb, yb = encaixar(realcar(b.img), lw, H, b.centro)
    if b.recortavel:
        # papel escuro puxado para a cor de destaque, com foco de luz atrás do objeto
        fb = fundo_papel(pal["escuro"], luz=(0.78, 0.55), seed=11, cor_luz=pal["acento"]).crop((W - lw, 0, W, H))
    lay = Image.new("RGB", (W, H))
    lay.paste(fb, (W - lw, 0))
    mask = Image.new("L", (W * SS, H * SS), 0)
    ImageDraw.Draw(mask).polygon([(topo * SS, 0), (W * SS, 0), (W * SS, H * SS), (base * SS, H * SS)], 255)
    can.paste(lay, (0, 0), mask.resize((W, H), Image.LANCZOS))
    _marcar(can, a, marcacao, sa, -xa, -ya, pal)
    if not b.recortavel:
        _marcar(can, b, marcacao, sbb, W - lw - xb, -yb, pal)
    can = vinheta(can, 0.5)
    _vetor(can, lambda d, c: d.line([(topo * SS, -10), (base * SS, H * SS + 10)], fill=c, width=12 * SS),
           pal["claro"], pal, contorno=0)
    partes = dividir_operador(texto)
    if b.recortavel:
        obj = b.recorte()
        s = min(W * 0.46 / obj.width, H * 0.72 / obj.height)
        obj = obj.resize((int(obj.width * s), int(obj.height * s)), Image.LANCZOS)
        ox = int(W * 0.76 - obj.width / 2)
        ox = min(ox, W - obj.width - 24)
        oy = int(H * 0.52 - obj.height / 2) if partes else int(H - obj.height - 30)
        colar_adesivo(can, obj, (ox, oy), pal, borda=8)
        if marcacao and marcacao.get("cena") == b.cid:
            x0, y0, *_ = b.bbox
            f = int(0.02 * max(b.img.size))
            _marcar(can, b, marcacao, s, ox - (max(0, x0 - f)) * s, oy - (max(0, y0 - f)) * s, pal)
    if partes:
        ta, tb = partes
        dest = {norm(p) for seg, d in segs if d for p in seg.split()}
        da = bool(dest & set(norm(ta).split()))
        db = bool(dest & set(norm(tb).split()))
        if not (da or db):
            da = True
        ea = bloco_texto([(ta, da)], int(W * 0.46), int(H * 0.3), pal, angulo=3, max_linhas=1, tam_max=190)
        eb = bloco_texto([(tb, db)], int(W * 0.5), int(H * 0.3), pal, angulo=-3, max_linhas=1, tam_max=190)
        colar_bloco(can, ea, (24, 18, W // 2, H // 2), "esq", "topo")
        colar_bloco(can, eb, (W // 2, H - H // 3, W - 20, H - 16), "dir", "base")
        seta(can, (W * 0.30, H * 0.62), (W * 0.62, H * 0.44), 0.32, 64, pal)
    else:
        bloco = bloco_texto(segs, int(W * 0.5), int(H * 0.56), pal, angulo=-3, max_linhas=3, tam_max=190)
        caixa = colar_bloco(can, bloco, (28, 22, int(W * 0.56), int(H * 0.62)), "esq", "topo")
        seta(can, (caixa[0] + (caixa[2] - caixa[0]) * 0.55, caixa[3] - 6), (W * 0.62, H * 0.80), -0.35, 56, pal)
    return grao(can, 5)


def layout_heroi(heroi: Midia, fundo_m: Midia | None, texto: str, segs, pal: dict, fundo_ia=None,
                 marcacao=None) -> Image.Image:
    """Sujeito recortado enorme à direita; fundo = o outro lado da história desfocado e tingido; texto gigante."""
    origem = fundo_ia if fundo_ia is not None else (fundo_m.img if fundo_m else heroi.img)
    f, *_ = encaixar(realcar(origem), W, H, fundo_m.centro if (fundo_m and fundo_ia is None) else (0.5, 0.5))
    f = f.filter(ImageFilter.GaussianBlur(7 if (fundo_ia is not None or fundo_m) else 22))
    f = tingir(f, pal["escuro"], pal["acento"], 0.35)
    can = ImageEnhance.Brightness(f).enhance(0.85)
    # escurece o lado do texto (gradiente) para a letra saltar
    grad = Image.linear_gradient("L").rotate(90).resize((W, H)).point(lambda v: int(max(0, v - 60) * 0.95))
    escuro = Image.new("RGB", (W, H), pal["escuro"])
    can = Image.composite(escuro, can, ImageOps.mirror(grad).point(lambda v: int(v * 0.9)))
    can = vinheta(can, 0.45, cx=0.65)
    lado_texto = int(W * 0.56)              # o texto pode avançar um pouco sobre o sujeito
    area_obj = int(W * 0.40)
    if heroi.recortavel:
        obj = heroi.recorte()
        alvo_h = H * (1.0 if heroi.toca_base else 0.84)
        s = min((W - area_obj - 10) / obj.width, alvo_h / obj.height)
        obj = obj.resize((int(obj.width * s), int(obj.height * s)), Image.LANCZOS)
        ox = W - obj.width - max(10, (W - area_obj - obj.width) // 2)
        oy = H - obj.height + (8 if heroi.toca_base else -int((H - obj.height) * 0.45))
        colar_adesivo(can, obj, (ox, oy), pal, borda=10)
        if marcacao and marcacao.get("cena") == heroi.cid:
            x0, y0, *_ = heroi.bbox
            fo = int(0.02 * max(heroi.img.size))
            _marcar(can, heroi, marcacao, s, ox - max(0, x0 - fo) * s, oy - max(0, y0 - fo) * s, pal)
    else:
        card = foto_moldura(heroi.img, int(W * 0.5), int(H * 0.62), pal, -4, heroi.centro, borda=14)
        ox, oy = W - card.width + 30, (H - card.height) // 2
        base = can.convert("RGBA")
        _colar(base, card, ox, oy)
        can = base.convert("RGB")
    bloco = bloco_texto(segs, lado_texto - 40, int(H * 0.86), pal, angulo=-4, max_linhas=4, tam_max=210)
    colar_bloco(can, bloco, (34, 30, lado_texto, H - 30), "esq", "centro")
    return grao(can, 6)


def layout_domino(a: Midia, b: Midia, texto: str, segs, pal: dict, fundo_ia=None, marcacao=None) -> Image.Image:
    """Fundo de papel escuro; A e B inclinados (recorte ou foto emoldurada); dominós caindo de A até B."""
    if fundo_ia is not None:
        f, *_ = encaixar(fundo_ia, W, H)
        can = ImageEnhance.Brightness(tingir(f.filter(ImageFilter.GaussianBlur(6)), pal["escuro"], pal["ouro"], .5)).enhance(.45)
    else:
        can = fundo_papel(pal["escuro"])
    larg, alt = int(W * 0.37), int(H * 0.46)
    meio_y = H * 0.66                                   # centro da faixa das imagens (o texto fica em cima)
    for k, (m, cx, ang) in enumerate(((a, W * 0.22, 5), (b, W * 0.78, -4))):
        if k == 1:  # dominós saem de A e somem atrás de B
            domino(can, W * 0.33, W * 0.66, H * 0.93, pal, alt=int(H * 0.17))
        if m.recortavel:
            obj = m.recorte()
            s = min(W * 0.38 / obj.width, H * 0.56 / obj.height)
            obj = obj.resize((int(obj.width * s), int(obj.height * s)), Image.LANCZOS)
            obj = obj.rotate(ang * 0.5, Image.BICUBIC, expand=True)
            oy = int(H * 0.96 - obj.height) if m.toca_base else int(meio_y - obj.height / 2)
            colar_adesivo(can, obj, (int(cx - obj.width / 2), oy), pal, borda=8, brilho=False)
        else:
            card = foto_moldura(m.img, larg, alt, pal, ang, m.centro)
            base = can.convert("RGBA")
            _colar(base, card, int(cx - card.width / 2), int(meio_y - card.height / 2))
            can.paste(base.convert("RGB"))
    bloco = bloco_texto(segs, int(W * 0.92), int(H * 0.36), pal, alinhar="centro", max_linhas=2, tam_max=210)
    colar_bloco(can, bloco, (0, 14, W, int(H * 0.38)), "centro", "centro")
    can = vinheta(can, 0.45)
    return grao(can, 6)


# ───────────────────────────── prévia e geração ─────────────────────────────

def previa(imgs: list[Image.Image], destino: Path) -> None:
    """As variações em 320×180 (busca/home no celular) e 168×94 (barra lateral), lado a lado."""
    fundo = (15, 15, 15)
    can = Image.new("RGB", (24 + len(imgs) * 344, 24 + 180 + 20 + 94 + 24), fundo)
    for k, im in enumerate(imgs):
        x = 24 + k * 344
        can.paste(im.resize((320, 180), Image.LANCZOS), (x, 24))
        can.paste(im.resize((168, 94), Image.LANCZOS), (x, 24 + 180 + 20))
    can.save(destino, quality=92)


SUFIXO_FUNDO = ("no text, no letters, no logos, no watermark, no recognizable real person, no faces, "
                "strong focal subject, high contrast, dramatic light, empty lower third for a title")


def fundo_local(prompt: str, destino: Path, formato: str = "16:9", seed: int | None = None) -> Path:
    """Fundo de thumbnail/capa (sem texto) pelo modelo de imagem LOCAL. formato: 16:9 (thumbnail) | 9:16 (capa)."""
    import ia_local
    log(f"  thumbnail: gerando fundo local (~{ia_local.estimar_minutos(1, 0):.1f} min de GPU)...")
    it = ia_local.gerar_wangp([ia_local.tarefa_imagem("fundo", f"{prompt.rstrip('. ')}. {SUFIXO_FUNDO}", destino,
                                                      formato, seed)])[0]
    if not it["ok"]:
        raise RuntimeError(it.get("erro"))
    return destino


def gerar(slug: str, forcar: list[str] | None = None, fundo_ia: bool = False,
          prompt_fundo: str | None = None, saida: Path | str | None = None) -> list[Path]:
    ep = pasta_episodio(slug)
    sb = ler_storyboard(ep)
    th = sb["meta"].get("thumbnail") or {}
    texto = th.get("texto") or sb["meta"]["titulo"]
    forcar = forcar or th.get("cenas")
    cands = candidatas(ep, sb)
    if forcar:
        mapa = {cid: arq for _, cid, arq in cands}
        escolha = [(cid, mapa.get(cid) or midia_da_cena(ep, cid)) for cid in forcar]
        escolha = [(cid, a) for cid, a in escolha if a]
        escolha += [(cid, arq) for _, cid, arq in cands if cid not in forcar]
    else:
        escolha = [(cid, arq) for _, cid, arq in cands]
    final = ep / "final"
    destino = Path(saida) if saida else final
    destino.mkdir(parents=True, exist_ok=True)
    fundo = None
    if fundo_ia:
        final.mkdir(exist_ok=True)
        arq_fundo = final / "thumbnail_fundo_ia.png"
        if not arq_fundo.exists():
            fundo_local(prompt_fundo or th.get("ideia_visual") or sb["meta"]["titulo"], arq_fundo)
        fundo = Image.open(arq_fundo).convert("RGB")
    if not escolha:
        log("  thumbnail: nenhuma cena com mídia — pulei")
        return []
    pal = paleta()
    segs = segmentos(texto, th.get("destaque"))
    n_palavras = len([w for w in texto.split() if norm(w) not in {norm(o) for o in OPERADORES}])
    if n_palavras > 4:
        log(f"  AVISO thumbnail: '{texto}' tem {n_palavras} palavras (ideal <=4) — "
            "texto curto e grande rende mais CTR; peça meta.thumbnail.texto menor ao roteirista")
    ms: list[Midia] = []
    for cid, arq in escolha[:4]:  # 2 extras: pool para trocar rosto genérico por objeto
        try:
            ms.append(Midia(cid, quadro(ep, arq)))
        except Exception as e:
            log(f"  thumbnail: pulei {cid} ({e})")
    if not ms:
        return []
    # quem é o protagonista real (rotulo.tipo == "pessoa") e quem apenas tem rosto na foto
    pessoas = {c["id"] for c in sb["cenas"] if (c.get("rotulo") or {}).get("tipo") == "pessoa"}
    for m in ms:
        m.pessoa = m.cid in pessoas
        m.rosto = m.pessoa or _tem_rosto(m.img)
    a = ms[0]
    b = ms[1] if len(ms) > 1 else ms[0]
    # anti-genérico: rosto que não é o protagonista não divide a thumbnail com ele; sem protagonista,
    # no máximo UM rosto (o de melhor recorte) — o outro slot vira objeto
    par = [a, b]
    tem_pessoa = any(m.pessoa for m in ms)
    rostos_par = [m for m in par if m.rosto]
    fraco = min(rostos_par, key=lambda m: m.nota) if len(rostos_par) > 1 else None
    for pos, m in enumerate(par):
        gen = m.rosto and not m.pessoa and tem_pessoa   # humano genérico ao lado do real
        dup = m is fraco and not tem_pessoa             # o mais fraco de 2 rostos genéricos
        if gen or dup:
            sub = next((x for x in ms if x not in par and not x.rosto), None)
            if sub is not None:
                par[pos] = sub
    a, b = par
    # herói: o pedido em meta.thumbnail.sujeito; senão protagonista recortável; senão o melhor recorte
    sujeito = th.get("sujeito")
    if sujeito and sujeito not in {m.cid for m in ms} and midia_da_cena(ep, sujeito):
        ms.append(Midia(sujeito, quadro(ep, midia_da_cena(ep, sujeito))))
        ms[-1].pessoa = sujeito in pessoas
        ms[-1].rosto = ms[-1].pessoa or _tem_rosto(ms[-1].img)
    pool = [m for m in ms if m.pessoa and m.recortavel] or [m for m in ms if m.recortavel] or list(ms)
    heroi = next((m for m in ms if m.cid == sujeito), None) or max(reversed(pool), key=lambda m: m.nota)
    outro = next((m for m in ms if m is not heroi), None)
    marcacao = th.get("marcacao")
    feitos = {
        "seta": lambda: layout_seta(a, b, texto, segs, pal, marcacao) if b is not a else None,
        "heroi": lambda: layout_heroi(heroi, outro, texto, segs, pal, fundo, marcacao),
        "domino": lambda: layout_domino(a, b, texto, segs, pal, fundo, marcacao) if b is not a else None,
    }
    # ordem: meta.thumbnail.layouts manda; senão, 'heroi' abre quando o sujeito é forte:
    # protagonista real, rosto detectado ou sujeito escolhido a dedo pelo roteirista
    base = th.get("layouts") or ((["heroi"] if (heroi.recortavel and (heroi.pessoa or heroi.rosto or sujeito)) else [])
                                 + list(LAYOUTS))
    ordem = []
    for x in base:
        if x in feitos and x not in ordem:
            ordem.append(x)
    ordem += [x for x in LAYOUTS if x not in ordem]
    imgs, nomes, min_linha = [], [], {}
    for nome in ordem:
        bloco_texto.min_linha = 10 ** 9
        try:
            im = feitos[nome]()
        except Exception as e:
            log(f"  aviso: layout {nome} falhou ({e})")
            im = None
        if im is not None:
            imgs.append(im)
            nomes.append(nome)
            min_linha[nome] = bloco_texto.min_linha
            if min_linha[nome] < 80:
                log(f"  AVISO thumbnail ({nome}): menor linha ~{min_linha[nome]}px no cartaz — "
                    "fica ilegível no celular (168px); encurte o texto")
        if len(imgs) == 3:
            break
    saidas = []
    for k, im in enumerate(imgs, 1):
        p = destino / f"thumbnail_{k}.jpg"
        im.save(p, quality=93)
        saidas.append(p)
    if imgs:
        imgs[0].save(destino / "thumbnail.jpg", quality=93)
        previa(imgs, destino / "thumbnail_previa.jpg")
        # registro p/ atribuir o resultado do 'Teste e compare' às features de cada variante
        salvar_json(destino / "ctr_log.json", {
            "slug": slug, "canal": sb["meta"].get("canal") or "demo",
            "titulo": sb["meta"]["titulo"], "texto_thumb": texto, "palavras": n_palavras,
            "gerado_em": time.strftime("%Y-%m-%d %H:%M"),
            "variantes": [{"arquivo": f"thumbnail_{k}.jpg", "layout": nome,
                           "cenas": [a.cid, b.cid], "sujeito": heroi.cid,
                           "min_linha_px": min_linha.get(nome)}
                          for k, nome in enumerate(nomes, 1)],
            "resultado": {"vencedor": "", "ctr_7d": "", "ctr_28d": "", "impressoes_28d": "",
                          "teste_titulo": {"variantes": [], "vencedor": ""}}})
    for f in (ep / "build").glob("_thumb_*.png"):
        f.unlink(missing_ok=True)
    recortes = ", ".join(f"{m.cid}{'*' if m.pessoa else ''} recorte {m.nota:.2f}" for m in ms[:4])
    log(f"  thumbnail: {len(saidas)} variação(ões) [{', '.join(nomes)}] com {recortes}"
        f"{' + fundo IA local' if fundo is not None else ''} -> {destino / 'thumbnail.jpg'}")
    return saidas


def ctr_log() -> None:
    """Consolida os final/ctr_log.json dos episódios em canais/<canal>/ctr_log.csv (uma linha por
    variante). Preencha vencedor/ctr no Studio ('Teste e compare' + YouTube Analytics) para fechar
    o loop: as colunas ligam o resultado às features (layout, nº de palavras, sujeito, cenas)."""
    por_canal: dict[str, list] = {}
    for p in sorted(RAIZ.glob("episodios/*/final/ctr_log.json")):
        d = ler_json(p, None)
        if not d:
            continue
        res = d.get("resultado") or {}
        for i, v in enumerate(d.get("variantes") or [], 1):
            por_canal.setdefault(d.get("canal") or "demo", []).append(
                [d["slug"], d.get("titulo", ""), d.get("texto_thumb", ""), d.get("palavras", ""),
                 i, v.get("layout", ""), "|".join(v.get("cenas") or []), v.get("sujeito") or "",
                 v.get("min_linha_px") or "", res.get("vencedor", ""), res.get("ctr_7d", ""),
                 res.get("ctr_28d", ""), res.get("impressoes_28d", "")])
    cab = ["slug", "titulo", "texto_thumb", "palavras", "variante", "layout", "cenas", "sujeito",
           "min_linha_px", "vencedor", "ctr_7d", "ctr_28d", "impressoes_28d"]
    for canal, linhas in por_canal.items():
        out = RAIZ / "canais" / canal / "ctr_log.csv"
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(cab)
            w.writerows(linhas)
        log(f"  ctr_log: {len(linhas)} variante(s) -> {out} — preencha vencedor/ctr com os números do Studio")
    if not por_canal:
        log("  ctr_log: nenhum episódio com ctr_log.json ainda")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("slug", nargs="?")
    ap.add_argument("--cenas", help="ex.: c12,c50 (A, B)")
    ap.add_argument("--saida", help="pasta de saída (padrão: final/ do episódio)")
    ap.add_argument("--fundo-local", action="store_true", help="fundo gerado pela IA local (GPU) nos layouts heroi/domino")
    ap.add_argument("--prompt-fundo", help="descrição do fundo (padrão: meta.thumbnail.ideia_visual)")
    ap.add_argument("--ctr-log", action="store_true",
                    help="consolida final/ctr_log.json dos episódios em canais/<id>/ctr_log.csv")
    a = ap.parse_args()
    if a.ctr_log:
        ctr_log()
        return
    if not a.slug:
        ap.error("slug é obrigatório (ou use --ctr-log)")
    saida = a.saida
    if saida and not Path(saida).is_absolute():
        saida = RAIZ / saida
    gerar(a.slug, a.cenas.split(",") if a.cenas else None, a.fundo_local, a.prompt_fundo, saida)


if __name__ == "__main__":
    main()
