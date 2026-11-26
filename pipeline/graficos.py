"""Cartelas e rótulos (lower thirds) com Pillow, desenhados com os tokens do canal — e animados.

Cada grafismo é montado como uma lista de PEÇAS (linha de texto, palavra, fio de cor, véu de contraste), e cada
peça tem uma animação de entrada própria, com atraso (stagger):
  subir   → revelação por máscara: o texto sobe de trás de uma "fenda" invisível (títulos de documentário);
  linha_h → fio que se desenha da esquerda para a direita;  linha_v → de cima para baixo;
  fade    → aparece com um leve deslize (véus, textos secundários).
A saída também é animada (máscara ao contrário, mais rápida). Os quadros da animação são PNGs RGBA recortados
na caixa do grafismo; um arquivo `ffconcat` monta a linha do tempo (vazio → entrada → parado → saída → vazio)
que o montar.py sobrepõe com um único `overlay` — sem expressões de filtro complicadas.

O layout é decidido pelo CONTEÚDO (tem número? é data? é frase longa?), e a seed da cena só desempata.
"""
from __future__ import annotations

import json
import re
import textwrap
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageOps

import i18n
from estilo import caminho_fonte, rng, tokens

# a "cifra" é o número + magnitude (mil, milhões, %); unidades (litros, km) vão para a legenda
_MAG = r"mil|milh(?:ões|ão)|bilh(?:ões|ão)|trilh(?:ões|ão)|thousand|million|billion|trillion"
RE_NUMERO = re.compile(r"[~≈]?\s*(?:US\$|R\$|\$)?\s*\d[\d.,]*(?:\s*(?:%|" + _MAG + r")(?!\w))?", re.I)
RE_MAGNITUDE = re.compile(r"\s+(" + _MAG + r")$", re.I)
# datas: "1919", "15 de janeiro de 1919", "15/01/1919", "January 15, 1919", "15 January 1919", "Jan. 1919"
RE_DATA = re.compile(r"^\s*(\d{1,2}\s+de\s+\w+\s+de\s+)?\d{3,4}\s*$|^\s*\d{1,2}/\d{1,2}/\d{2,4}\s*$"
                     r"|^\s*[A-Z][a-z]+\.?\s+(\d{1,2},?\s+)?\d{3,4}\s*$|^\s*\d{1,2}\s+[A-Z][a-z]+\.?\s+\d{3,4}\s*$", re.I)


def cor(hexa: str, alpha: int | None = None) -> tuple:
    h = hexa.lstrip("#")
    rgb = tuple(int(h[i:i + 2], 16) for i in range(0, 6, 2))
    if len(h) == 8:
        return rgb + (int(h[6:8], 16),)
    return rgb + ((alpha,) if alpha is not None else ())


def fonte(nome: str, tamanho: int) -> ImageFont.FreeTypeFont:
    return _fonte_arq(caminho_fonte(nome), max(6, int(tamanho)))  # caminho vem dos tokens do canal


