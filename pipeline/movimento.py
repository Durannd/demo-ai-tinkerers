"""Câmera sobre imagens paradas: decide o movimento pela composição da imagem e gera o filtro FFmpeg.

Curvas por família (quase-linear, ease-out com atraso, "parado" com micro-deriva), continuidade de vetor
entre cortes secos e punch-in de ênfase (fatores_punch / aplicar_punch). A escolha depende de
- proporção da imagem (panorâmica → pan; vertical → tilt com fundo desfocado);
- onde está o "assunto" (centro de massa de bordas/contraste) → para onde o push-in vai;
- duração da cena → intensidade;
- seed estável da cena → desempate (nunca duas cenas iguais).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageFilter, ImageOps

from estilo import ease, rng, tokens

MOVIMENTOS = ("zoom_in", "zoom_out", "pan_esquerda", "pan_direita", "subir", "descer", "nenhum", "auto", "parallax")


def saliencia(img_path: Path) -> tuple[float, float, float]:
    """(cx, cy, força) em [0,1]: centro de massa das bordas, com peso maior longe das margens."""
    with Image.open(img_path) as im:
        g = ImageOps.grayscale(im).resize((64, 36))
    e = g.filter(ImageFilter.FIND_EDGES)
    px = e.load()
    sx = sy = tot = 0.0
    for y in range(1, 35):
        for x in range(1, 63):
            v = px[x, y] ** 1.5
            sx += v * x
            sy += v * y
            tot += v
    if tot == 0:
        return 0.5, 0.5, 0.0
    cx, cy = sx / tot / 63, sy / tot / 35
    forca = min(1.0, abs(cx - 0.5) * 2 + abs(cy - 0.5) * 2)
    return cx, cy, forca


@dataclass
class Plano:
    tipo: str          # zoom_in | zoom_out | pan_esquerda | pan_direita | subir | descer | nenhum
    z0: float
    z1: float
    fx: float          # foco (0..1) do recorte
    fy: float
    fundo_desfocado: bool = False
    fx0: float | None = None   # foco no início (deriva até fx/fy); None = parado no foco
    fy0: float | None = None
    curva: str = "linear"      # família da curva: linear (quase-linear) | easeout (desacelera) | parado (micro-deriva)
    atraso: float = 0.0        # s até o 1º movimento perceptível (só easeout)


FAMILIAS = ("linear", "easeout", "parado")
OPOSTO = {"zoom_in": "zoom_out", "zoom_out": "zoom_in", "pan_direita": "pan_esquerda",
          "pan_esquerda": "pan_direita", "descer": "subir", "subir": "descer"}


def escolher_curva(cena: dict, anteriores: list[str], automatico: bool = True) -> str:
    """Família da curva da cena (estável pela seed). ~12% 'parado' (só em movimento automático); o resto
    se divide entre quase-linear e ease-out. Nunca 3 cenas seguidas com a mesma família."""
    r = rng(cena, "curva")
    if automatico and r.random() < 0.125 and (not anteriores or anteriores[-1] != "parado"):
        fam = "parado"
    else:
        fam = "easeout" if r.random() < 0.45 else "linear"
    if len(anteriores) >= 2 and anteriores[-1] == anteriores[-2] == fam:
        fam = "easeout" if fam == "linear" else "linear"
    return fam


def conflita(anterior: "Plano | None", tipo: str) -> bool:
    """True se `tipo` inverte o vetor da câmera do plano anterior (zoom_in → zoom_out, pan ← →, tilt ↑ ↓)."""
    return bool(anterior) and OPOSTO.get(anterior.tipo) == tipo


def decidir(cena: dict, img_path: Path, dur: float, w: int, h: int, anterior: Plano | None = None,
            curvas_anteriores: list[str] | None = None) -> Plano:
    """Plano de câmera da cena. `anterior` = plano da cena anterior quando a entrada é corte seco: o vetor
    da câmera não se inverte no corte (zoom_in → zoom_out, pan_esquerda → pan_direita). Movimento pedido
    explicitamente no storyboard é respeitado (sem troca de vetor e sem plano parado)."""
    pedido = cena.get("movimento") or "auto"
    automatico = pedido == "auto"
    familia = escolher_curva(cena, curvas_anteriores or [], automatico)
    plano = _decidir(cena, img_path, dur, w, h, anterior if automatico else None, familia)
    plano.curva = familia
    if familia == "easeout":
        plano.atraso = round(rng(cena, "atraso").uniform(0.1, 0.3), 3)
    return plano


def _decidir(cena: dict, img_path: Path, dur: float, w: int, h: int, anterior: Plano | None, familia: str) -> Plano:
    pedido = cena.get("movimento") or "auto"
    mv = tokens()["movimento"]
    r = rng(cena, "camera")
    with Image.open(img_path) as im:
        iw, ih = im.size
    asp, alvo = iw / ih, w / h
    # intensidade cresce com a duração, dentro dos limites do canal
    amp = min(mv["zoom_max"], max(mv["zoom_min"], 0.03 + 0.009 * dur)) * r.uniform(0.85, 1.15)
    cx, cy, forca = saliencia(img_path)
    vertical = asp < 1.05  # retrato de verdade; 4:3 aceita recorte

    if pedido == "auto":
        if vertical:
            pedido = "zoom_in" if forca > 0.3 else r.choice(["zoom_in", "zoom_out"])
        elif asp < 1.45:
            # 4:3 e afins: o recorte 16:9 sobra na vertical → tilt revela o resto da foto
            pedido = r.choice(["subir", "descer", "zoom_in"]) if forca < 0.3 else "zoom_in"
        elif asp > alvo * 1.35:
            # panorâmica: anda no sentido de onde está o assunto (termina nele)
            pedido = "pan_direita" if cx > 0.5 else "pan_esquerda"
        elif forca > 0.25:
            pedido = "zoom_in"          # há um assunto claro: aproxima dele
        else:
            pedido = r.choice(["zoom_in", "zoom_out", "pan_direita" if cx >= 0.5 else "pan_esquerda"])
    if pedido == "parallax":  # sem camadas de profundidade ainda → aproximação 2D
        pedido = "zoom_in"
    if conflita(anterior, pedido):
        # mantém o vetor da cena anterior; pan/tilt sem sobra no eixo vira push-in
        pedido = anterior.tipo
        if pedido in ("pan_esquerda", "pan_direita") and not asp > alvo * 1.08:
            pedido = "zoom_in"
        elif pedido in ("subir", "descer") and not asp < alvo * 0.92:
            pedido = "zoom_in"
    if familia == "parado":
        # plano parado deliberado: micro-deriva de ~1% no sentido do zoom da cena anterior (ou aproximando)
        tipo = "zoom_out" if anterior and anterior.tipo == "zoom_out" else "zoom_in"
        fx = 0.5 + (cx - 0.5) * 0.4
        fy = 0.5 + (cy - 0.5) * 0.4
        a, b = 1.02, 1.03
        return Plano(tipo, a, b, fx, fy, vertical) if tipo == "zoom_in" else Plano(tipo, b, a, fx, fy, vertical)

    if pedido in ("zoom_in", "zoom_out"):
        a, b = 1.0, 1.0 + amp
        # foco puxado para o assunto, mas sem exagero (evita recorte esquisito)
        fx = 0.5 + (cx - 0.5) * 0.7
        fy = 0.5 + (cy - 0.5) * 0.7
        # deriva lateral junto com o zoom: a câmera "procura" o assunto (zoom_in) ou se afasta dele (zoom_out)
        dx = r.uniform(0.18, 0.32) * r.choice([-1, 1]) if forca < 0.15 else (0.5 - fx) * 1.2
        dy = r.uniform(-0.08, 0.08)
        ini = (min(1, max(0, fx + dx)), min(1, max(0, fy + dy)))
        if pedido == "zoom_in":
            return Plano(pedido, a, b, fx, fy, vertical, *ini)
        return Plano(pedido, b, a, ini[0], ini[1], vertical, fx, fy)
    if pedido in ("pan_esquerda", "pan_direita", "subir", "descer"):
        z = 1.0 + max(mv["pan_min"], min(mv["pan_max"], amp + 0.02))
        return Plano(pedido, z, z, 0.5, 0.5 + (cy - 0.5) * 0.5, vertical)
    return Plano("nenhum", 1.02, 1.02, 0.5, 0.5, vertical)


def filtro(plano: Plano, frames: int, w: int, h: int, fps: int, img_path: Path) -> tuple[str, bool]:
    """Filtro FFmpeg (entrada: imagem em [0:v]) → vídeo w×h com o movimento do plano.

    Retorna (filtro, precisa_loop). precisa_loop=True → a entrada deve ser "-loop 1 -framerate fps".
    - zoom: zoompan com supersampling 2× (evita o "tremido" do ken burns no FFmpeg);
    - pan/tilt com sobra real na imagem: crop animado sobre a foto inteira (revela o que o recorte esconderia).
    """
    W, H = w * 2, h * 2
    n = max(1, frames - 1)
    with Image.open(img_path) as im:
        iw, ih = im.size
    asp = iw / ih
    dur = frames / fps

    if plano.tipo in ("pan_esquerda", "pan_direita") and asp > w / h * 1.08:
        sw = round(H * asp / 2) * 2                    # largura da foto escalada para altura H
        curso = min(sw - W, int(W * 0.45))             # não atravessa panorâmicas gigantes em 5 s
        x0 = int(max(0, min(sw - W - curso, plano.fx * sw - W / 2 - curso / 2)))
        t = ease(f"min(1,t/{dur:.3f})")
        sentido = t if plano.tipo == "pan_direita" else f"(1-{t})"
        return (f"[0:v]scale={sw}:{H},crop={W}:{H}:x='{x0}+{curso}*{sentido}':y=0,scale={w}:{h}:flags=lanczos,"
                f"fps={fps}", True)
    if plano.tipo in ("subir", "descer") and asp < w / h * 0.92 and not plano.fundo_desfocado:
        sh = round(W / asp / 2) * 2
        curso = min(sh - H, int(H * 0.45))
        y0 = int(max(0, min(sh - H - curso, plano.fy * sh - H / 2 - curso / 2)))
        t = ease(f"min(1,t/{dur:.3f})")
        sentido = t if plano.tipo == "descer" else f"(1-{t})"
        return (f"[0:v]scale={W}:{sh},crop={W}:{H}:x=0:y='{y0}+{curso}*{sentido}',scale={w}:{h}:flags=lanczos,"
                f"fps={fps}", True)
    if plano.tipo in ("subir", "descer", "pan_esquerda", "pan_direita"):
        # sem sobra no eixo: vira um push-in suave na direção pedida
        plano = Plano("zoom_in", 1.0, plano.z0, {"pan_esquerda": 0.35, "pan_direita": 0.65}.get(plano.tipo, 0.5),
                      {"subir": 0.35, "descer": 0.65}.get(plano.tipo, 0.5), plano.fundo_desfocado)

    t = ease(f"on/{n}")
    z = f"{plano.z0:.4f}+({plano.z1:.4f}-{plano.z0:.4f})*{t}"
    x = f"(iw-iw/zoom)*{plano.fx:.3f}"
    y = f"(ih-ih/zoom)*{plano.fy:.3f}"
    zp = f"zoompan=z='{z}':x='{x}':y='{y}':d={frames}:s={w}x{h}:fps={fps}"
    if plano.fundo_desfocado:
        # retrato: fundo é a própria foto desfocada e escurecida; a foto inteira fica no centro
        return (f"[0:v]split=2[a][b];"
                f"[a]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},boxblur=40:2,"
                f"eq=brightness=-0.12:saturation=0.7[fundo];"
                f"[b]scale=-2:{int(H * 0.92)}[frente];"
                f"[fundo][frente]overlay=(W-w)/2:(H-h)/2,{zp}", False)
    return f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},{zp}", False


# ---------------------------------------------------------------- render subpixel (OpenCV)
def _curva(n: int, familia: str = "linear", atraso_q: int = 0):
    """Progresso 0..1 por quadro.
    - linear/parado: quase velocidade constante (o olho lê como câmera), com pontas suavizadas. Smootherstep
      puro para e arranca em cada corte e dá a sensação de 'tranco'.
    - easeout: a câmera entra andando e desacelera até parar (velocidade ∝ (1-u)², com rampa de 10% para
      não arrancar num degrau); espera `atraso_q` quadros antes do 1º movimento."""
    import numpy as np
    if familia != "easeout":
        t = np.linspace(0, 1, n)
        suave = t * t * t * (t * (t * 6 - 15) + 10)
        return 0.8 * t + 0.2 * suave
    atraso_q = max(0, min(atraso_q, n // 4))
    m = n - atraso_q
    if m < 3:
        return np.linspace(0, 1, n)
    u = (np.arange(m) + 0.5) / m
    r = np.clip(u / 0.1, 0, 1)
    v = r * r * (3 - 2 * r) * (1 - u) ** 2
    k = np.concatenate([[0.0], np.cumsum(v)[:-1]])
    k = k / k[-1]
    return np.concatenate([np.zeros(atraso_q), k])


def fatores_punch(n: int, fps: int, tempos: list[float] | None, forca: float = 1.09, quadros: int = 4):
    """Multiplicador de zoom por quadro para punch-ins: 1,00 → `forca` em `quadros` quadros (ease-out
    cúbico) a partir de cada tempo (s, relativo ao 1º quadro do clipe), e fica. Vários punches se acumulam.
    API pública: o futuro campo `enfase` do storyboard só precisa virar uma lista de tempos aqui."""
    import numpy as np
    f = np.ones(n)
    for t in sorted(tempos or []):
        q0 = int(round(t * fps))
        if q0 >= n:
            continue
        i = np.arange(max(0, q0), n)
        x = np.clip((i - q0 + 1) / quadros, 0, 1)
        f[i] *= 1 + (forca - 1) * (1 - (1 - x) ** 3)
    return f


def aplicar_punch(entrada: Path, saida: Path, w: int, h: int, fps: int, fatores, args_saida: list[str],
                  congelar: int | None = None) -> Path:
    """Punch-in num vídeo já em w×h (vídeo de banco normalizado): zoom central subpixel quadro a quadro
    (OpenCV) com os fatores dados; quadros com fator 1 passam intactos. `congelar` = índice do quadro em que o
    vídeo para (freeze-frame): dali em diante repete esse quadro (o zoom continua valendo por cima)."""
    import subprocess

    import cv2
    import numpy as np

    n = len(fatores)
    dec = subprocess.Popen(["ffmpeg", "-v", "error", "-i", str(entrada), "-f", "rawvideo", "-pix_fmt", "bgr24",
                            "-s", f"{w}x{h}", "-"], stdout=subprocess.PIPE)
    enc = subprocess.Popen(["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{w}x{h}",
                            "-r", str(fps), "-i", "-", *args_saida, "-an", str(saida)], stdin=subprocess.PIPE)
    tam = w * h * 3
    try:
        i, parado = 0, None
        while True:
            buf = dec.stdout.read(tam)
            if len(buf) < tam:
                break
            q = np.frombuffer(buf, np.uint8).reshape(h, w, 3)
            if congelar is not None and i >= congelar:
                if parado is None:  # quadro congelado: 30% dessaturado (o olho lê "pausa")
                    cinza = cv2.cvtColor(cv2.cvtColor(q, cv2.COLOR_BGR2GRAY), cv2.COLOR_GRAY2BGR)
                    parado = cv2.addWeighted(q, 0.7, cinza, 0.3, 0)
                q = parado
            f = float(fatores[min(i, n - 1)])
            if f > 1.0001:
                s = 1 / f
                M = np.array([[s, 0, (w - w * s) / 2 + 0.5 * s - 0.5], [0, s, (h - h * s) / 2 + 0.5 * s - 0.5]])
                q = cv2.warpAffine(q, M, (w, h), flags=cv2.INTER_CUBIC | cv2.WARP_INVERSE_MAP,
                                   borderMode=cv2.BORDER_REFLECT)
            enc.stdin.write(q.tobytes())
            i += 1
    finally:
        enc.stdin.close()
        dec.stdout.close()
        dec.wait()
        if enc.wait() != 0:
            raise RuntimeError(f"ffmpeg falhou ao gravar {saida}")
    return saida


def _fonte(plano: Plano, img_path: Path, w: int, h: int, zmax: float):
    """Imagem de origem (numpy BGR) já reduzida para ~1,3× a resolução útil — o warp então quase não reamostra.
    Devolve (imagem, retângulo da foto dentro dela em px: x, y, largura, altura) — as marcações (marcas.py)
    usam o retângulo para seguir a câmera."""
    import numpy as np
    with Image.open(img_path) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        rect = None
        if plano.fundo_desfocado:
            # retrato: a foto inteira no centro sobre ela mesma desfocada e escurecida
            W, H = int(w * 1.3 * zmax), int(h * 1.3 * zmax)
            fundo = ImageOps.fit(im, (W, H)).resize((W // 8, H // 8)).filter(ImageFilter.GaussianBlur(6)).resize((W, H))
            fundo = Image.eval(fundo, lambda v: int(v * 0.72))
            fh = int(H * 0.92)
            frente = im.resize((max(1, round(im.width * fh / im.height)), fh), Image.LANCZOS)
            fundo.paste(frente, ((W - frente.width) // 2, (H - fh) // 2))
            rect = ((W - frente.width) // 2, (H - fh) // 2, frente.width, fh)
            im = fundo
        else:
            # cobre o quadro na menor dimensão com folga para o zoom máximo
            alvo = max(w / im.width, h / im.height) * 1.3 * zmax
            if alvo < 1:
                im = im.resize((round(im.width * alvo), round(im.height * alvo)), Image.LANCZOS)
        arr = np.asarray(im)[:, :, ::-1].copy()
    return arr, rect or (0, 0, arr.shape[1], arr.shape[0])


def clipe(plano: Plano, frames: int, w: int, h: int, fps: int, img_path: Path, saida: Path, args_saida: list[str],
          punches: list[float] | None = None, forca_punch: float = 1.09, trajeto: list | None = None,
          rect_rel: tuple[float, float, float, float] | None = None) -> Path:
    """Renderiza o movimento quadro a quadro com posição/zoom em ponto flutuante (sem degraus de pixel) e
    entrega um MP4 mezanino. Substitui o zoompan do FFmpeg, que arredonda o recorte para pixels inteiros.
    `trajeto` (lista): recebe, por quadro, (sx, sy, ox, oy) — ponto (x, y) relativo à FOTO (0–1) cai em
    (ox + x·sx, oy + y·sy) na saída. `rect_rel`: onde a foto está dentro de img_path (moldura), em frações."""
    import subprocess

    import cv2
    import numpy as np

    n = max(1, frames)
    pf = fatores_punch(n, fps, punches, forca_punch)
    zmax = max(plano.z0, plano.z1, 1.0) * float(pf.max())
    src, rect = _fonte(plano, img_path, w, h, zmax)
    if rect_rel and not plano.fundo_desfocado:
        rect = (rect_rel[0] * src.shape[1], rect_rel[1] * src.shape[0], rect_rel[2] * src.shape[1],
                rect_rel[3] * src.shape[0])
    ih, iw = src.shape[:2]
    asp = w / h
    vw0 = min(iw, ih * asp)                     # viewport em z=1 (cobre o quadro)
    k = _curva(n, plano.curva, int(round(plano.atraso * fps)))
    pan = plano.tipo in ("pan_esquerda", "pan_direita", "subir", "descer")
    # trajetória do foco
    if pan:
        z = np.full(n, plano.z0)
        vw = vw0 / plano.z0
        vh = vw / asp
        if plano.tipo in ("pan_esquerda", "pan_direita"):
            sobra = iw - vw
            curso = min(sobra, vw * 0.45) / max(sobra, 1e-6)          # fração do curso disponível
            c0 = min(1 - curso, max(0.0, plano.fx - curso / 2))
            a, b = (c0, c0 + curso) if plano.tipo == "pan_direita" else (c0 + curso, c0)
            fx, fy = a + (b - a) * k, np.full(n, plano.fy)
        else:
            sobra = ih - vh
            curso = min(sobra, vh * 0.45) / max(sobra, 1e-6)
            c0 = min(1 - curso, max(0.0, plano.fy - curso / 2))
            a, b = (c0 + curso, c0) if plano.tipo == "subir" else (c0, c0 + curso)
            fx, fy = np.full(n, plano.fx), a + (b - a) * k
    else:
        z = plano.z0 + (plano.z1 - plano.z0) * k
        fx0 = plano.fx if plano.fx0 is None else plano.fx0
        fy0 = plano.fy if plano.fy0 is None else plano.fy0
        fx = fx0 + (plano.fx - fx0) * k
        fy = fy0 + (plano.fy - fy0) * k
    z = z * pf

    saida.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen(["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{w}x{h}",
                             "-r", str(fps), "-i", "-", *args_saida, "-an", str(saida)], stdin=subprocess.PIPE)
    try:
        for i in range(n):
            vw = vw0 / z[i]
            vh = vw / asp
            x0 = (iw - vw) * fx[i]
            y0 = (ih - vh) * fy[i]
            s = vw / w
            # mapa inverso: pixel de saída (u, v) → origem (x0 + (u+.5)·s − .5, ...)
            M = np.array([[s, 0, x0 + 0.5 * s - 0.5], [0, s, y0 + 0.5 * s - 0.5]], dtype=np.float64)
            q = cv2.warpAffine(src, M, (w, h), flags=cv2.INTER_CUBIC | cv2.WARP_INVERSE_MAP,
                               borderMode=cv2.BORDER_REFLECT)
            proc.stdin.write(q.tobytes())
            if trajeto is not None:
                trajeto.append((rect[2] / s, rect[3] / s, (rect[0] - x0) / s, (rect[1] - y0) / s))
    finally:
        proc.stdin.close()
        if proc.wait() != 0:
            raise RuntimeError(f"ffmpeg falhou ao gravar {saida}")
    return saida


def fatores_impacto(n: int, fps: int, impactos: list[tuple[float, bool, bool]]):
    """Por quadro: (dx, dy, zoom, flash). Tremor = chacoalhão curto (~0,35 s, ±1,1% da largura, 11–13 Hz,
    amortecido) com um 'soco' de zoom de 3,5%; flash = estouro de exposição que some em ~0,15 s.
    impactos = [(segundo relativo ao 1º quadro do clipe, tremor, flash)]."""
    import numpy as np
    t = np.arange(n) / fps
    dx, dy, z, fl = np.zeros(n), np.zeros(n), np.ones(n), np.zeros(n)
    for k, (t0, tremor, flash) in enumerate(sorted(impactos)):
        x = t - t0
        ativo = x >= 0
        if tremor:
            env = np.where(ativo, np.exp(-np.clip(x, 0, None) * 11.0), 0.0) * (x < 0.5)
            dx += 0.011 * env * np.sin(2 * np.pi * 11.0 * x + 0.7 * k)
            dy += 0.008 * env * np.sin(2 * np.pi * 13.0 * x + 1.9 + 0.7 * k)
            z += 0.035 * np.where(ativo, np.exp(-np.clip(x, 0, None) * 9.0), 0.0) * (x < 0.6)
        if flash:
            fl += np.where(ativo, 0.6 * np.exp(-np.clip(x, 0, None) / 0.07), 0.0) * (x < 0.4)
    return dx, dy, z, np.clip(fl, 0, 0.85)


def aplicar_impactos(entrada: Path, saida: Path, w: int, h: int, fps: int, impactos: list[tuple[float, bool, bool]],
                     args_saida: list[str]) -> Path:
    """Pós-passe genérico sobre um mezanino w×h (foto, vídeo, cartela ou cena Remotion): tremor e/ou flash
    nos instantes pedidos (som.eventos[].efeito). Quadros fora das janelas passam intactos."""
    import subprocess

    import cv2
    import numpy as np

    dec = subprocess.Popen(["ffmpeg", "-v", "error", "-i", str(entrada), "-f", "rawvideo", "-pix_fmt", "bgr24",
                            "-s", f"{w}x{h}", "-"], stdout=subprocess.PIPE)
    enc = subprocess.Popen(["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{w}x{h}",
                            "-r", str(fps), "-i", "-", *args_saida, "-an", str(saida)], stdin=subprocess.PIPE)
    tam = w * h * 3
    dx, dy, z, fl = fatores_impacto(max(1, int(round(duracao_video(entrada) * fps)) + 2), fps, impactos)
    try:
        i = 0
        while True:
            buf = dec.stdout.read(tam)
            if len(buf) < tam:
                break
            q = np.frombuffer(buf, np.uint8).reshape(h, w, 3)
            k = min(i, len(z) - 1)
            if abs(dx[k]) > 1e-4 or abs(dy[k]) > 1e-4 or z[k] > 1.0001:
                s = 1 / z[k]
                M = np.array([[s, 0, (w - w * s) / 2 + dx[k] * w * s], [0, s, (h - h * s) / 2 + dy[k] * h * s]])
                q = cv2.warpAffine(q, M, (w, h), flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP,
                                   borderMode=cv2.BORDER_REFLECT)
            if fl[k] > 0.004:
                q = cv2.addWeighted(q, 1 - fl[k], np.full_like(q, 255), fl[k], 0)
            enc.stdin.write(np.ascontiguousarray(q).tobytes())
            i += 1
    finally:
        enc.stdin.close()
        dec.stdout.close()
        dec.wait()
        if enc.wait() != 0:
            raise RuntimeError(f"ffmpeg falhou ao gravar {saida}")
    return saida


def duracao_video(arq: Path) -> float:
    import subprocess
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(arq)],
                       capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 600.0
