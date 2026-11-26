"""Prepara cenas de foto/vídeo para a colagem editorial (render/src/cenas/Colagem.tsx).

Linguagem dos explicativos da BBC News Brasil: a mídia não some — o sujeito é RECORTADO (ISNet, o mesmo
modelo da thumbnail) e posto em P&B sobre fundo de estúdio, com texto gigante atrás, fio com nome + ano,
moldura fina, riscos de película, ícone/ficha e "mapa térmico" numa palavra da narração.

Quando:
  · pedido: visual.colagem = true | {layout, titulo, ano, texto_fundo, termico, icone, ficha, base...}
    (foto OU vídeo; vídeo usa o layout "janela", sem recorte);
  · auto (config render.colagem = "auto"): uma fração (render.colagem_fracao) das FOTOS elegíveis —
    recorte bom (nota ≥ render.colagem_nota_min), ≥ 3 s, nunca duas seguidas, nem logo depois de um
    parallax. visual.colagem = false proíbe.
Textos: nada é inventado. titulo/subtitulo/ano vêm do próprio objeto visual.colagem ou do rótulo da cena
(rotulo pessoa/local/data, já aprovado no storyboard); texto_fundo automático = ano dito na narração.
O rótulo usado pela colagem sai da cena (senão o lower third do montar.py apareceria duplicado).
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from PIL import Image

import estilo
from common import config, log

EXT_IMG = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff"}
EXT_VID = {".mp4", ".mov", ".webm", ".mkv"}
TIPOS = {"stock_imagem", "arquivo_historico", "ia_imagem", "local", "stock_video", "ia_video"}
VERSAO = "1"


def _cfg() -> dict:
    r = config().get("render", {})
    return {"modo": r.get("colagem", "auto"), "fracao": float(r.get("colagem_fracao", 0.4)),
            "nota_min": float(r.get("colagem_nota_min", 0.6))}


def pedido(c) -> dict | None:
    v = c.dado["visual"].get("colagem")
    if v is True:
        return {}
    return dict(v) if isinstance(v, dict) else None


def _recorte(foto: Path, destino: Path) -> dict | None:
    """Recorte RGBA do MESMO tamanho da foto (≤ 2400 px) + caixa normalizada. Cache em destino (.json ao lado)."""
    info = destino.with_suffix(".json")
    if destino.exists() and info.exists():
        return json.loads(info.read_text(encoding="utf-8"))
    import thumbnail
    with Image.open(foto) as im:
        img = im.convert("RGB")
    img.thumbnail((2400, 2400))
    m = thumbnail.Midia(foto.stem, img)
    if m.mascara is None:
        dados = {"nota": 0.0}
    else:
        rgba = img.convert("RGBA")
        rgba.putalpha(m.mascara)
        rgba.save(destino)
        x0, y0, x1, y1 = m.bbox
        dados = {"nota": float(m.nota), "bbox": [round(x0 / img.width, 4), round(y0 / img.height, 4),
                                          round(x1 / img.width, 4), round(y1 / img.height, 4)],
                 "toca_base": bool(m.toca_base), "aspecto": round(img.width / img.height, 4)}
    info.write_text(json.dumps(dados), encoding="utf-8")
    return dados


def _dur_video(arq: Path) -> float:
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(arq)],
                             capture_output=True, text=True, timeout=30).stdout.strip()
        return float(out)
    except (ValueError, subprocess.SubprocessError, OSError):
        return 0.0


def _aspecto_video(arq: Path) -> float:
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                              "-of", "csv=p=0", str(arq)], capture_output=True, text=True, timeout=30).stdout.strip()
        w, h = (int(x) for x in out.split(",")[:2])
        return round(w / h, 4)
    except (ValueError, subprocess.SubprocessError, OSError):
        return 16 / 9


def escolher(ep: Path, cenas: list, fps: int) -> list:
    """Cenas que viram colagem (pedidas + automáticas). Não mexe nas que já viraram parallax/Remotion."""
    cfg = _cfg()
    out, anterior = [], False
    pasta = ep / "build" / "colagem"
    for c in cenas:
        v = c.dado["visual"]
        ok_tipo = v["tipo"] in TIPOS and c.midia is not None
        ped = pedido(c) if ok_tipo else None
        if ped is not None:
            out.append(c)
            anterior = True
            continue
        # pessoa nomeada no rótulo: sempre candidata (é como a colagem apresenta personagens); o resto, sorteio
        pessoa = (c.dado.get("rotulo") or {}).get("tipo") == "pessoa" if isinstance(c.dado.get("rotulo"), dict) else False
        auto = (cfg["modo"] == "auto" and ok_tipo and v.get("colagem") is not False and not anterior
                and c.midia.suffix.lower() in EXT_IMG and c.frames / fps >= 3.0
                and (c.dado.get("movimento") or "auto") == "auto"
                and (pessoa or estilo.rng(c.dado, "colagem").random() < cfg["fracao"]))
        if auto:
            pasta.mkdir(parents=True, exist_ok=True)
            try:
                info = _recorte(c.midia, pasta / f"{c.id}_{int(c.midia.stat().st_mtime)}_recorte.png")
            except Exception as e:  # modelo indisponível etc.: a cena segue normal
                log(f"  {c.id}: colagem auto sem recorte ({e})")
                info = None
            if info and info.get("nota", 0) >= cfg["nota_min"]:
                out.append(c)
                anterior = True
                continue
        anterior = c.dado["visual"]["tipo"] == "parallax"
    return out


_ANO = re.compile(r"\b(1[5-9]\d\d|20\d\d)\b")


def _textos(c, ped: dict) -> tuple[dict, bool]:
    """titulo/subtitulo/ano a partir do pedido ou do rótulo da cena. Devolve (textos, usou_rotulo)."""
    r = c.dado.get("rotulo") if isinstance(c.dado.get("rotulo"), dict) else {}
    t = {k: ped.get(k) for k in ("titulo", "subtitulo", "ano", "texto_fundo") if ped.get(k)}
    usou = False
    if r.get("texto") and not ("titulo" in t or "ano" in t) and ped.get("rotulo", True) is not False:
        usou = True
        if r.get("tipo") == "data":
            anos = _ANO.findall(r["texto"])
            t["ano"] = r["texto"] if len(r["texto"]) <= 18 else (anos[0] if anos else r["texto"])
        else:
            t["titulo"] = r["texto"]
            if r.get("subtitulo"):
                t["subtitulo"] = r["subtitulo"]
            anos = _ANO.findall(r["texto"])
            if r.get("tipo") == "local" and anos:  # "Manaus, c. 1903" → título Manaus, ano 1903
                t["titulo"] = re.sub(r",?\s*(c\.\s*|década de\s*)?" + anos[0] + r".*$", "", r["texto"]).strip(" ,")
                t["ano"] = anos[0]
    elif c.dado.get("texto_tela") and not t and ped.get("rotulo", True) is not False:
        usou = True
        t["titulo"] = c.dado["texto_tela"]
    if "texto_fundo" not in t and ped.get("texto_fundo") is not False:
        anos = _ANO.findall(c.dado.get("narracao", ""))
        if t.get("ano") and _ANO.fullmatch(str(t["ano"])):
            t["texto_fundo"] = t["ano"]
        elif anos:
            t["texto_fundo"] = anos[0]
    if ped.get("texto_fundo") is False:
        t.pop("texto_fundo", None)
    if t.get("texto_fundo") and t.get("ano") == t["texto_fundo"] and t.get("titulo"):
        pass  # ano no fio E gigante atrás: é o padrão da BBC ("1898 / MARIE CURIE")
    return t, usou


def preparar(ep: Path, c) -> None:
    """Converte a cena em tipo 'colagem' para o Remotion (c.dado é copiado; o storyboard não muda)."""
    ped = pedido(c) or {}
    pasta = ep / "build" / "colagem"
    pasta.mkdir(parents=True, exist_ok=True)
    r = estilo.rng(c.dado, "colagem-layout")
    era = estilo.era(c.dado)
    dados: dict = {"pb": era == "historico" if ped.get("pb") is None else bool(ped["pb"])}
    video = c.midia.suffix.lower() in EXT_VID
    imagens = [c.midia]
    if video:
        dados.update(video=True, aspecto=_aspecto_video(c.midia), dur_video=_dur_video(c.midia),
                     inicio_video=float(c.dado["visual"].get("inicio") or 0), layout="janela")
    else:
        info = _recorte(c.midia, pasta / f"{c.id}_{int(c.midia.stat().st_mtime)}_recorte.png") or {}
        rec = pasta / f"{c.id}_{int(c.midia.stat().st_mtime)}_recorte.png"
        layout = ped.get("layout", "auto")
        recortavel = info.get("nota", 0) >= 0.45 and rec.exists()
        if layout in (None, "auto"):
            rot = c.dado.get("rotulo") if isinstance(c.dado.get("rotulo"), dict) else {}
            if not recortavel:
                layout = "janela"
            elif rot.get("tipo") == "pessoa":  # gente: retrato (texto atrás da cabeça) ou círculo na cabeça
                layout = "retrato" if info.get("toca_base") and r.random() < 0.65 else "circulo"
            else:  # coisa/lugar/grupo: objeto sobre retângulo; foto que encosta na base pode virar retrato
                layout = "retrato" if info.get("toca_base") and r.random() < 0.4 else "objeto"
        if layout != "janela" and recortavel:
            imagens.append(rec)
            dados.update(bbox=info["bbox"], toca_base=info["toca_base"])
        elif layout != "janela":
            log(f"  {c.id}: colagem {layout} sem recorte confiável (nota {info.get('nota', 0)}) — usando janela")
            layout = "janela"
        dados["aspecto"] = info.get("aspecto") or _aspecto_img(c.midia)
        dados["layout"] = layout
    textos, usou_rotulo = _textos(c, ped)
    if dados["layout"] in ("janela", "circulo") and not ped.get("texto_fundo"):
        textos.pop("texto_fundo", None)  # a janela/o círculo cobririam o texto gigante
    dados.update(textos)
    base = ped.get("base", "auto")
    dados["base"] = ("clara" if r.random() < 0.25 else "escura") if base == "auto" else base
    for k in ("termico", "icone", "ficha", "legenda_fundo", "entrada", "textura", "forma", "reenquadra", "dupla", "dupla_em"):
        if ped.get(k) not in (None, False):
            dados[k] = ped[k]
    novo = {k: v for k, v in c.dado.items() if not (usou_rotulo and k in ("rotulo", "texto_tela"))}
    v = dict(c.dado["visual"])
    v["tipo"] = "colagem"
    v["colagem"] = dados
    novo["visual"] = v
    c.dado = novo
    c.extras["imagens_remotion"] = imagens
    c.extras["movimento"] = "colagem"
    log(f"  {c.id}: colagem {dados['layout']} ({dados['base']}"
        + (f", {dados.get('titulo') or dados.get('ano')}" if dados.get("titulo") or dados.get("ano") else "") + ")")


def _aspecto_img(arq: Path) -> float:
    with Image.open(arq) as im:
        return round(im.width / im.height, 4)