@lru_cache(maxsize=64)
def _fonte_arq(caminho: str, tamanho: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(caminho, tamanho)


# ---------------------------------------------------------------- tipografia
def _avancos(texto: str, f, tracking: float) -> list[float]:
    """Posição x de cada caractere, respeitando o kerning do par (largura do prefixo) + tracking."""
    return [f.getlength(texto[:i]) + tracking * i for i in range(len(texto))]


def largura_espacada(d, texto, f, tracking) -> float:
    if not texto:
        return 0.0
    return f.getlength(texto) + tracking * (len(texto) - 1)


def texto_espacado(d: ImageDraw.ImageDraw, xy, texto: str, f, fill, tracking: float = 0.0) -> float:
    """Desenha com espaçamento entre letras (caixa-alta de rótulo) sem perder o kerning. Retorna a largura."""
    x, y = xy
    if not tracking:
        d.text((x, y), texto, font=f, fill=fill)
        return f.getlength(texto)
    for ch, dx in zip(texto, _avancos(texto, f, tracking)):
        d.text((x + dx, y), ch, font=f, fill=fill)
    return largura_espacada(d, texto, f, tracking)


def _metricas(f) -> tuple[int, int]:
    asc, desc = f.getmetrics()
    return asc, desc


def img_texto(texto: str, f, fill, tracking: float = 0.0) -> Image.Image:
    """Texto numa imagem RGBA justa na caixa da fonte (ascendente + descendente), com folga para a máscara."""
    asc, desc = _metricas(f)
    folga = int(f.size * 0.08)
    w = int(largura_espacada(None, texto, f, tracking) + 2 * folga + 2)
    img = Image.new("RGBA", (max(1, w), asc + desc + 2 * folga), (0, 0, 0, 0))
    texto_espacado(ImageDraw.Draw(img), (folga, folga), texto, f, fill, tracking)
    img.info["folga"] = folga
    return img


def img_retangulo(w: float, h: float, fill) -> Image.Image:
    return Image.new("RGBA", (max(1, round(w)), max(1, round(h))), fill)


def img_veu(w: float, h: float, raio: float, alpha: int, lado: str = "esq") -> Image.Image:
    """Véu escuro difuso atrás do texto (legibilidade sobre foto clara) — sem caixa dura.
    lado="esq": mais denso à esquerda e some para a direita, como um gradiente de lower third."""
    m = int(raio * 2.6)
    k = int(raio * 0.5)  # o miolo é maior que o texto: o desfoque come a borda, não a densidade atrás das letras
    W, H = int(w) + 2 * m, int(h) + 2 * m
    mascara = Image.new("L", (W, H), 0)
    ImageDraw.Draw(mascara).rounded_rectangle([m - k, m - k, m + int(w) + k, m + int(h) + k],
                                              radius=int(h * 0.5 + k), fill=alpha)
    mascara = mascara.filter(ImageFilter.GaussianBlur(raio))
    if lado == "esq":
        grad = Image.linear_gradient("L").rotate(-90, expand=True).resize((W, H))  # 255 à esquerda → 0
        grad = grad.point(lambda v: int(110 + v * 145 / 255))
        mascara = ImageChops.multiply(mascara, grad)
    veu = Image.new("RGBA", (W, H), cor(tokens()["cores"]["tinta"], 0))
    veu.putalpha(mascara)
    veu.info["margem"] = m
    return veu


# ---------------------------------------------------------------- animação
def _bezier(x1: float, y1: float, x2: float, y2: float):
    """Curva cubic-bezier(x1,y1,x2,y2) como função t→y (mesma do CSS)."""
    def bx(t):
        return 3 * x1 * t * (1 - t) ** 2 + 3 * x2 * t * t * (1 - t) + t ** 3

    def by(t):
        return 3 * y1 * t * (1 - t) ** 2 + 3 * y2 * t * t * (1 - t) + t ** 3

    def f(x):
        if x <= 0:
            return 0.0
        if x >= 1:
            return 1.0
        lo, hi = 0.0, 1.0
        for _ in range(30):
            m = (lo + hi) / 2
            if bx(m) < x:
                lo = m
            else:
                hi = m
        return by((lo + hi) / 2)
    return f


EASE_ENTRADA = _bezier(0.16, 1, 0.3, 1)       # "expo out": chega rápido e assenta devagar
EASE_SAIDA = _bezier(0.7, 0, 0.84, 0)         # "expo in": sai acelerando


@dataclass
class Peca:
    img: Image.Image
    x: float
    y: float
    tipo: str = "subir"          # subir | linha_h | linha_v | fade
    atraso: float = 0.0          # s, relativo ao início da entrada
    dur: float = 0.7
    sombra: bool = True          # recebe sombra suave (texto sobre foto)
    atraso_saida: float = 0.0


@dataclass
class Grafismo:
    w: int
    h: int
    pecas: list[Peca] = field(default_factory=list)
    sombra: tuple[float, float, int] = (0, 0, 0)   # (raio, deslocamento y, opacidade 0-255); 0 = sem sombra

    def add(self, *p: Peca) -> None:
        self.pecas.extend(p)

    @property
    def dur_entrada(self) -> float:
        return max((p.atraso + p.dur for p in self.pecas), default=0.0)


def _peca_no_instante(p: Peca, a: float, s: float) -> Image.Image | None:
    """Imagem da peça para progresso de entrada a∈[0,1] e de saída s∈[0,1]. None = invisível."""
    if a <= 0 or s >= 1:
        return None
    pw, ph = p.img.size
    img = p.img
    if p.tipo == "subir":
        dy = (1 - a) * ph * 0.92 - s * ph * 0.92
        alpha = min(1.0, a * 1.8) * (1 - s)
        quadro = Image.new("RGBA", (pw, ph), (0, 0, 0, 0))
        quadro.paste(img, (0, round(dy)))
        img = quadro
    elif p.tipo == "linha_h":
        x0, x1 = round(pw * s), round(pw * a)
        if x1 - x0 < 1:
            return None
        quadro = Image.new("RGBA", (pw, ph), (0, 0, 0, 0))
        quadro.paste(img.crop((x0, 0, x1, ph)), (x0, 0))
        img, alpha = quadro, 1.0
    elif p.tipo == "linha_v":
        y0, y1 = round(ph * s), round(ph * a)
        if y1 - y0 < 1:
            return None
        quadro = Image.new("RGBA", (pw, ph), (0, 0, 0, 0))
        quadro.paste(img.crop((0, y0, pw, y1)), (0, y0))
        img, alpha = quadro, 1.0
    else:  # fade
        alpha = a * (1 - s)
    if alpha < 0.999:
        canal = img.getchannel("A").point(lambda v: int(v * alpha))
        img = img.copy()
        img.putalpha(canal)
    return img


def compor(g: Grafismo, t: float, t_saida: float | None = None, dur_saida: float = 0.45) -> Image.Image:
    """Quadro do grafismo t segundos após o início da entrada (t_saida: quando a saída começa)."""
    camada = Image.new("RGBA", (g.w, g.h), (0, 0, 0, 0))
    fundo = Image.new("RGBA", (g.w, g.h), (0, 0, 0, 0))
    for p in g.pecas:
        a = EASE_ENTRADA((t - p.atraso) / p.dur) if p.dur > 0 else 1.0
        s = 0.0
        if t_saida is not None:
            s = EASE_SAIDA((t - t_saida - p.atraso_saida) / dur_saida)
        im = _peca_no_instante(p, a, s)
        if im is not None:
            (camada if p.sombra else fundo).alpha_composite(im, (round(p.x), round(p.y)))
    raio, dy, opac = g.sombra
    if opac and camada.getbbox():
        a = camada.getchannel("A").filter(ImageFilter.GaussianBlur(raio))
        a = a.point(lambda v: min(255, int(v * opac / 255 * 1.6)))
        sombra = Image.new("RGBA", (g.w, g.h), (0, 0, 0, 0))
        sombra.paste(Image.new("RGBA", (g.w, g.h), (0, 0, 0, 255)), (0, round(dy)), a)
        fundo.alpha_composite(sombra)
    fundo.alpha_composite(camada)
    return fundo


def exportar_animacao(g: Grafismo, pasta: Path, fps: int, ti: float, tf: float | None, dur_total: float,
                      dur_saida: float = 0.45) -> Path:
    """Escreve os quadros (PNG RGBA) e um `ffconcat` cobrindo a cena inteira:
    vazio até ti → entrada → parado → saída (a partir de tf) → vazio. Retorna o .ffconcat."""
    pasta.mkdir(parents=True, exist_ok=True)
    for velho in pasta.glob("*.png"):
        velho.unlink()
    passo = 1 / fps
    n_in = max(1, round(g.dur_entrada * fps))
    linhas = ["ffconcat version 1.0"]

    def entrada(nome: str, dur: float) -> None:
        linhas.append(f"file '{(pasta / nome).as_posix()}'")
        linhas.append(f"duration {max(dur, 0.0):.6f}")

    vazio = Image.new("RGBA", (g.w, g.h), (0, 0, 0, 0))
    vazio.save(pasta / "vazio.png", compress_level=1)
    if tf is not None:
        tf = max(tf, ti + g.dur_entrada + 0.3)
    fim_hold = (tf if tf is not None else dur_total)
    if ti > 0:
        entrada("vazio.png", ti)
    for i in range(n_in):
        compor(g, i * passo).save(pasta / f"e{i:03d}.png", compress_level=1)
        entrada(f"e{i:03d}.png", passo)
    compor(g, g.dur_entrada + 1).save(pasta / "cheio.png", compress_level=1)
    entrada("cheio.png", fim_hold - ti - n_in * passo)
    if tf is not None:
        atraso_max = max((p.atraso_saida for p in g.pecas), default=0)
        n_out = max(1, round((dur_saida + atraso_max) * fps))
        t_base = g.dur_entrada + 1
        for i in range(n_out):
            compor(g, t_base + i * passo, t_saida=t_base, dur_saida=dur_saida).save(pasta / f"s{i:03d}.png",
                                                                                     compress_level=1)
            entrada(f"s{i:03d}.png", passo)
        entrada("vazio.png", max(passo, dur_total - tf - n_out * passo + 1))
    linhas.append(f"file '{(pasta / ('vazio.png' if tf is not None else 'cheio.png')).as_posix()}'")
    lista = pasta / "linha.ffconcat"
    lista.write_text("\n".join(linhas) + "\n", encoding="utf-8")
    return lista


def filtro_overlay(idx: int, entrada: str, x: float, y: float, fps: int, saida: str, nome: str = "graf") -> list[str]:
    """Filtros FFmpeg para sobrepor uma animação exportada (entrada `idx` aberta com args_entrada)."""
    return [f"[{idx}:v]fps={fps},format=rgba,setpts=PTS-STARTPTS[{nome}]",
            f"{entrada}[{nome}]overlay=x={round(x)}:y={round(y)}:eof_action=pass:format=auto{saida}"]


def args_entrada(lista: Path) -> list[str]:
    return ["-f", "concat", "-safe", "0", "-i", str(lista)]


# ---------------------------------------------------------------- fundo de cartela
def _textura_papel(w: int, h: int, intensidade: int = 7, seed: int = 0) -> Image.Image:
    """Grão fixo e fino (não pisca): tira o aspecto de 'cor chapada digital' do fundo."""
    ruido = Image.effect_noise((w // 2, h // 2), 40).resize((w, h), Image.BICUBIC)
    return ruido.point(lambda v: 128 + (v - 128) * intensidade // 40)


def fundo_canal(w: int, h: int, cena: dict, imagem_fundo: Path | None = None) -> Image.Image:
    """Fundo das cartelas: imagem vizinha desfocada e escurecida (nunca igual) ou tinta com luz suave."""
    c = tokens()["cores"]
    r = rng(cena, "fundo")
    if imagem_fundo and imagem_fundo.exists():
        with Image.open(imagem_fundo) as im:
            base = ImageOps.fit(im.convert("RGB"), (w, h))
        base = ImageOps.grayscale(base).convert("RGB").filter(ImageFilter.GaussianBlur(w / 60))
        escuro = Image.new("RGB", (w, h), cor(c["tinta"]))
        base = Image.blend(base, escuro, 0.8)
    else:
        base = Image.new("RGB", (w, h), cor(c["tinta"]))
    # luz difusa em posição que varia por cena (evita o "slide preto chapado")
    luz = Image.new("L", (w, h), 0)
    dl = ImageDraw.Draw(luz)
    cx, cy = r.uniform(0.25, 0.75) * w, r.uniform(0.3, 0.7) * h
    raio = r.uniform(0.45, 0.7) * w
    dl.ellipse([cx - raio, cy - raio * 0.7, cx + raio, cy + raio * 0.7], fill=r.randint(22, 34))
    luz = luz.filter(ImageFilter.GaussianBlur(w / 8))
    base = Image.composite(Image.new("RGB", (w, h), (52, 54, 60)), base, luz)
    # grão fixo bem sutil (overlay suave) — a vinheta e o grão animado vêm no acabamento
    grao = _textura_papel(w, h).convert("RGB")
    return ImageChops.soft_light(base, grao)


def _quebrar(texto: str, f, largura_max: float) -> list[str]:
    """Quebra equilibrada: a maior largura que cabe, depois tenta deixar as linhas parecidas (sem viúva)."""
    for largura in range(48, 6, -1):
        linhas = textwrap.wrap(texto, width=largura) or [texto]
        if max(f.getlength(l) for l in linhas) <= largura_max:
            break
    else:
        return textwrap.wrap(texto, width=8)
    n = len(linhas)
    if n > 1:  # menor largura que mantém o mesmo número de linhas → bloco mais quadrado
        for menor in range(largura - 1, 6, -1):
            alt = textwrap.wrap(texto, width=menor)
            if len(alt) != n:
                break
            linhas = alt
    return linhas


def _subir_palavras(g: Grafismo, texto: str, f, fill, x: float, y: float, atraso: float, passo: float,
                    tracking: float = 0.0, dur: float = 0.75) -> float:
    """Uma peça 'subir' por palavra (stagger). Retorna a largura total da linha."""
    pos = _avancos(texto, f, tracking) + [largura_espacada(None, texto, f, tracking) + tracking]
    i, k = 0, 0
    for palavra in texto.split(" "):
        if palavra:
            cor_p = _DESTAQUE["cor"] if _DESTAQUE["cor"] and _chave_palavra(palavra) in _DESTAQUE["palavras"] else fill
            im = img_texto(palavra, f, cor_p, tracking)
            g.add(Peca(im, x + pos[i] - im.info["folga"], y - im.info["folga"], "subir", atraso + k * passo, dur,
                       atraso_saida=k * 0.03))
            k += 1
        i += len(palavra) + 1
    return pos[-1] - tracking


# ---------------------------------------------------------------- cartela
_DESTAQUE: dict = {"cor": None, "palavras": set()}  # **palavra** da cartela (ativo só durante _layout_cartela)


def _chave_palavra(p: str) -> str:
    return re.sub(r"[^\w$%]", "", p).lower()


def _marcar_destaque(texto: str) -> tuple[str, set]:
    """'It heats **water**, wherever' → ('It heats water, wherever', {'water'}). Aceita **várias palavras**."""
    limpas, marcadas, dentro = [], set(), False
    for p in texto.split(" "):
        abre = p.startswith("**")
        fecha = p.rstrip(".,!?;:").endswith("**") and (not abre or len(p.strip("*.,!?;:")) > 0)
        limpa = p.replace("**", "")
        if abre or dentro:
            marcadas.add(_chave_palavra(limpa))
        dentro = (abre or dentro) and not fecha
        limpas.append(limpa)
    return " ".join(limpas), marcadas


def _layout_cartela(texto: str, cena: dict, w: int, h: int) -> tuple[Grafismo, str]:
    texto, marcadas = _marcar_destaque(texto)
    _DESTAQUE.update(cor=cor(tokens()["cores"]["destaque"], 255) if marcadas else None, palavras=marcadas)
    try:
        return _layout_cartela_(texto, cena, w, h)
    finally:
        _DESTAQUE.update(cor=None, palavras=set())


def _layout_cartela_(texto: str, cena: dict, w: int, h: int) -> tuple[Grafismo, str]:
    c, gr = tokens()["cores"], tokens()["grade"]
    r = rng(cena, "cartela")
    e = h / 1080
    g = Grafismo(w, h, sombra=(10 * e, 3 * e, 120))
    mx = int(w * gr["margem_x"])
    branco, suave, destaque = cor(c["texto"], 255), cor(c["texto_suave"], 255), cor(c["destaque"], 255)
    fio = max(2, round(3 * e))
    m = RE_NUMERO.search(texto)
    palavras = texto.split()

    if m and len(texto) <= 48 and any(ch.isdigit() for ch in m.group(0)):
        cifra = m.group(0).strip()
        resto = (texto[:m.start()] + texto[m.end():]).strip(" ·-—,")
        mag = RE_MAGNITUDE.search(cifra)
        numero, magnitude = (cifra[:mag.start()], mag.group(1)) if mag else (cifra, "")
        tam = int(h * (0.34 if not magnitude else 0.30))
        f = fonte("titulo", tam)
        fm = fonte("titulo_italico", int(tam * 0.42))
        larg = lambda: f.getlength(numero) + (fm.getlength(" " + magnitude) if magnitude else 0)
        while larg() > w - 4 * mx and tam > 40:
            tam -= 6
            f, fm = fonte("titulo", tam), fonte("titulo_italico", int(tam * 0.42))
        alinhar_esq = r.random() < 0.55
        lw = larg()
        x = mx * 2 if alinhar_esq else (w - lw) / 2
        asc, _ = _metricas(f)
        y = h * 0.47 - asc * 0.62
        # algarismos entram um a um (a "contagem" visual), a magnitude logo depois em itálico
        for i, (ch, dx) in enumerate(zip(numero, _avancos(numero, f, 0))):
            im = img_texto(ch, f, branco)
            g.add(Peca(im, x + dx - im.info["folga"], y - im.info["folga"], "subir", 0.05 * i, 0.85,
                       atraso_saida=0.02 * i))
        if magnitude:
            im = img_texto(magnitude, fm, branco)
            asc_m, _ = _metricas(fm)
            g.add(Peca(im, x + f.getlength(numero) + fm.getlength(" ") - im.info["folga"],
                       y + asc - asc_m - im.info["folga"], "subir", 0.05 * len(numero) + 0.08, 0.85))
        base_y = y + asc + h * 0.055
        larg_fio = w * 0.05
        fio_x = x + tam * 0.02 if alinhar_esq else (w - larg_fio) / 2
        g.add(Peca(img_retangulo(larg_fio, fio, destaque), fio_x, base_y, "linha_h", 0.35, 0.6, sombra=False))
        if resto:
            fr = fonte("rotulo", int(30 * e))
            tr = 30 * e * 0.16
            for i, l in enumerate(_quebrar(resto.upper(), fr, w * 0.55)):
                lw2 = largura_espacada(None, l, fr, tr)
                lx = fio_x if alinhar_esq else (w - lw2) / 2
                _subir_palavras(g, l, fr, suave, lx, base_y + h * 0.03 + i * 44 * e, 0.5 + 0.08 * i, 0.05, tr, 0.7)
        return g, "numero"

    if len(palavras) <= 3:
        # frase curta: serif grande e centralizada OU caixa-alta espaçada — a seed escolhe, o conteúdo manda
        serif = r.random() < 0.6 and len(texto) <= 26
        if serif:
            f, tr, t = fonte("titulo", int(h * 0.105)), 0.0, texto[0].upper() + texto[1:]
        else:
            tam = int(h * 0.062)
            f, t = fonte("rotulo_forte", tam), texto.upper()
            tr = tam * 0.14
        lw = largura_espacada(None, t, f, tr)
        asc, desc = _metricas(f)
        y = h * 0.5 - (asc + desc) * 0.55
        _subir_palavras(g, t, f, branco, (w - lw) / 2, y, 0.0, 0.11, tr, 0.8)
        n = len(t.split())
        larg_fio = w * 0.035
        g.add(Peca(img_retangulo(larg_fio, fio, destaque), (w - larg_fio) / 2, y + asc + desc + h * 0.04,
                   "linha_h", 0.15 + 0.11 * n, 0.55, sombra=False))
        return g, "curta"

    tam = int(h * (0.072 if len(texto) < 90 else 0.06 if len(texto) < 150 else 0.05))
    f = fonte("titulo_medio", tam)
    linhas = _quebrar(texto, f, w * 0.6)
    alt = tam * 1.24
    asc, _ = _metricas(f)
    bloco = alt * (len(linhas) - 1) + asc
    y = (h - bloco) / 2 - tam * 0.1
    x = mx * 2 + w * (0.0 if r.random() < 0.6 else 0.1)
    barra = max(3, round(4 * e))
    g.add(Peca(img_retangulo(barra, bloco + tam * 0.25, destaque), x - w * 0.028, y + tam * 0.05,
               "linha_v", 0.0, 0.9, sombra=False))
    for i, l in enumerate(linhas):  # linha a linha, cada uma saindo da sua fenda
        im = img_texto(l, f, branco)
        g.add(Peca(im, x - im.info["folga"], y + i * alt - im.info["folga"], "subir", 0.12 + 0.12 * i, 0.9,
                   atraso_saida=0.03 * i))
    return g, "frase"


def cartela(texto: str, pasta: Path, cena: dict, w: int, h: int, imagem_fundo: Path | None = None) -> tuple[Path, Path]:
    """Retorna (fundo.png, texto.png RGBA) — versão estática (compatibilidade). Layout:
    - "numero": a cifra domina (serif enorme, magnitude em itálico) e o resto vira legenda em caixa-alta;
    - "frase": serif em bloco, alinhada à esquerda na grade, com fio de destaque;
    - "curta": até 3 palavras, centralizada (serif grande ou caixa-alta espaçada).
    """
    pasta.mkdir(parents=True, exist_ok=True)
    g, _ = _layout_cartela(texto, cena, w, h)
    pf, pt = pasta / f"{cena['id']}_cartela_fundo.png", pasta / f"{cena['id']}_cartela_texto.png"
    fundo_canal(w, h, cena, imagem_fundo).save(pf)
    compor(g, g.dur_entrada + 1).save(pt)
    return pf, pt


def _recortar(g: Grafismo, folga: int) -> tuple[Grafismo, int, int]:
    """Reduz a tela do grafismo à caixa das peças (quadros menores = PNG e overlay bem mais rápidos)."""
    caixa = compor(g, g.dur_entrada + 1).getbbox()
    if not caixa:
        return g, 0, 0
    x0, y0 = max(0, caixa[0] - folga), max(0, caixa[1] - folga - int(g.h * 0.02))
    x1, y1 = min(g.w, caixa[2] + folga), min(g.h, caixa[3] + folga + int(g.h * 0.06))
    novo = Grafismo(x1 - x0, y1 - y0, sombra=g.sombra)
    for p in g.pecas:
        novo.add(Peca(p.img, p.x - x0, p.y - y0, p.tipo, p.atraso, p.dur, p.sombra, p.atraso_saida))
    return novo, x0, y0


def cartela_animada(texto: str, pasta: Path, cena: dict, w: int, h: int, fps: int, ti: float, dur_total: float,
                    imagem_fundo: Path | None = None) -> tuple[Path, Path, int, int]:
    """Cartela com texto animado. Retorna (fundo.png, linha.ffconcat, x, y) — x/y do overlay."""
    pasta.mkdir(parents=True, exist_ok=True)
    g, _ = _layout_cartela(texto, cena, w, h)
    g, x, y = _recortar(g, int(h * 0.03))
    pf = pasta / f"{cena['id']}_cartela_fundo.png"
    fundo_canal(w, h, cena, imagem_fundo).save(pf)
    lista = exportar_animacao(g, pasta / f"{cena['id']}_cartela_anim", fps, ti, None, dur_total)
    return pf, lista, x, y


# ---------------------------------------------------------------- rótulo (lower third)
def tipo_rotulo(texto: str, pedido: str | None = None) -> str:
    if pedido in ("local", "data", "pessoa"):
        return pedido
    return "data" if RE_DATA.match(texto) else "local"


def _layout_rotulo(texto: str, w: int, h: int, tipo: str, subtitulo: str) -> tuple[Grafismo, int, int]:
    """Monta as peças do lower third numa tela local. Retorna (grafismo, x, y) da tela no quadro.

    local  → fio vermelho curto + caixa-alta espaçada (Inter 600), subtítulo opcional em Inter
    data   → serif grande, algarismos entrando um a um, fio ocre vertical ao lado
    pessoa → nome em serif, fio fino que se desenha (com acento vermelho), função em caixa-alta pequena
    Todos sobre um véu escuro difuso (sem caixa dura) e com sombra suave — legível em foto clara ou escura.
    """
    c, gr = tokens()["cores"], tokens()["grade"]
    e = h / 1080
    branco, suave = cor(c["texto"], 255), cor(c.get("rotulo_sub", "#E2DDD3"), 255)
    destaque, ocre = cor(c["destaque"], 255), cor(c["secundaria"], 255)
    fio = max(2, round(3 * e))
    pecas: list[Peca] = []
    sub = (subtitulo or "").strip()

    def add_palavras(txt, f, fill, x, y, atraso, passo, tr=0.0, dur=0.7):
        tmp = Grafismo(1, 1)
        larg = _subir_palavras(tmp, txt, f, fill, x, y, atraso, passo, tr, dur)
        pecas.extend(tmp.pecas)
        return larg

    if tipo == "data":
        f = fonte("titulo", int(66 * e))
        asc, desc = _metricas(f)
        x0 = 22 * e
        for i, (ch, dx) in enumerate(zip(texto, _avancos(texto, f, 0))):
            if ch == " ":
                continue
            im = img_texto(ch, f, branco)
            pecas.append(Peca(im, x0 + dx - im.info["folga"], -im.info["folga"], "subir", 0.12 + 0.035 * i, 0.75,
                              atraso_saida=0.015 * i))
        larg = f.getlength(texto) + x0
        alt = asc + desc * 0.4
        pecas.insert(0, Peca(img_retangulo(fio + 1, alt * 0.92, ocre), 0, alt * 0.06, "linha_v", 0.0, 0.6,
                             sombra=False))
        if sub:
            fs = fonte("rotulo", int(21 * e))
            tr = 21 * e * 0.14
            add_palavras(sub.upper(), fs, suave, x0, alt + 12 * e, 0.45, 0.05, tr, 0.6)
            alt += 12 * e + sum(_metricas(fs))
            larg = max(larg, x0 + largura_espacada(None, sub.upper(), fs, tr))
    elif tipo == "pessoa":
        f1 = fonte("titulo_medio", int(50 * e))
        asc, desc = _metricas(f1)
        larg = add_palavras(texto, f1, branco, 0, 0, 0.0, 0.07, 0.0, 0.8)
        y_fio = asc + desc * 0.55 + 6 * e
        alt = y_fio + fio
        if sub:
            fs = fonte("rotulo", int(21 * e))
            tr = 21 * e * 0.14
            larg = max(larg, largura_espacada(None, sub.upper(), fs, tr))
            add_palavras(sub.upper(), fs, suave, 0, y_fio + 14 * e, 0.4, 0.04, tr, 0.65)
            alt = y_fio + 14 * e + sum(_metricas(fs))
        hair = max(1, round(1.5 * e))
        pecas.append(Peca(img_retangulo(larg, hair, cor(c["texto"], 110)), 0, y_fio, "linha_h", 0.2, 0.8,
                          sombra=False))
        pecas.append(Peca(img_retangulo(44 * e, fio, destaque), 0, y_fio - (fio - hair) / 2, "linha_h", 0.2, 0.45,
                          sombra=False))
    else:
        f = fonte("rotulo", int(30 * e))
        tr = 30 * e * 0.17
        t = texto.upper()
        asc, desc = _metricas(f)
        pecas.append(Peca(img_retangulo(48 * e, fio + 1, destaque), 0, 0, "linha_h", 0.0, 0.5, sombra=False))
        y_txt = fio + 12 * e
        larg = add_palavras(t, f, branco, 0, y_txt, 0.1, 0.07, tr, 0.7)
        alt = y_txt + asc + desc * 0.3
        if sub:
            fs = fonte("corpo", int(25 * e))
            add_palavras(sub, fs, suave, 0, alt + 8 * e, 0.35, 0.05, 0.0, 0.65)
            alt += 8 * e + sum(_metricas(fs))
            larg = max(larg, fs.getlength(sub))

    # véu difuso por baixo de tudo (entra primeiro, em fade)
    raio = 44 * e
    veu = img_veu(larg + 60 * e, alt + 36 * e, raio, 215)
    m = veu.info["margem"]
    pad = int(m + 30 * e)
    W, H = int(larg + 2 * pad), int(alt + 2 * pad)
    g = Grafismo(W, H, sombra=(6 * e, 2 * e, 190))
    g.add(Peca(veu, pad - 30 * e - m, pad - 18 * e - m, "fade", 0.0, 0.6, sombra=False, atraso_saida=0.12))
    for p in pecas:
        p.x += pad
        p.y += pad
        g.add(p)
    x = int(w * gr["margem_x"]) - pad
    y = int(h * gr["linha_rotulo"] - alt / 2) - pad
    return g, x, y


def rotulo(texto: str, destino: Path, w: int, h: int, tipo: str = "local", subtitulo: str = "") -> tuple[Path, int, int, int, int]:
    """Lower third estático em PNG RGBA. Retorna (png, x, y, largura, altura) no quadro."""
    g, x, y = _layout_rotulo(texto, w, h, tipo, subtitulo)
    img = compor(g, g.dur_entrada + 1)
    img.save(destino)
    return destino, x, y, img.width, img.height


def rotulo_animado(texto: str, pasta: Path, w: int, h: int, fps: int, ti: float, tf: float, dur_total: float,
                   tipo: str = "local", subtitulo: str = "") -> tuple[Path, int, int]:
    """Lower third animado (entrada por máscara/stagger, saída por máscara). Retorna (ffconcat, x, y)."""
    g, x, y = _layout_rotulo(texto, w, h, tipo, subtitulo)
    return exportar_animacao(g, pasta, fps, ti, tf, dur_total, dur_saida=0.4), x, y


# compatibilidade com código antigo
def texto_tela(texto: str, destino: Path, w: int, h: int, estilo: dict | None = None) -> Path:
    return rotulo(texto, destino, w, h, tipo_rotulo(texto))[0]


def placeholder(cena: dict, pasta: Path, w: int, h: int) -> tuple[Path, Path]:
    """Cena sem mídia no rascunho: listras de obra + o que falta. Impossível confundir com o vídeo final."""
    pasta.mkdir(parents=True, exist_ok=True)
    fundo = Image.new("RGB", (w, h), (24, 24, 26))
    d = ImageDraw.Draw(fundo)
    passo = w // 24
    for x in range(-h, w, passo * 2):
        d.polygon([(x, h), (x + passo, h), (x + passo + h, 0), (x + h, 0)], fill=(34, 34, 36))
    camada = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(camada)
    v = cena["visual"]
    f1, f2 = fonte("documento_forte", int(h * 0.05)), fonte("documento", int(h * 0.03))
    linhas = [f"{i18n.t('falta_midia')} · {cena['id']} · {v['tipo']}"]
    detalhe = v.get("busca") or v.get("prompt") or v.get("arquivo") or ""
    y = h * 0.42
    d.text((w * 0.08, y), linhas[0], font=f1, fill=(240, 200, 60, 255))
    for i, l in enumerate(textwrap.wrap(detalhe, 70)[:3]):
        d.text((w * 0.08, y + h * 0.08 + i * h * 0.045), l, font=f2, fill=(200, 200, 200, 255))
    pf, pt = pasta / f"{cena['id']}_falta_fundo.png", pasta / f"{cena['id']}_falta_texto.png"
    fundo.save(pf)
    camada.save(pt)
    return pf, pt


def moldura(foto: Path, destino: Path, w: int, h: int, cena: dict, ampliacao_max: float = 2.0) -> Path:
    """Foto pequena demais para tela cheia → cópia impressa sobre a própria foto desfocada.
    Papel levemente amarelado com grão, sombra em duas camadas (contato + ambiente), leve rotação estável.
    Não estica a imagem além de 2× (evita borrão)."""
    r = rng(cena, "moldura")
    c = tokens()["cores"]
    with Image.open(foto) as im:
        im = im.convert("RGB")
        fundo = ImageOps.fit(im, (w, h)).filter(ImageFilter.GaussianBlur(w / 40))
    fundo = Image.blend(fundo, Image.new("RGB", (w, h), cor(c["tinta"])), 0.6)
    escala = min(ampliacao_max, h * 0.74 / im.height, w * 0.7 / im.width)
    foto_r = im.resize((int(im.width * escala), int(im.height * escala)), Image.LANCZOS)
    borda = max(6, int(h * 0.014))
    papel = Image.new("RGB", (foto_r.width + 2 * borda, foto_r.height + 2 * borda), cor(c["papel"]))
    papel = ImageChops.soft_light(papel, _textura_papel(papel.width, papel.height, 10).convert("RGB"))
    papel.paste(foto_r, (borda, borda))
    # fio interno quase invisível entre a foto e o papel (a emulsão não encosta perfeita na borda)
    ImageDraw.Draw(papel).rectangle([borda - 1, borda - 1, borda + foto_r.width, borda + foto_r.height],
                                    outline=cor(c["papel_sombra"]))
    papel = papel.convert("RGBA").rotate(r.uniform(-1.6, 1.6), expand=True, resample=Image.BICUBIC)
    x, y = (w - papel.width) // 2 + int(w * r.uniform(-0.02, 0.02)), (h - papel.height) // 2
    base = fundo.convert("RGBA")
    for desloc, raio, opac in ((borda * 0.4, borda * 0.6, 0.55), (borda * 2.2, borda * 4, 0.45)):
        sombra = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        alfa = papel.split()[3].point(lambda a, o=opac: int(a * o))
        sombra.paste(Image.new("RGBA", papel.size, (0, 0, 0, 255)), (x + int(desloc * 0.4), y + int(desloc)), alfa)
        base.alpha_composite(sombra.filter(ImageFilter.GaussianBlur(raio)))
    base.alpha_composite(papel, (x, y))
    base.convert("RGB").save(destino, quality=95)
    # onde a foto ficou dentro da moldura (frações; ignora a rotação de ±1,6°): as marcações (marcas.py) usam
    cx, cy = x + papel.width / 2, y + papel.height / 2
    destino.with_suffix(".json").write_text(json.dumps({"rect": [(cx - foto_r.width / 2) / w, (cy - foto_r.height / 2) / h,
                                                                 foto_r.width / w, foto_r.height / h]}), encoding="utf-8")
    return destino


# ---------------------------------------------------------------- destaque (texto cinético)
def destaque_animado(texto: str, pasta: Path, w: int, h: int, fps: int, ti: float, tf: float, dur_total: float,
                     tempos: list[float | None] | None = None) -> tuple[Path, int, int]:
    """2–5 palavras grandes no terço inferior-central, cada uma subindo pela máscara no instante em que é
    dita (tempos[i], relativo a ti; None = escalonado). **palavra** sai na cor secundária. Retorna (ffconcat, x, y)."""
    tk = tokens()
    f = fonte("titulo", int(h * 0.11))
    palavras = texto.split()
    destaque = [w_.startswith("**") or w_.endswith("**") for w_ in palavras]
    limpas = [w_.strip("*") for w_ in palavras]
    imgs = [img_texto(p_, f, cor(tk["cores"]["secundaria"]) if d else cor(tk["cores"]["texto"])) for p_, d in
            zip(limpas, destaque)]
    esp = int(h * 0.022)
    larg = sum(i.width for i in imgs) + esp * (len(imgs) - 1)
    alt = max(i.height for i in imgs)
    x0, y0 = (w - larg) / 2, h * 0.60
    g = Grafismo(w, h, sombra=(h * 0.02, h * 0.006, 170))
    veu = img_veu(larg + h * 0.06, alt + h * 0.02, h * 0.05, 175, "centro")
    m = veu.info["margem"]
    g.add(Peca(veu, x0 - h * 0.03 - m, y0 - h * 0.01 - m, "fade", 0.0, 0.35, sombra=False))
    x, passo = x0, 0.12
    for k, im in enumerate(imgs):
        t = tempos[k] if tempos and k < len(tempos) and tempos[k] is not None else k * passo
        g.add(Peca(im, x, y0, "subir", max(0.0, t), 0.45, atraso_saida=k * 0.04))
        x += im.width + esp
    g, gx, gy = _recortar(g, int(h * 0.02))
    return exportar_animacao(g, pasta, fps, ti, tf, dur_total, dur_saida=0.35), gx, gy
