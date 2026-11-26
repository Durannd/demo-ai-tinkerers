"""Monta o vídeo final: cenas → transições → acabamento (grão, vinheta) → mix de áudio → MP4, SRT, descrição.

Uso:
  python pipeline/montar.py <slug>                    # final 1080p (+ final/shorts/)
  python pipeline/montar.py <slug> --sem-shorts       # final sem gerar os Shorts
  python pipeline/montar.py <slug> --rascunho         # 720p rápido, aceita mídia faltando (placeholder)
  python pipeline/montar.py <slug> --trecho 0:30-1:30 # só uma janela (para ajustar rápido)

Como funciona
  1. Cada cena vira um MP4 "mezanino" em build/cenas/ (cache por hash). Se a cena entra ou sai com
     transição, ela é renderizada com "alças" (meia transição antes/depois) para o xfade não roubar tempo.
  2. As cenas são agrupadas em blocos (cortados sempre num corte seco). Cada bloco recebe as transições
     (xfade) e o acabamento global (tratamento → grão → vinheta) e é codificado no formato final (cache por hash).
     Rótulos, destaques e CTAs (inscrever/like/comentar, pipeline/cta.py) entram só aqui, por cima do
     acabamento; no final o bloco sai também SEM eles (bloco_NNN_limpo.mp4), fonte dos Shorts.
  3. Os blocos são concatenados sem recodificar e o áudio (voz + música com ducking + SFX) é mixado.
  4. Final: Shorts (shorts.gerar) a partir da versão limpa, que é apagada depois (--sem-shorts pula;
     config.shorts.auto). config.render.limpar_build apaga os intermediários pesados no fim.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image

import cta
import objetos
import estilo
import graficos
import i18n
import marcas
import movimento
import colagem
import parallax
import musica
import remotion
import thumbnail
import som
from common import RAIZ, checar_ffmpeg, config, duracao, ler_json, ler_storyboard, log, pasta_episodio, rodar, salvar_json

VERSAO_RENDER = "3-" + hashlib.sha1((Path(__file__).parent / "graficos.py").read_bytes()).hexdigest()[:8]  # muda com graficos.py
EXT_IMG = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff"}
EXT_VID = {".mp4", ".webm", ".ogv", ".mov", ".mkv"}
TIPOS_COM_MIDIA = {"stock_video", "stock_imagem", "arquivo_historico", "ia_imagem", "ia_video", "local", "foto", "video"}
XFADE = {"dissolve": "fade", "escuro": "fadeblack", "whip": "hblur", "flash": "fadewhite", "foco": "fade",
         "luz": "fade", "zoom": "fade",
         # equivalentes xfade das dinâmicas (usados onde não há OpenCV, ex.: Shorts)
         "forma": "circleopen", "cortina": "horzopen", "fatias": "hlslice", "mosaico": "pixelize", "cor": "fadewhite"}
# renderizadas quadro a quadro em OpenCV (transicao_cv), não por xfade
TRANSICAO_CV = {"whip", "foco", "luz", "zoom", "forma", "cortina", "fatias", "mosaico", "cor"}
ESPECIAIS = {"escuro", "whip", "flash", "foco", "luz", "zoom"}
# dinâmicas (linguagem da colagem): o 'auto' escolhe de vez em quando nos cortes (render.transicao_dinamica_*)
DINAMICAS = ("forma", "cortina", "fatias", "mosaico", "cor")
# duração padrão em s (config render.transicao_<nome>); luz/zoom só por pedido explícito no storyboard
TRANSICAO_PADRAO = {"luz": 0.9, "zoom": 0.5, "forma": 0.7, "cortina": 0.6, "fatias": 0.55, "mosaico": 0.8, "cor": 0.55}
LEGADO_TRANSICAO = {"fade": "dissolve"}
MAX_CENAS_BLOCO = 12
VERSAO_MOVIMENTO = hashlib.sha1((Path(__file__).parent / "movimento.py").read_bytes()).hexdigest()[:8]


@dataclass
class Cena:
    dado: dict
    midia: Path | None
    frames: int                 # duração no tempo do vídeo (narração + pausa)
    inicio: float = 0.0
    entrada: str = "corte"      # transição com a cena anterior
    alca_antes: int = 0         # quadros extras renderizados antes (metade da transição de entrada)
    alca_depois: int = 0
    arquivo: Path | None = None
    hash: str = ""
    extras: dict = field(default_factory=dict)

    @property
    def id(self) -> str:
        return self.dado["id"]

    @property
    def total(self) -> int:
        return self.alca_antes + self.frames + self.alca_depois


# ---------------------------------------------------------------- mídia
def achar_midia(ep: Path, cena: dict) -> Path | None:
    arq = cena["visual"].get("arquivo")
    if arq:
        p = Path(arq)
        for base in (p, ep / p, RAIZ / p):
            if base.exists():
                return base
        return None
    for p in sorted((ep / "midia").glob(f"{cena['id']}.*")):
        if p.suffix.lower() in EXT_IMG | EXT_VID:
            return p
    return None


def quadro_de(midia: Path | None, build: Path) -> Path | None:
    """Imagem representativa de uma mídia (para fundo de cartela)."""
    if not midia:
        return None
    if midia.suffix.lower() in EXT_IMG:
        return midia
    destino = build / f"{midia.stem}_quadro.jpg"
    if not destino.exists():
        try:
            rodar(["ffmpeg", "-y", "-v", "error", "-ss", "1", "-i", str(midia), "-frames:v", "1", str(destino)])
        except RuntimeError:
            return None
    return destino


def vizinhas(ep: Path, c: "Cena", cenas: list["Cena"]) -> tuple[Path | None, list[Path]]:
    """Para cenas animadas: (fundo, imagens próprias). Fundo = mídia da cena seguinte (capítulo apresenta
    o que vem) ou a mais próxima; imagens = mídia da própria cena (retrato da citação etc.)."""
    if c.extras.get("imagens_remotion"):
        return None, list(c.extras["imagens_remotion"])
    i = cenas.index(c)
    ordem = cenas[i + 1:i + 3] + cenas[max(0, i - 2):i][::-1]
    if c.dado["visual"]["tipo"] != "capitulo":
        ordem = cenas[max(0, i - 1):i] + cenas[i + 1:i + 2] + ordem
    build = ep / "build" / "cenas"
    build.mkdir(parents=True, exist_ok=True)
    fundo = next((quadro_de(x.midia, build) for x in ordem if x.midia and x.dado["visual"]["tipo"] in TIPOS_COM_MIDIA), None)
    proprias = [m for m in [c.midia] if m]
    if c.dado["visual"]["tipo"] == "comparacao":
        comp = c.dado["visual"].get("comparacao") or {}
        proprias = []
        for lado in ("a", "b"):
            arq = (comp.get(lado) or {}).get("arquivo")
            achado = achar_midia(ep, {"id": f"{c.id}_{lado}", "visual": {"arquivo": arq} if arq else {}})
            if achado:
                proprias.append(achado)
    proprias += [p for p in (Path(x) for x in c.dado["visual"].get("imagens", [])) if p.exists()]
    return fundo, [quadro_de(m, build) for m in proprias if quadro_de(m, build)]


def cartela_substituta(cena: dict) -> dict:
    """Sem Node/Remotion: a cena animada vira uma cartela estática com o essencial."""
    v = cena["visual"]
    d = v.get(v["tipo"]) or {}
    if v["tipo"] == "numero":
        valor = d.get("valor", "")
        txt = i18n.numero(valor, 0 if float(valor).is_integer() else 1) if isinstance(valor, (int, float)) else str(valor)
        txt = f"{d.get('prefixo', '')}{txt} {d.get('unidade', '')}".strip()
    elif v["tipo"] == "capitulo":
        txt = d.get("titulo") or v.get("titulo", "")
    elif v["tipo"] == "domino":
        if d.get("modo") == "recapitulacao":
            txt = " → ".join(p.get("titulo", "") for p in d.get("pecas") or [] if p.get("titulo"))[:120]
        else:
            txt = f"{i18n.t('peca')} {d.get('numero', '')} · " + " — ".join(x for x in (d.get("data"), d.get("titulo")) if x)
    elif v["tipo"] == "icones":
        txt = d.get("titulo") or " · ".join(x.get("rotulo") or x.get("texto", "") for x in
                                            (d.get("itens") or d.get("fichas") or [])) or cena.get("narracao", "")[:80]
    else:
        txt = d.get("texto") or d.get("titulo") or v.get("texto") or cena.get("narracao", "")[:80]
    return {**cena, "visual": {"tipo": "cartela", "cartela_texto": txt}}


def dividir_em_subcortes(c: dict, meta: dict, frames: int, fps: int) -> list[tuple[dict, int, int]]:
    """[(cena, quadro_inicial, n_quadros)]. Sem 'sub' → a própria cena. Cada sub entra na palavra-âncora
    (ou divide o tempo por igual); partes com menos de 1,2 s são descartadas (corte rápido demais)."""
    subs = c.get("sub") or []
    base = {k: v for k, v in c.items() if k != "sub"}
    if not subs:
        return [(base, 0, frames)]
    palavras = meta.get("palavras") or []

    def norm(x: str) -> str:
        import unicodedata
        x = unicodedata.normalize("NFD", x.lower())
        return "".join(ch for ch in x if ch.isalnum())

    cortes = []
    for k, sub in enumerate(subs, 1):
        alvo = norm((sub.get("ancora") or "").split(" ")[0])
        t = next((w["ini"] for w in palavras if alvo and norm(w["texto"]).startswith(alvo)), None)
        if t is None:
            t = meta["duracao"] * k / (len(subs) + 1)
        cortes.append((round(t * fps), k, sub))
    cortes.sort(key=lambda x: x[0])
    out, ini, atual = [], 0, base
    minimo = int(1.2 * fps)
    for q, k, sub in cortes:
        if q - ini < minimo or frames - q < minimo:
            continue
        out.append((atual, ini, q - ini))
        atual = {**base, "id": f"{c['id']}_s{k}", "visual": sub["visual"], "movimento": sub.get("movimento", "auto"),
                 "transicao": sub.get("transicao", "corte"), "rotulo": sub.get("rotulo"), "texto_tela": None,
                 "era": sub.get("era", c.get("era"))}
        ini = q
    out.append((atual, ini, frames - ini))
    return out


# ---------------------------------------------------------------- transições
def duracoes_transicao() -> dict[str, float]:
    """Duração (s) de cada transição: config.render.transicao_* + tokens da marca (também usada pelos Shorts)."""
    rcfg = config().get("render", {})
    return {"foco": rcfg.get("transicao_foco", 0.6), **{k: rcfg.get(f"transicao_{k}", v) for k, v in TRANSICAO_PADRAO.items()},
            **estilo.tokens()["transicoes"]}


def decidir_transicoes(cenas: list[Cena], fps: int, versao2: bool = False) -> None:
    """Transição de ENTRADA de cada cena. Explícita no storyboard vence; 'auto' segue a gramática do canal:
    corte seco é o padrão; dissolve quando muda a 'era' da imagem; mergulho no escuro na troca de bloco;
    nunca a mesma transição especial duas vezes seguidas. 'foco' (rack focus) substitui parte dos dissolves
    de troca de era. Transições especiais (escuro, whip, flash, foco) escolhidas automaticamente respeitam
    no mínimo ~8 s entre si e no máximo 3 tipos especiais no vídeo (as pedidas no storyboard contam, mas vencem)."""
    rcfg = config().get("render", {})
    dur = duracoes_transicao()
    intervalo = rcfg.get("intervalo_transicao_especial", 8)
    max_tipos = rcfg.get("max_tipos_transicao_especial", 3)
    prob_din = rcfg.get("transicao_dinamica_prob", 0.35)
    intervalo_din = rcfg.get("transicao_dinamica_intervalo", 5)
    ultima, t_especial, tipos = "corte", -1e9, set()
    t_din, ultima_din = -1e9, None

    def pode(tipo: str, t: float) -> bool:
        return t - t_especial >= intervalo and (tipo in tipos or len(tipos) < max_tipos)

    for i, c in enumerate(cenas):
        if i == 0:
            c.entrada = "corte"
            continue
        pedido = LEGADO_TRANSICAO.get(c.dado.get("transicao"), c.dado.get("transicao") or "auto")
        if not versao2 and pedido == "corte":
            pedido = "auto"  # na v1 o roteirista marcava "corte" em tudo por padrão
        a, b = cenas[i - 1].dado, c.dado
        if pedido == "auto" or pedido not in ("corte", *XFADE):
            if a.get("bloco") and b.get("bloco") and a["bloco"] != b["bloco"]:
                pedido = "escuro" if pode("escuro", c.inicio) else "dissolve"
            elif estilo.era(a) != estilo.era(b) and "grafico" not in (estilo.era(a), estilo.era(b)):
                pedido = "dissolve"
                if estilo.rng(b, "foco").random() < 0.4 and pode("foco", c.inicio):
                    pedido = "foco"
            else:
                pedido = "corte"
            # parte dos cortes e dissolves (e metade da chance nas trocas de bloco) vira transição dinâmica
            # (forma, cortina, fatias, mosaico), nunca a mesma duas vezes seguidas
            rr = estilo.rng(b, "dinamica")
            chance = prob_din * (0.5 if pedido == "escuro" else 1.0)
            if pedido in ("corte", "dissolve", "escuro") and c.inicio - t_din >= intervalo_din and rr.random() < chance:
                opcoes = [x for x in DINAMICAS if x != ultima_din]
                pedido = opcoes[int(rr.random() * len(opcoes)) % len(opcoes)]
            if pedido == ultima and pedido != "corte":
                pedido = "dissolve" if pedido != "dissolve" else "corte"
        c.entrada = pedido
        ultima = pedido
        if pedido in DINAMICAS:
            t_din, ultima_din = c.inicio, pedido
        if pedido in ESPECIAIS:
            t_especial = c.inicio
            tipos.add(pedido)
        if pedido != "corte":
            meia = max(2, round(dur[pedido] * fps / 2))
            # transição não pode comer mais que 1/3 de nenhuma das cenas
            meia = min(meia, cenas[i - 1].frames // 3, c.frames // 3)
            if meia < 2:
                c.entrada = "corte"
                continue
            cenas[i - 1].alca_depois = meia
            c.alca_antes = meia


# ---------------------------------------------------------------- render de cena
def assinatura(*partes) -> str:
    return hashlib.sha1(json.dumps([VERSAO_RENDER, *partes], sort_keys=True, default=str).encode()).hexdigest()


def texto_rotulo(cena: dict) -> str | None:
    r = cena.get("rotulo")
    return (r.get("texto") if isinstance(r, dict) else None) or cena.get("texto_tela")


def _overlay_tratado(idx: int, ultimo: str, x: float, y: float, fps: int, saida: str, nome: str,
                     tratamento: str | None) -> list[str]:
    """Overlay de uma animação RGBA. Com `tratamento` (cor por era da cena), a camada recebe o MESMO grade de
    cor que o mezanino recebia quando o rótulo era queimado nele (RGB tratado; alfa preservado à parte)."""
    if not tratamento or tratamento == "null":
        return graficos.filtro_overlay(idx, ultimo, x, y, fps, saida, nome)
    return [f"[{idx}:v]fps={fps},format=rgba,setpts=PTS-STARTPTS,split[{nome}c][{nome}a]",
            f"[{nome}a]alphaextract[{nome}m]",
            f"[{nome}c]format=yuv444p,{tratamento},format=rgb24[{nome}t]",
            f"[{nome}t][{nome}m]alphamerge,format=rgba[{nome}]",
            f"{ultimo}[{nome}]overlay=x={round(x)}:y={round(y)}:eof_action=pass:format=auto{saida}"]


def camada_rotulo(c, build: Path, entradas: list, camadas: list, ultimo: str, w: int, h: int, fps: int,
                  t0: float, t1: float, dur_total: float | None = None, sufixo: str = "",
                  tratamento: str | None = None) -> str:
    """Acrescenta o rótulo (lower third) animado ao filtro; devolve o nome da camada resultante.
    A animação (máscara/stagger na entrada e na saída) vem pronta do graficos.rotulo_animado.
    t0/t1 = início/fim do corpo da cena no relógio do filtro (cena isolada ou bloco)."""
    cena = c.dado
    txt = texto_rotulo(cena)
    if not txt:
        return ultimo
    r = cena.get("rotulo") if isinstance(cena.get("rotulo"), dict) else {}
    tipo = graficos.tipo_rotulo(txt, r.get("tipo"))
    ti, tf = t0 + 0.45, max(t0 + 1.2, t1 - 0.6)
    lista, x, y = graficos.rotulo_animado(txt, build / f"{c.id}_rotulo_anim", w, h, fps, ti, tf,
                                          dur_total or c.total / fps, tipo, r.get("subtitulo", ""))
    idx = len([a for a in entradas if a == "-i"])
    entradas += graficos.args_entrada(lista)
    camadas += _overlay_tratado(idx, ultimo, x, y, fps, f"[vr{sufixo}]", f"rot{sufixo}", tratamento)
    return f"[vr{sufixo}]"


def camada_destaque(c, build: Path, entradas: list, camadas: list, ultimo: str, w: int, h: int, fps: int,
                    t0: float, t1: float, dur_total: float | None = None, sufixo: str = "",
                    tratamento: str | None = None) -> str:
    """Texto cinético (cena.destaque): entra na palavra-âncora e cada palavra sobe quando é dita.
    Em cena com sub-cortes, aparece só na parte onde a âncora é falada."""
    dq = c.dado.get("destaque")
    if not dq or not dq.get("texto"):
        return ultimo
    dur = c.frames / fps
    ini = tempo_palavra(c, dq["ancora"]) if dq.get("ancora") else 0.3
    if ini is None or ini < 0 or ini > dur - 1.0:
        return ultimo
    pal = (c.extras.get("meta") or {}).get("palavras", [])
    tempos = []
    for w_ in dq["texto"].split():
        alvo = _norm_palavra(w_.strip("*"))
        t = next((p["ini"] for p in pal if len(alvo) >= 3 and p["ini"] >= ini - 0.05
                  and _norm_palavra(p["texto"]).startswith(alvo[:5])), None)
        tempos.append(None if t is None else max(0.0, t - ini))
    # palavras não ditas entram logo após a anterior
    for k in range(len(tempos)):
        if tempos[k] is None:
            tempos[k] = (tempos[k - 1] + 0.12) if k else 0.0
    ti = t0 + max(0.1, ini - 0.08)
    tf = min(t1 - 0.4, ti + max(2.2, (tempos[-1] if tempos else 0) + 1.6))
    lista, x, y = graficos.destaque_animado(dq["texto"], build / f"{c.id}_destaque", w, h, fps, ti, tf,
                                            dur_total or c.total / fps, tempos)
    idx = len([a for a in entradas if a == "-i"])
    entradas += graficos.args_entrada(lista)
    camadas += _overlay_tratado(idx, ultimo, x, y, fps, f"[vd{sufixo}]", f"dest{sufixo}", tratamento)
    return f"[vd{sufixo}]"


def tem_overlay(c) -> bool:
    dq = c.dado.get("destaque")
    return bool(texto_rotulo(c.dado) or (dq and dq.get("texto")))


def assinatura_overlay(c) -> list:
    """O que muda os overlays de uma cena (entra no hash do bloco, não do mezanino)."""
    if not tem_overlay(c):
        return []
    return [c.dado.get("rotulo"), c.dado.get("texto_tela"), c.dado.get("destaque"),
            (c.extras.get("meta") or {}).get("palavras") if c.dado.get("destaque") else None,
            tratamento_overlay(c)]


def tratamento_overlay(c) -> str | None:
    """Grade de cor que o rótulo recebia quando era queimado no mezanino (cartela/placeholder/Remotion: nenhum)."""
    tipo = c.dado["visual"]["tipo"]
    if tipo in remotion.TIPOS or tipo == "cartela" or c.midia is None:
        return None
    return estilo.filtro_tratamento(c.dado)


# chaves que só afetam os overlays (aplicados no bloco): fora do hash do mezanino
CHAVES_OVERLAY = ("rotulo", "texto_tela", "destaque")


_CAMERA_LOCK = threading.Lock()
PALAVRAS_FRACAS = {"porque", "quando", "depois", "antes", "também", "sobre", "entre", "ainda", "estava", "tinha",
                   "foram", "seria", "isso", "essa", "esse", "aquele", "aquela", "mesmo", "muito", "onde", "como",
                   "nunca", "sempre", "então", "pelos", "pelas", "deles", "delas", "nossa", "nosso", "outro", "outra"}


def _norm_palavra(x: str) -> str:
    import unicodedata
    x = unicodedata.normalize("NFD", x.lower())
    return "".join(ch for ch in x if ch.isalnum())


def tempo_enfase(c: Cena, fps: int, freq: dict) -> float | None:
    """Segundo (relativo ao início do corpo da cena) da palavra de ênfase: a mais longa/rara da 2ª metade
    da narração da cena. Campo `enfase` (lista de segundos) no storyboard tem prioridade."""
    explicito = c.dado.get("enfase")
    if isinstance(explicito, list) and explicito and isinstance(explicito[0], dict):
        # storyboard v2: [{"em": "palavra", "escala": 1.1}] → tempo da palavra nesta (sub)cena
        for e in explicito:
            alvo = _norm_palavra(e.get("em", "").split()[0] if e.get("em") else "")
            for p in c.extras.get("meta", {}).get("palavras", []):
                if alvo and _norm_palavra(p["texto"]).startswith(alvo) and 0 <= p["ini"] <= c.frames / fps:
                    c.extras["enfase_escala"] = e.get("escala")
                    return float(p["ini"])
        return None
    if isinstance(explicito, (int, float)):
        return float(explicito)
    if isinstance(explicito, list) and explicito and isinstance(explicito[0], (int, float)):
        return float(explicito[0])
    dur = c.frames / fps
    melhor, nota = None, 0.0
    for p in c.extras.get("meta", {}).get("palavras", []):
        if not (max(dur / 2, 1.0) <= p["ini"] <= dur - 1.0):
            continue
        n = _norm_palavra(p["texto"])
        if len(n) < 5 or n in PALAVRAS_FRACAS:
            continue
        s = len(n) + (4 if freq.get(n, 0) <= 1 else 2 if freq.get(n, 0) <= 2 else 0) + (3 if n.isdigit() else 0)
        if s > nota:
            melhor, nota = p["ini"], s
    return melhor


def imagem_camera(ep: Path, c: Cena, w: int, h: int) -> Path:
    """Imagem que a câmera vai percorrer (foto pequena vira cópia impressa sobre fundo desfocado)."""
    build = ep / "build" / "cenas"
    build.mkdir(parents=True, exist_ok=True)
    with Image.open(c.midia) as im:
        pequena = im.height < h * 0.75 and im.width < w * 0.75
    if not pequena:
        return c.midia
    c.extras["tratamento"] = "moldura"
    arq = graficos.moldura(c.midia, build / f"{c.id}_moldura.jpg", w * 2, h * 2, c.dado,
                           ampliacao_max=2.0 * 2 * (1080 / h if h < 1080 else 1))
    lado = ler_json(arq.with_suffix(".json"), {})
    if lado.get("rect"):
        c.extras["rect_rel"] = tuple(lado["rect"])   # onde a foto está na moldura (marcações)
    return arq


def _na_parte(c: Cena, expr: str | None, fps: int) -> float | None:
    """Segundo (relativo ao corpo) em que `expr` é dita DENTRO desta parte da cena (sub-cortes), ou None."""
    pal = (c.extras.get("meta") or {}).get("palavras") or []
    t = remotion.achar_na_fala(pal, expr, -0.01)
    return t if t is not None and t <= c.frames / fps else None


def tempo_congelar(c: Cena, fps: int) -> float | None:
    """cena.congelar = {"em": "palavra"}: freeze-frame do vídeo a partir da palavra (só vídeo; só na parte em que
    a palavra é dita; precisa sobrar ≥ 0,4 s de plano)."""
    cg = c.dado.get("congelar")
    if not cg or not eh_video(c):
        return None
    t = _na_parte(c, cg.get("em"), fps)
    return t if t is not None and t <= c.frames / fps - 0.4 else None


def impactos_da_cena(c: Cena, fps: int) -> list[tuple[float, bool, bool]]:
    """[(segundo desde o 1º quadro do clipe, tremor, flash)]: som.eventos[].efeito + flash do congelamento."""
    out = []
    t0 = c.alca_antes / fps
    for e in (c.dado.get("som") or {}).get("eventos") or []:
        ef = e.get("efeito")
        if ef not in ("tremor", "flash", "tremor_flash"):
            continue
        t = _na_parte(c, e.get("em"), fps)
        if t is not None:
            out.append((t0 + t, ef != "flash", ef != "tremor"))
    cg = c.dado.get("congelar") or {}
    t = tempo_congelar(c, fps)
    if t is not None and cg.get("flash", True):
        out.append((t0 + t, False, True))
    return out


def aplicar_impactos(ep: Path, c: Cena, w: int, h: int, fps: int) -> None:
    """Pós-passe (tremor/flash) sobre o mezanino pronto de QUALQUER tipo de cena; cache por hash."""
    imp = impactos_da_cena(c, fps)
    if not imp or not c.arquivo:
        return
    novo = assinatura(c.hash, imp, w, h, fps, VERSAO_MOVIMENTO)
    saida = c.arquivo.with_name(f"{c.id}_impacto.mp4")
    marca = saida.with_suffix(".hash")
    if not (saida.exists() and marca.exists() and marca.read_text() == novo):
        movimento.aplicar_impactos(c.arquivo, saida, w, h, fps, imp, estilo.ARGS_MEZANINO)
        marca.write_text(novo)
    log(f"  impacto {c.id}: " + ", ".join(f"{t:.2f}s{' tremor' if a else ''}{' flash' if b else ''}" for t, a, b in imp))
    c.arquivo, c.hash = saida, novo


def eh_foto(c: Cena) -> bool:
    return bool(c.midia) and c.midia.suffix.lower() in EXT_IMG and c.dado["visual"]["tipo"] in TIPOS_COM_MIDIA


def eh_video(c: Cena) -> bool:
    return bool(c.midia) and c.midia.suffix.lower() in EXT_VID and c.dado["visual"]["tipo"] in TIPOS_COM_MIDIA


def preparar_camera(ep: Path, cenas: list[Cena], w: int, h: int, fps: int) -> None:
    """Decide, EM ORDEM, o plano de câmera de todas as fotos e os punch-ins (render_cena roda em paralelo,
    mas continuidade de vetor, alternância de curvas e o espaçamento dos punches dependem da cena anterior).
    Roda uma vez por lista de cenas (lock + marca na 1ª cena)."""
    with _CAMERA_LOCK:
        if not cenas or cenas[0].extras.get("_camera"):
            return
        rcfg = config().get("render", {})
        min_plano = rcfg.get("punch_min_plano", 8)
        intervalo = rcfg.get("punch_intervalo", 25)
        freq: dict[str, int] = {}
        for orig in {c.extras.get("orig", c.id): c for c in cenas}.values():
            for p in orig.extras.get("meta_orig", {}).get("texto", "").split():
                n = _norm_palavra(p)
                freq[n] = freq.get(n, 0) + 1
        anterior, curvas, ultimo_punch = None, [], -1e9
        for c in cenas:
            foto = eh_foto(c)
            if foto:
                img = imagem_camera(ep, c, w, h)
                plano = movimento.decidir(c.dado, img, c.total / fps, w, h,
                                          anterior if c.entrada == "corte" else None, curvas[-2:])
                c.extras["img_camera"] = img
                c.extras["plano"] = plano
                c.extras["movimento"] = plano.tipo
                c.extras["curva"] = plano.curva
                curvas.append(plano.curva)
                anterior = plano
            else:
                anterior = None
            if (foto or eh_video(c)) and (c.frames / fps > min_plano or c.dado.get("enfase") is not None):
                t = tempo_enfase(c, fps, freq)
                pedido = isinstance(c.dado.get("enfase"), list) and t is not None
                if t is not None and (pedido or c.inicio + t - ultimo_punch >= intervalo):
                    forca = c.extras.get("enfase_escala") or round(estilo.rng(c.dado, "punch").uniform(1.08, 1.10), 3)
                    c.extras["enfase_pedida"] = pedido
                    c.extras["punch"] = {"tempos": [round(c.alca_antes / fps + t, 3)], "forca": forca}
                    ultimo_punch = c.inicio + t
            if foto or c.extras.get("punch"):
                p = c.extras.get("plano")
                log(f"  câmera {c.id}: {p.tipo + '/' + p.curva if p else 'vídeo'}"
                    + (f"  punch {c.extras['punch']['tempos'][0]:.2f}s ×{c.extras['punch']['forca']}"
                       if c.extras.get("punch") else ""))
        cenas[0].extras["_camera"] = True


def render_cena(ep: Path, c: Cena, cenas: list[Cena], w: int, h: int, fps: int, rascunho: bool) -> Path:
    build = ep / "build" / "cenas"
    build.mkdir(parents=True, exist_ok=True)
    preparar_camera(ep, cenas, w, h, fps)
    cena = c.dado
    saida = build / f"{c.id}.mp4"
    vizinha = next((x.midia for x in [*cenas[cenas.index(c) + 1:cenas.index(c) + 2],
                                       *cenas[max(0, cenas.index(c) - 1):cenas.index(c)]] if x.midia), None)
    fundo = quadro_de(vizinha, build) if cena["visual"]["tipo"] == "cartela" else None
    c.hash = assinatura({k: v for k, v in cena.items() if k not in CHAVES_OVERLAY}, str(c.midia), c.midia.stat().st_mtime if c.midia else 0, c.frames, c.alca_antes,
                        c.alca_depois, w, h, fps, rascunho, estilo.tokens(), str(fundo),
                        c.extras.get("plano"), c.extras.get("punch"), VERSAO_MOVIMENTO)
    marca = build / f"{c.id}.hash"
    if saida.exists() and marca.exists() and marca.read_text() == c.hash:
        return saida

    total = c.total
    dur_total = total / fps
    t0 = c.alca_antes / fps                   # início do "corpo" da cena
    t1 = (c.alca_antes + c.frames) / fps      # fim do corpo
    tratamento = estilo.filtro_tratamento(cena)
    entradas: list[str] = []
    camadas: list[str] = []
    trajeto = None

    if cena["visual"]["tipo"] == "cartela" or c.midia is None:
        if cena["visual"]["tipo"] == "cartela":
            pf, lista, tx, ty = graficos.cartela_animada(cena["visual"]["cartela_texto"], build, cena, w, h, fps,
                                                         t0 + 0.15, dur_total, fundo)
            texto_in = graficos.args_entrada(lista)
        else:
            pf, pt = graficos.placeholder(cena, build, w, h)
            texto_in, tx, ty = ["-loop", "1", "-framerate", str(fps), "-i", str(pt)], 0, 0
        plano = movimento.Plano("zoom_in", 1.0, 1.05, 0.5, 0.5)
        mov = movimento.clipe(plano, total, w, h, fps, pf, build / f"{c.id}_mov.mp4", estilo.ARGS_MEZANINO)
        entradas += ["-i", str(mov), *texto_in]
        camadas.append("[0:v]setsar=1[base]")
        camadas += graficos.filtro_overlay(1, "[base]", tx, ty, fps, "[v0]", "txt")
        tratamento = "null"
    elif c.midia.suffix.lower() in EXT_IMG:
        # plano e imagem (moldura p/ foto pequena) já decididos em ordem por preparar_camera
        img = c.extras.get("img_camera") or imagem_camera(ep, c, w, h)
        plano = c.extras.get("plano") or movimento.decidir(cena, img, total / fps, w, h)
        c.extras["movimento"] = plano.tipo
        punch = c.extras.get("punch") or {}
        trajeto = [] if marcas.lista(cena) else None
        mov = movimento.clipe(plano, total, w, h, fps, img, build / f"{c.id}_mov.mp4", estilo.ARGS_MEZANINO,
                              punch.get("tempos"), punch.get("forca", 1.09), trajeto, c.extras.get("rect_rel"))
        entradas += ["-i", str(mov)]
        camadas.append("[0:v]setsar=1[v0]")
    else:
        inicio = max(0.0, float(cena["visual"].get("inicio", 0)) - t0)
        norm_v = f"scale={w}:{h}:force_original_aspect_ratio=increase:flags=lanczos,crop={w}:{h},fps={fps},setsar=1"
        punch = c.extras.get("punch")
        cong = tempo_congelar(c, fps)
        fat = None
        if punch or cong is not None:
            # punch-in / freeze-frame: normaliza o vídeo para w×h, aplica quadro a quadro (OpenCV) e segue
            import numpy as np
            base = build / f"{c.id}_base.mp4"
            rodar(["ffmpeg", "-y", "-hide_banner", "-v", "error", "-stream_loop", "-1", "-ss", f"{inicio:.3f}",
                   "-i", str(c.midia), "-vf", norm_v, "-frames:v", str(total), *estilo.ARGS_MEZANINO, "-an", str(base)])
            fat = movimento.fatores_punch(total, fps, punch["tempos"], punch["forca"]) if punch else np.ones(total)
            q_cong = None
            if cong is not None:
                q_cong = c.alca_antes + round(cong * fps)
                zoom = float((cena.get("congelar") or {}).get("zoom", 1.06))
                fat = fat * movimento.fatores_punch(total, fps, [q_cong / fps], zoom, quadros=max(4, round(0.3 * fps)))
            pun = movimento.aplicar_punch(base, build / f"{c.id}_punch.mp4", w, h, fps, fat, estilo.ARGS_MEZANINO,
                                          congelar=q_cong)
            base.unlink(missing_ok=True)
            entradas += ["-i", str(pun)]
            camadas.append("[0:v]setsar=1[v0]")
        else:
            entradas += ["-stream_loop", "-1", "-ss", f"{inicio:.3f}", "-i", str(c.midia)]
            camadas.append(f"[0:v]{norm_v}[v0]")
        trajeto = marcas.trajeto_video(c.midia, w, h, fat) if marcas.lista(cena) else None

    # rótulo e destaque NÃO são queimados aqui: entram no bloco (render_bloco), depois do acabamento — assim o
    # mesmo grafo produz a versão limpa usada nos Shorts. Marcações (cena.marca) sim: são parte da imagem, entram
    # depois do tratamento de cor (o vermelho não pode virar cinza na foto histórica) e acompanham a câmera.
    janelas = marcas.janelas(c, fps) if trajeto else []
    if janelas:
        camada_m = marcas.camada(janelas, trajeto, w, h, fps, total, build / f"{c.id}_marca.mov")
        # posição na tela de cada marcação (segundos do vídeo longo): os Shorts centram o recorte 9:16 nela
        inicio_clipe = c.inicio - c.alca_antes / fps
        salvar_json(build / f"{c.id}_marca.json",
                    {"marcas": [{**x, "ti": round(inicio_clipe + x["ti"], 3), "tf": round(inicio_clipe + x["tf"], 3)}
                                for x in marcas.caixas(janelas, trajeto, w, h, fps)]})
        k = len([a for a in entradas if a == "-i"])
        entradas += ["-i", str(camada_m)]
        camadas.append(f"[v0]{tratamento}[vt]")
        camadas.append(f"[{k}:v]format=rgba,setpts=PTS-STARTPTS[mk]")
        camadas.append("[vt][mk]overlay=0:0:eof_action=pass:format=auto,format=yuv420p[v]")
    else:
        if marcas.lista(cena) and not trajeto:
            log(f"  aviso {c.id}: 'marca' só vale em foto/vídeo — ignorada")
        camadas.append(f"[v0]{tratamento},format=yuv420p[v]")

    rodar(["ffmpeg", "-y", "-hide_banner", "-v", "error", *entradas, "-filter_complex", ";".join(camadas),
           "-map", "[v]", "-frames:v", str(total), "-r", str(fps), "-t", f"{dur_total:.4f}",
           *estilo.ARGS_MEZANINO, "-an", str(saida)])
    marca.write_text(c.hash)
    return saida


# ---------------------------------------------------------------- blocos com transição + acabamento
def blocos(cenas: list[Cena], processos: int = 1) -> list[list[Cena]]:
    """Agrupa cenas; um bloco só termina num corte seco. Blocos menores = mais paralelismo e cache mais fino."""
    alvo = max(3, min(MAX_CENAS_BLOCO, -(-len(cenas) // max(1, processos))))
    out, atual = [], []
    for c in cenas:
        if atual and c.entrada == "corte" and len(atual) >= alvo:
            out.append(atual)
            atual = []
        atual.append(c)
    if atual:
        out.append(atual)
    return out


VERSAO_TRANSICAO = "cv2"  # whip/foco; luz/zoom entram pelo nome da transição no hash
VERSAO_OVERLAY = "ov1"   # rótulo/destaque no bloco, por cima do acabamento


def _ler_quadros(arq: Path, ini: int, n: int, w: int, h: int):
    import subprocess

    import numpy as np
    p = subprocess.run(["ffmpeg", "-v", "error", "-i", str(arq), "-vf",
                        f"trim=start_frame={ini}:end_frame={ini + n},setpts=PTS-STARTPTS,scale={w}:{h}",
                        "-f", "rawvideo", "-pix_fmt", "bgr24", "-"], capture_output=True, check=True)
    q = np.frombuffer(p.stdout, np.uint8)
    out = list(q[: (len(q) // (w * h * 3)) * w * h * 3].reshape(-1, h, w, 3))
    while len(out) < n:  # mezanino curto (arredondamento): repete a última
        out.append(out[-1])
    return out


def transicao_cv(ep: Path, a: Cena, b: Cena, d: int, fps: int) -> Path:  # noqa: C901
    """Clipe de d quadros que substitui a janela de sobreposição entre A (cauda) e B (cabeça).
    - whip: A sai deslocando-se ~12% do quadro para a esquerda (power4.in) e B entra da direita (power4.out),
      com desfoque de movimento horizontal proporcional à velocidade; corte no meio, escondido pelo borrão.
    - foco (rack focus): A desfoca (gaussiano até ~19 px em 1080p, power2.in), B refoca (power2.out);
      no meio, os dois desfocados se misturam (evita salto de brilho).
    - luz (film burn / light leak): A dissolve em B por baixo de manchas de luz quente (ouro → laranja →
      tijolo) que atravessam o quadro em "screen", com leve superexposição; tudo gerado, sem asset de terceiros.
    - zoom (zoom-through): A mergulha (1 → 1,4×, power2.in) com desfoque radial proporcional à velocidade;
      B sai do mesmo mergulho (1,4 → 1×, power2.out); o corte no meio fica escondido no borrão.
    Dinâmicas (linguagem da colagem editorial):
    - forma: A encolhe girando em direção ao centro (o fundo de estúdio aparece em volta) enquanto B nasce de
      dentro de uma forma que cresce (círculo, quadrado girado, losango ou hexágono, pela semente) com fio claro.
    - cortina: A se abre ao meio como duas portas (cada metade desliza para um lado) revelando B; fio claro na fresta.
    - fatias: B chega em 8 faixas horizontais alternando esquerda/direita, escalonadas, com rastro horizontal.
    - mosaico: o quadro vira uma grade de ladrilhos que giram no eixo vertical (A → B) em onda diagonal.
    - cor: cor chapada da marca — A é engolido por um campo de cor que avança dos dois lados (A escurece
      afundando na cor); depois o campo se abre ao meio revelando B, que assenta de 1,08×. Fio claro na
      fresta, como a transição laranja da referência."""
    import math

    import cv2
    import numpy as np

    pasta = ep / "build" / "transicoes"
    pasta.mkdir(parents=True, exist_ok=True)
    hsh = assinatura(a.hash, b.hash, b.entrada, d, fps, VERSAO_TRANSICAO)[:16]
    saida = pasta / f"{b.id}_{b.entrada}_{hsh}.mp4"
    if saida.exists():
        return saida
    cap = cv2.VideoCapture(str(a.arquivo))
    w, h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()
    qa = _ler_quadros(a.arquivo, a.total - d, d, w, h)
    qb = _ler_quadros(b.arquivo, 0, d, w, h)
    tmp = saida.with_suffix(".tmp.mp4")
    import subprocess
    enc = subprocess.Popen(["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{w}x{h}",
                            "-r", str(fps), "-i", "-", *estilo.ARGS_MEZANINO, "-an", str(tmp)], stdin=subprocess.PIPE)

    def desloca(q, dx):
        M = np.array([[1, 0, -dx], [0, 1, 0]], dtype=np.float64)
        return cv2.warpAffine(q, M, (w, h), flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP,
                              borderMode=cv2.BORDER_REFLECT)

    def borra_h(q, comp):
        k = int(round(comp))
        return cv2.blur(q, (k | 1, 1)) if k >= 3 else q

    def gauss(q, sigma):
        return cv2.GaussianBlur(q, (0, 0), sigma) if sigma > 0.3 else q

    amp = 0.12 * w
    smax = 19 * h / 1080
    r = estilo.rng(b.dado, "luz")
    # manchas da "luz": (cor BGR, y relativo, raio relativo, x inicial, velocidade)
    cores_luz = [(70, 150, 215), (30, 100, 230), (40, 60, 190), (60, 140, 240)]  # BGR: ouro, laranja, tijolo, âmbar
    manchas = [(cores_luz[i % 4], r.uniform(0.15, 0.85), r.uniform(0.25, 0.5), r.uniform(-0.6, -0.1), r.uniform(1.0, 1.8))
               for i in range(4)]
    ys, xs = np.mgrid[0:h // 8, 0:w // 8].astype(np.float32)
    xs, ys = xs / (w // 8), ys / (h // 8) * (h / w)

    def luz(u):
        env = math.sin(math.pi * u) ** 1.5
        cam = np.zeros((h // 8, w // 8, 3), np.float32)
        for cor_b, yc, rr, x0, vel in manchas:
            xc = x0 + vel * u
            g = np.exp(-(((xs - xc) / (rr * 1.6)) ** 2 + ((ys - yc * h / w) / rr) ** 2))
            cam += g[..., None] * np.array(cor_b, np.float32)
        cam = np.clip(cam * env * 0.7, 0, 235)
        return cv2.resize(cam, (w, h), interpolation=cv2.INTER_CUBIC)

    def escala(q, z):
        M = cv2.getRotationMatrix2D((w / 2, h / 2), 0, z)
        return cv2.warpAffine(q, M, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)

    def radial(q, z, borrao):
        if borrao < 0.004:
            return escala(q, z)
        n = 6
        acc = np.zeros(q.shape, np.float32)
        for i in range(n):
            acc += escala(q, z * (1 + borrao * i / (n - 1))).astype(np.float32)
        return (acc / n).astype(np.uint8)

    rd = estilo.rng(b.dado, "transicao-dinamica")
    forma_tr = rd.choice(["circulo", "quadrado", "losango", "hexagono"])
    # cor chapada da transição "cor": acento da marca (destaque ou secundária), sorteado por cena
    hexc = estilo.tokens()["cores"][rd.choice(["destaque", "secundaria"])].lstrip("#")
    cor_chap = tuple(int(hexc[i:i + 2], 16) for i in (4, 2, 0))  # BGR
    cor_v = np.array(cor_chap, np.float32)
    hexa = estilo.tokens().get("colagem", {}).get("fundo_escuro", "#1C1C1E").lstrip("#")
    cor_fundo = tuple(int(hexa[i:i + 2], 16) for i in (4, 2, 0))  # BGR
    linha = (230, 239, 244)

    def poligono(cx, cy, r, ang):
        if forma_tr == "circulo":
            return None
        n, extra = {"quadrado": (4, math.pi / 4), "losango": (4, 0.0), "hexagono": (6, 0.0)}[forma_tr]
        return np.array([[cx + r * math.cos(extra + ang + i * 2 * math.pi / n), cy + r * math.sin(extra + ang + i * 2 * math.pi / n)]
                         for i in range(n)], np.int32)

    def gira_escala(q, z, ang):
        M = cv2.getRotationMatrix2D((w / 2, h / 2), ang, z)
        return cv2.warpAffine(q, M, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=cor_fundo)

    def forma(k, u):
        ea = min(1.0, u / 0.65) ** 3                                     # A: power3.in
        base = gira_escala(qa[k], 1 - 0.6 * ea, 28 * ea)
        eb = 1 - (1 - min(1.0, max(0.0, (u - 0.22) / 0.78))) ** 3        # B: power3.out
        if eb <= 0:
            return base
        r = eb * math.hypot(w, h) * 0.56
        bq = escala(qb[k], 1.25 - 0.25 * eb)
        mask = np.zeros((h, w), np.uint8)
        pol = poligono(w / 2, h / 2, r, (1 - eb) * 0.9)
        if pol is None:
            cv2.circle(mask, (w // 2, h // 2), int(r), 255, -1, cv2.LINE_AA)
        else:
            cv2.fillPoly(mask, [pol], 255, cv2.LINE_AA)
        m = (mask.astype(np.float32) / 255)[..., None]
        out = (bq * m + base * (1 - m)).astype(np.uint8)
        esp = max(2, round(3 * h / 1080))
        if pol is None:
            cv2.circle(out, (w // 2, h // 2), int(r), linha, esp, cv2.LINE_AA)
        else:
            cv2.polylines(out, [pol], True, linha, esp, cv2.LINE_AA)
        return out

    def cortina(k, u):
        e = 1 - (1 - u) ** 3
        meio = int(w / 2 * e)
        out = qb[k].copy()
        if meio < w // 2:
            esq, dir_ = qa[k][:, : w // 2], qa[k][:, w // 2:]
            out[:, : w // 2 - meio] = esq[:, meio:]
            out[:, w // 2 + meio:] = dir_[:, : w - w // 2 - meio]
            esp = max(2, round(3 * h / 1080))
            for x in (w // 2 - meio, w // 2 + meio):
                cv2.line(out, (x, 0), (x, h), linha, esp, cv2.LINE_AA)
        return out

    def fatias(k, u):
        n = 8
        out = qa[k].copy()
        alt = h / n
        for i in range(n):
            ui = min(1.0, max(0.0, (u - i * 0.05) / 0.62))
            ui_ant = min(1.0, max(0.0, (u - 1 / d - i * 0.05) / 0.62))
            e, e_ant = 1 - (1 - ui) ** 4, 1 - (1 - ui_ant) ** 4
            if e <= 0:
                continue
            lado = 1 if i % 2 else -1
            dx = int(lado * (1 - e) * w)
            y0, y1 = int(i * alt), int((i + 1) * alt)
            faixa = qb[k][y0:y1]
            faixa = borra_h(faixa, abs(e - e_ant) * w * 0.25)
            if dx >= 0:
                out[y0:y1, dx:] = faixa[:, : w - dx]
            else:
                out[y0:y1, : w + dx] = faixa[:, -dx:]
        return out

    def mosaico(k, u):
        cols, lins = 8, 5
        tw, th = w // cols, h // lins
        out = np.empty_like(qa[k])
        out[:] = cor_fundo
        for j in range(lins):
            for i in range(cols):
                atraso = (i / cols + j / lins) / 2 * 0.5
                ui = min(1.0, max(0.0, (u - atraso) / 0.5))
                sx = abs(math.cos(math.pi * ui))
                fonte_q = qa[k] if ui < 0.5 else qb[k]
                x0, y0 = i * tw, j * th
                x1, y1 = (w if i == cols - 1 else x0 + tw), (h if j == lins - 1 else y0 + th)
                lad = fonte_q[y0:y1, x0:x1]
                lw = max(1, int((x1 - x0) * sx * 0.96))
                lh = max(1, int((y1 - y0) * (0.96 if 0 < ui < 1 else 1)))
                if 0 < ui < 1:
                    lad = cv2.resize(lad, (lw, lh), interpolation=cv2.INTER_AREA)
                    ox, oy = x0 + ((x1 - x0) - lw) // 2, y0 + ((y1 - y0) - lh) // 2
                    out[oy:oy + lh, ox:ox + lw] = lad
                else:
                    out[y0:y1, x0:x1] = lad
        return out

    def cor_chapada(k, u):
        """Cor chapada: até u=0,45 o campo de cor fecha dos dois lados sobre A (que afunda na cor);
        depois abre revelando B (que assenta de 1,08×). Fio claro acompanha a fresta."""
        esp = max(2, round(3 * h / 1080))
        if u < 0.45:
            e = (u / 0.45) ** 2                                    # power2.in
            a = qa[k].astype(np.float32) * (1 - 0.72 * e) + cor_v * (0.72 * e)
            out = a.astype(np.uint8)
            m = int((w / 2) * e ** 1.35)
            if m > 0:
                out[:, :m] = cor_chap
                out[:, w - m:] = cor_chap
                cv2.line(out, (m, 0), (m, h), linha, esp, cv2.LINE_AA)
                cv2.line(out, (w - m, 0), (w - m, h), linha, esp, cv2.LINE_AA)
            return out
        x = (u - 0.45) / 0.55
        e = 1 - (1 - x) ** 3                                       # power3.out
        m = int((w / 2) * (1 - e))
        out = np.full_like(qb[k], cor_chap)
        bq = escala(qb[k], 1.08 - 0.08 * e)
        if m < w // 2:
            out[:, m:w - m] = bq[:, m:w - m]
            cv2.line(out, (m, 0), (m, h), linha, esp, cv2.LINE_AA)
            cv2.line(out, (w - m, 0), (w - m, h), linha, esp, cv2.LINE_AA)
        return out

    try:
        for k in range(d):
            u = (k + 0.5) / d
            if b.entrada in ("forma", "cortina", "fatias", "mosaico", "cor"):
                q = {"forma": forma, "cortina": cortina, "fatias": fatias, "mosaico": mosaico, "cor": cor_chapada}[b.entrada](k, u)
            elif b.entrada == "whip":
                if u < 0.5:
                    off = lambda x: -amp * min(1, max(0, x)) ** 4                 # power4.in
                    p, p0 = u / 0.5, (u - 1 / d) / 0.5
                    q = borra_h(desloca(qa[k], off(p)), abs(off(p) - off(p0)))
                else:
                    off = lambda x: amp * (1 - min(1, max(0, x))) ** 4            # power4.out (entra da direita)
                    p, p1 = (u - 0.5) / 0.5, (u + 1 / d - 0.5) / 0.5
                    q = borra_h(desloca(qb[k], off(p)), abs(off(p) - off(p1)))
            elif b.entrada == "luz":
                mix = min(1.0, max(0.0, (u - 0.3) / 0.4))
                mix = mix * mix * (3 - 2 * mix)
                base = cv2.addWeighted(qa[k], 1 - mix, qb[k], mix, 0).astype(np.float32)
                base = base + (255 - base) * 0.08 * math.sin(math.pi * u)            # superexposição leve
                lz = luz(u)
                q = np.clip(255 - (255 - base) * (255 - lz) / 255, 0, 255).astype(np.uint8)  # screen
            elif b.entrada == "zoom":
                if u < 0.5:
                    p = (u / 0.5) ** 2
                    p_ant = (max(0.0, u - 1 / d) / 0.5) ** 2
                    q = radial(qa[k], 1 + 0.4 * p, 0.06 * (p - p_ant) * d / 2)
                else:
                    x = (u - 0.5) / 0.5
                    p = 1 - (1 - x) ** 2
                    p_prox = 1 - (1 - min(1.0, x + 2 / d)) ** 2
                    q = radial(qb[k], 1 + 0.4 * (1 - p), 0.06 * (p_prox - p) * d / 2)
            else:  # foco
                sa = smax * min(1.0, u / 0.5) ** 2                                  # power2.in
                sb = smax * (1 - min(1.0, max(0.0, (u - 0.5) / 0.5))) ** 2          # power2.out
                mix = min(1.0, max(0.0, (u - 0.35) / 0.3))
                mix = mix * mix * (3 - 2 * mix)
                if mix <= 0:
                    q = gauss(qa[k], sa)
                elif mix >= 1:
                    q = gauss(qb[k], sb)
                else:
                    q = cv2.addWeighted(gauss(qa[k], sa), 1 - mix,
                                        gauss(qb[k], sb), mix, 0)
            enc.stdin.write(np.ascontiguousarray(q).tobytes())
    finally:
        enc.stdin.close()
        if enc.wait() != 0:
            raise RuntimeError(f"ffmpeg falhou ao gravar {saida}")
    tmp.replace(saida)
    return saida


def render_bloco(ep: Path, idx: int, grupo: list[Cena], fps: int, final: bool, primeiro: bool, ultimo: bool,
                 trecho: tuple[float, float] | None = None, w: int = 1920, h: int = 1080,
                 limpo: bool = False, ctas: list[dict] | None = None) -> tuple[Path, Path | None]:
    """Transições + acabamento de um grupo de cenas. Rótulos e destaques entram AQUI, por cima do acabamento
    (tempo = início da cena no bloco + o ti/tf de sempre). Com `limpo`, o mesmo grafo sai também sem os overlays
    (split depois do acabamento: custo extra = só o encode) → bloco_NNN_limpo.mp4, fonte dos Shorts.
    Devolve (bloco, bloco_limpo | None)."""
    pasta = ep / "build" / "blocos"
    pasta.mkdir(parents=True, exist_ok=True)
    saida = pasta / f"bloco_{idx:03d}.mp4"
    saida_limpa = pasta / f"bloco_{idx:03d}_limpo.mp4"
    ac = estilo.tokens()["acabamento"]
    args_enc = estilo.args_encoder(final)
    # relógio do bloco: começa no corpo da 1ª cena (a alça inicial é cortada); CTAs que atravessam a emenda
    # entram nos dois blocos, cada um com a sua parte
    b0 = grupo[0].inicio
    b1 = b0 + (sum(c.frames for c in grupo)) / fps
    sig_cta = cta.assinatura(ctas or [], b0, b1)
    h_ = assinatura([c.hash for c in grupo], [c.entrada for c in grupo], primeiro, ultimo, ac, args_enc, final, trecho,
                    VERSAO_TRANSICAO, VERSAO_OVERLAY, [assinatura_overlay(c) for c in grupo], w, h,
                    *([sig_cta] if sig_cta else []))
    marca = pasta / f"bloco_{idx:03d}.hash"
    if saida.exists() and marca.exists() and marca.read_text() == h_ and (not limpo or saida_limpa.exists()):
        return saida, (saida_limpa if limpo else None)

    entradas, filtros = [], []
    for i, c in enumerate(grupo):
        entradas += ["-i", str(c.arquivo)]
        # concat/xfade exigem a mesma timebase e taxa nas duas pontas
        filtros.append(f"[{i}:v]fps={fps},settb=1/{fps},setpts=PTS-STARTPTS,setsar=1[n{i}]")
    acc, acc_frames = "[n0]", grupo[0].total
    pos = [0]  # quadro do bloco (antes do trim da alça inicial) onde começa o arquivo de cada cena
    for i, c in enumerate(grupo[1:], 1):
        rot = f"[x{i}]"
        if c.entrada == "corte":
            pos.append(acc_frames)
            filtros.append(f"{acc}[n{i}]concat=n=2:v=1:a=0,settb=1/{fps}{rot}")
            acc_frames += c.total
        elif c.entrada in TRANSICAO_CV:
            # janela de sobreposição (2 alças) pronta em OpenCV: cauda de A + cabeça de B → clipe de d quadros
            d = 2 * c.alca_antes
            pos.append(acc_frames - d)
            tr = transicao_cv(ep, grupo[i - 1], c, d, fps)
            k = len([x for x in entradas if x == "-i"])
            entradas += ["-i", str(tr)]
            filtros.append(f"[{k}:v]fps={fps},settb=1/{fps},setpts=PTS-STARTPTS,setsar=1[t{i}]")
            filtros.append(f"{acc}trim=end_frame={acc_frames - d},setpts=PTS-STARTPTS[a{i}]")
            filtros.append(f"[n{i}]trim=start_frame={d},setpts=PTS-STARTPTS[b{i}]")
            filtros.append(f"[a{i}][t{i}][b{i}]concat=n=3:v=1:a=0,settb=1/{fps}{rot}")
            acc_frames += c.total - d
        else:
            d = 2 * c.alca_antes
            pos.append(acc_frames - d)
            filtros.append(f"{acc}[n{i}]xfade=transition={XFADE[c.entrada]}:duration={d / fps:.4f}:"
                           f"offset={(acc_frames - d) / fps:.4f}{rot}")
            acc_frames += c.total - d
        acc = rot
    # retira a alça inicial da 1ª cena e a final da última (não há vizinho fora do bloco)
    ini = grupo[0].alca_antes
    fim = acc_frames - grupo[-1].alca_depois
    cadeia = [f"trim=start_frame={ini}:end_frame={fim}", "setpts=PTS-STARTPTS"]
    dur = (fim - ini) / fps
    cadeia.append(f"vignette=angle={ac['vinheta']}")
    if final or ac.get("grao_no_rascunho"):
        # grão só na luma e com distribuição uniforme: textura de filme, não ruído digital colorido
        cadeia.append(f"format=yuv420p,noise=c0s={ac['grao']}:c0f=t+u")
    cadeia.append("format=yuv420p")
    # fade de abertura/fecho do vídeo: depois dos overlays (o rótulo da 1ª cena some no preto junto)
    fades = []
    if primeiro:
        fades.append("fade=t=in:st=0:d=0.8")
    if ultimo:
        fades.append(f"fade=t=out:st={max(0, dur - 1.2):.3f}:d=1.2")
    fades = ",".join(fades) or "null"
    filtros.append(f"{acc}{','.join(cadeia)}[pre]")
    if limpo:
        filtros.append("[pre]split[pre_o][pre_l]")
        filtros.append(f"[pre_l]{fades}[vl]")
        base = "[pre_o]"
    else:
        base = "[pre]"
    build = ep / "build" / "cenas"
    build.mkdir(parents=True, exist_ok=True)
    camada = base
    for i, c in enumerate(grupo):
        if not tem_overlay(c):
            continue
        t0 = (pos[i] - ini + c.alca_antes) / fps   # início do corpo da cena no relógio do bloco
        t1 = t0 + c.frames / fps
        trat = tratamento_overlay(c)
        camada = camada_rotulo(c, build, entradas, filtros, camada, w, h, fps, t0, t1, dur + 1, f"_{i}", trat)
        camada = camada_destaque(c, build, entradas, filtros, camada, w, h, fps, t0, t1, dur + 1, f"_{i}", trat)
    # CTAs (inscrever/like/comentar): por cima de tudo, sem tratamento de cor, fora da versão limpa
    camada = cta.overlay(ctas or [], b0, b0 + dur, entradas, filtros, camada, fps)
    filtros.append(f"{camada}{fades},format=yuv420p[v]")
    cmd = ["ffmpeg", "-y", "-hide_banner", "-v", "error", *entradas, "-filter_complex", ";".join(filtros),
           "-map", "[v]", "-r", str(fps), *args_enc, "-g", str(fps * 2), "-an", str(saida)]
    if limpo:
        # versão limpa (Shorts): mesmo encoder de GPU, qualidade um pouco menor — é intermediária
        cmd += ["-map", "[vl]", "-r", str(fps), *estilo.args_encoder_limpo(), "-g", str(fps * 2), "-an",
                str(saida_limpa)]
    rodar(cmd)
    marca.write_text(h_)
    return saida, (saida_limpa if limpo else None)


# ---------------------------------------------------------------- legendas
def tempo_srt(s: float) -> str:
    ms = int(round(s * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def palavras_da_cena(meta: dict, inicio: float) -> list[tuple[str, float, float]]:
    """Palavras com tempo absoluto. Formato novo: meta['palavras']; legado: alinhamento por caractere."""
    if meta.get("palavras"):
        return [(p["texto"], inicio + p["ini"], inicio + p["fim"]) for p in meta["palavras"]]
    al = meta.get("alignment") or {}
    chars = al.get("characters") or []
    ini = al.get("character_start_times_seconds") or []
    fim = al.get("character_end_times_seconds") or []
    if not chars:  # sem alinhamento: distribui o texto pela duração
        ws = meta["texto"].split()
        passo = meta["duracao"] / max(1, len(ws))
        return [(p, inicio + i * passo, inicio + (i + 1) * passo) for i, p in enumerate(ws)]
    out, atual, t0, ultimo = [], "", None, 0.0
    for ch, a, b in zip(chars, ini, fim):
        if ch.isspace():
            if atual:
                out.append((atual, inicio + t0, inicio + ultimo))
            atual, t0 = "", None
            continue
        if t0 is None:
            t0 = a
        atual += ch
        ultimo = b
    if atual:
        out.append((atual, inicio + t0, inicio + ultimo))
    return out


# Palavras que não devem terminar uma linha de legenda (lição do grio-video: ler "de / 1919" é ruim): i18n.LIGACAO


def gerar_srt(palavras, destino: Path, max_chars=42, max_seg=3.2, min_chars=12) -> None:
    """Particiona por programação dinâmica: minimiza blocos desequilibrados, quebras em palavras de
    ligação e blocos longos; respeita fim de frase como quebra natural."""
    n = len(palavras)
    if not n:
        destino.write_text("", encoding="utf-8")
        return
    INF = float("inf")
    ligacao = i18n.LIGACAO[i18n.lang()]
    custo = [INF] * (n + 1)
    volta = [0] * (n + 1)
    custo[0] = 0.0
    for j in range(1, n + 1):
        for i in range(j - 1, -1, -1):
            texto = " ".join(p[0] for p in palavras[i:j])
            dur = palavras[j - 1][2] - palavras[i][1]
            if len(texto) > max_chars or (dur > max_seg and j - i > 1):
                break
            if any(p[0][-1] in ".!?" for p in palavras[i:j - 1]):
                continue  # não atravessa fim de frase
            ultima = palavras[j - 1][0].lower().strip(",;:")
            c = (max_chars - len(texto)) ** 2 / 40
            if len(texto) < min_chars and j < n:
                c += 30
            if ultima in ligacao and j < n:
                c += 60
            if ultima[:1].isdigit() and j < n and not palavras[j - 1][0][-1] in ".!?,":
                c += 20
            if palavras[j - 1][0][-1] in ",;:":
                c -= 8
            if custo[i] + c < custo[j]:
                custo[j], volta[j] = custo[i] + c, i
    cortes, j = [], n
    while j > 0:
        cortes.append((volta[j], j))
        j = volta[j]
    linhas = []
    for k, (i, j) in enumerate(reversed(cortes), 1):
        b = palavras[i:j]
        linhas += [str(k), f"{tempo_srt(b[0][1])} --> {tempo_srt(b[-1][2])}", " ".join(x[0] for x in b), ""]
    destino.write_text("\n".join(linhas), encoding="utf-8")


# ---------------------------------------------------------------- descrição
def mmss(s: float) -> str:
    s = int(s)
    return f"{s // 3600}:{s // 60 % 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"


LIMITE_DESCRICAO = 4900  # o YouTube aceita 5.000 caracteres


def titulo_fonte(afirmacao: str) -> str:
    """'Wikipedia, Year Without a Summer: queda de...' -> 'Wikipedia, Year Without a Summer'."""
    t = afirmacao.split(":")[0].strip()
    return t if len(t) <= 70 else t[:67].rstrip() + "…"


def autor_curto(autor) -> str:
    a = re.split(r"\s*[(–—|]|\s-\s", str(autor or i18n.t("desconhecido")))[0].strip()
    return a[:50] or i18n.t("desconhecido")


def gerar_descricao(sb, ep, inicios, total, destino: Path, extras: list[str] | None = None,
                    sfx: list[str] | None = None) -> list[str]:
    creditos = ler_json(ep / "midia" / "creditos.json", {})
    linhas = [sb["meta"].get("descricao", ""), ""]
    # capítulos (YouTube exige começar em 0:00, 3+ capítulos, cada um com 10s+)
    caps, ultimo = [], None
    for c, t in zip(sb["cenas"], inicios):
        b = c.get("bloco")
        titulo_cap = ((c["visual"].get("capitulo") or {}).get("titulo") or c["visual"].get("titulo")) if c["visual"]["tipo"] == "capitulo" else None
        if (b and b != ultimo) or titulo_cap:
            if not caps or t - caps[-1][0] >= 10:
                caps.append((t, titulo_cap or i18n.bloco(b)))
            ultimo = b
    if len(caps) >= 3:
        caps[0] = (0, caps[0][1])
        linhas += [i18n.t("capitulos")] + [f"{mmss(t)} {nome}" for t, nome in caps] + [""]
    linhas += [i18n.t("fontes")] + [f"- {titulo_fonte(f['afirmacao'])}: {f['url']}" for f in sb["fontes"]] + [""]
    # imagens: crédito individual só onde a licença exige (CC BY/BY-SA); o resto vira uma linha
    exigem, outras, vistos = [], set(), set()
    for cr in creditos.values():  # inclui sub-cortes e lados de comparação
        if not cr or cr.get("fonte") == "fal" or cr.get("pagina") in vistos:
            continue
        vistos.add(cr.get("pagina"))
        lic = str(cr.get("licenca", ""))
        if cr.get("requer_atribuicao"):
            exigem.append(f"- {autor_curto(cr.get('autor'))} ({lic}): {cr.get('pagina')}")
        elif "pixabay" in lic.lower():
            outras.add("Pixabay")
        elif "pexels" in lic.lower():
            outras.add("Pexels")
        else:
            outras.add(i18n.t("dominio_publico_longo"))
    bloco_img = ([i18n.t("imagens_atribuicao")] + exigem) if exigem else []
    if outras:
        bloco_img.append(i18n.t("demais_imagens", lista=", ".join(sorted(outras))))
    bloco_mus = []
    if extras:
        titulos = [m.group(1) for e in extras if "MacLeod" in e and (m := re.search(r'"(.+?)"', e))]
        if len(titulos) == len(extras):
            nomes = ", ".join(f'"{t}"' for t in titulos)
            bloco_mus = [i18n.t("musica_macleod", nomes=nomes)]
        else:
            bloco_mus = [i18n.t("musica")] + [f"- {e}" for e in extras]
    sinteticos = [c for c in sb["cenas"] if c["visual"]["tipo"] in ("ia_imagem", "ia_video")]
    rodape = (["", i18n.t("ia_ilustracoes")] if sinteticos else [])
    rodape += ["", i18n.t("voz_sintetica")]
    mus = ([""] + bloco_mus) if bloco_mus else []
    if sfx:  # SFX do Freesound com CC BY (som.creditos); CC0/sintetizados não entram
        mus += ["", i18n.t("sfx_atribuicao")] + sfx
    completo = linhas + bloco_img + mus + rodape
    if len("\n".join(completo)) <= LIMITE_DESCRICAO:
        linhas = completo
    else:  # o YouTube corta em 5.000: créditos de imagem vão para o comentário fixado
        fixado = destino.parent / "comentario_fixado.txt"
        fixado.write_text("\n".join([i18n.t("creditos_imagens")] + bloco_img), encoding="utf-8")
        linhas = linhas + [i18n.t("creditos_no_fixado")] + mus + rodape
        log(f"  descrição longa: créditos de imagem em {fixado.name} (fixe como comentário)")
    destino.write_text("\n".join(linhas), encoding="utf-8")

    pendencias = []
    if any(c["visual"]["tipo"] == "ia_video" for c in sb["cenas"]):
        pendencias.append("Há vídeo realista gerado por IA: marque 'Conteúdo alterado ou sintético = Sim' no upload.")
    for cid, cr in creditos.items():
        if cr.get("verificar"):
            pendencias.append(f"{cid}: confira a licença manualmente ({cr.get('pagina')})")
        if cr.get("requer_atribuicao"):
            pendencias.append(f"{cid}: licença exige atribuição — já está na descrição, não remova")
    if sfx:
        pendencias.append(f"{len(sfx)} efeito(s) sonoro(s) CC BY do Freesound — atribuição já está na descrição, não remova")
    return pendencias


# ---------------------------------------------------------------- áudio
def _loudnorm_medir(entradas: list[str], filtro: str, total: float) -> dict:
    """1ª passada do master: mede o mix inteiro (nada vai para o disco)."""
    import subprocess

    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", *entradas, "-filter_complex",
                        f"{filtro};[pre]loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json[a]", "-map", "[a]",
                        "-t", f"{total:.3f}", "-f", "null", "-"], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode:
        raise SystemExit(f"[erro] ffmpeg (medição do master): {r.stderr[-800:]}")
    return json.loads(r.stderr[r.stderr.rindex("{"):r.stderr.rindex("}") + 1])


def tempo_palavra(c, palavra: str) -> float | None:
    """Segundo (relativo ao corpo da cena) da 1ª palavra da narração que começa como `palavra`."""
    alvo = _norm_palavra((palavra or "").split()[0]) if palavra else ""
    for p in (c.extras.get("meta") or {}).get("palavras", []):
        if alvo and p["ini"] >= 0 and _norm_palavra(p["texto"]).startswith(alvo):
            return float(p["ini"])
    return None


def silencios_dramaticos(cenas: list) -> list[tuple[float, float]]:
    """[(tempo absoluto da palavra, duração)] dos som.silencio do storyboard."""
    fps = config()["video"]["fps"]
    # sub-cortes herdam o som da cena original: a palavra pode cair em qualquer parte dela
    por_orig = {c.extras.get("orig", c.id): (c.dado.get("som") or {}).get("silencio")
                for c in cenas if (c.dado.get("som") or {}).get("silencio")}
    out, feitos = [], set()
    for c in cenas:
        orig = c.extras.get("orig", c.id)
        sil = por_orig.get(orig)
        if not sil or orig in feitos:
            continue
        tp = tempo_palavra(c, sil.get("antes_de", ""))
        if tp is not None and 0 <= tp <= c.frames / fps:
            out.append((c.inicio - cenas[0].inicio + tp, float(sil.get("dur", 1.0))))
            feitos.add(orig)
    return out


def mixar(ep: Path, sb: dict, narracao: Path, total: float, saida_audio: Path, sfx: Path | None = None,
          cenas: list | None = None, palavras: list | None = None, saida_limpa: Path | None = None,
          sfx_limpo: Path | None = None) -> list[str]:
    """Voz + trilha (ducking determinístico pelas palavras) + SFX, master em 2 passadas.
    Com `saida_limpa`, grava também (no mesmo comando, mesmo ganho) a mix com `sfx_limpo` no lugar de `sfx`:
    a dos Shorts, sem os sons dos CTAs do longo. Devolve os créditos de música para a descrição."""
    cfg_som = config().get("som", {})
    mus_cfg = sb["meta"].get("musica") or {}
    mus, plano, creditos_mus = None, [], []
    if mus_cfg.get("arquivo"):
        for base in (Path(mus_cfg["arquivo"]), ep / mus_cfg["arquivo"], RAIZ / "assets" / "musica" / mus_cfg["arquivo"]):
            if base.exists():
                mus = base
                break
        if not mus:
            log(f"  aviso: música '{mus_cfg['arquivo']}' não encontrada — seguindo sem música")
    elif mus_cfg.get("auto", cfg_som.get("musica_auto", True)) and cenas:
        inicios = [c.inicio - cenas[0].inicio for c in cenas]
        blocos = [c.dado.get("bloco") for c in cenas]
        tipos = [c.dado["visual"]["tipo"] for c in cenas]
        try:
            plano, creditos_mus = musica.preparar(ep, sb, inicios, blocos, total, tipos)
        except Exception as e:  # sem internet / catálogo fora do ar: vídeo sai sem trilha, mas sai
            log(f"  aviso: trilha automática falhou ({e}) — seguindo sem música")
    entradas = ["-i", str(narracao)]
    partes, rotulos = [f"[0:a]apad,atrim=0:{total:.3f}[voz]"], ["[voz]"]
    if mus:
        voltas = int(total // max(1.0, duracao(mus))) + 1
        entradas += ["-stream_loop", str(voltas), "-t", f"{total + 0.5:.3f}", "-i", str(mus)]
        partes.append(f"[1:a]loudnorm=I=-20:TP=-2,afade=t=in:d=2,afade=t=out:st={max(0, total - 4):.2f}:d=4[m]")
    elif plano:
        # trilha renderizada à parte: num grafo só (várias faixas + amix) o FFmpeg entra em impasse
        trilha = ep / "build" / "trilha.wav"
        e_m, p_m = musica.filtro_trilha(plano, 0, total)
        rodar(["ffmpeg", "-y", "-v", "error", *e_m, "-filter_complex", ";".join(p_m), "-map", "[m]",
               "-t", f"{total:.3f}", "-ar", "48000", "-ac", "2", str(trilha)])
        entradas += ["-i", str(trilha)]
        partes.append("[1:a]anull[m]")
    if mus or plano:
        # ducking determinístico: envelope de ganho calculado dos tempos por palavra (sem sidechain)
        env = musica.envelope(palavras or [], total + 0.5, cfg_som.get("musica_db_pausa", -6.0),
                              cfg_som.get("musica_db_voz", -16.0), cfg_som.get("ducking_pausa_min", 0.6),
                              silencios=silencios_dramaticos(cenas or []))
        arq_env = ep / "build" / "ducking.f32"
        arq_env.write_bytes(env.tobytes())
        n_env = len([x for x in entradas if x == "-i"])
        entradas += ["-f", "f32le", "-ar", str(musica.ENV_HZ), "-ac", "1", "-i", str(arq_env)]
        vol = mus_cfg.get("volume", 1.0)  # ajuste fino por episódio (multiplica o envelope)
        partes.append(f"[{n_env}:a]aresample=48000,aformat=sample_fmts=flt:channel_layouts=stereo,"
                      f"atrim=0:{total:.3f}[env]")
        partes.append(f"[m]aformat=sample_fmts=flt:sample_rates=48000:channel_layouts=stereo,apad,"
                      f"atrim=0:{total:.3f}[mf]")
        partes.append(f"[mf][env]amultiply,volume={vol}[mduck]")
        rotulos.append("[mduck]")
    base_rot = list(rotulos)
    if sfx:
        n_in = len([x for x in entradas if x == "-i"])
        entradas += ["-i", str(sfx)]
        rotulos.append(f"[{n_in}:a]")
    partes.append(f"{''.join(rotulos)}amix=inputs={len(rotulos)}:duration=first:normalize=0[pre]")
    filtro = ";".join(partes)
    filtro_saida, mapas_extra = filtro, []
    if saida_limpa:
        # voz e trilha divididas em dois ramos: [pre] (com CTAs, medido) e [pre_l] (sem)
        div = [f"{r}asplit=2[sa{i}][sb{i}]" for i, r in enumerate(base_rot)]
        rot_a = [f"[sa{i}]" for i in range(len(base_rot))] + rotulos[len(base_rot):]
        rot_b = [f"[sb{i}]" for i in range(len(base_rot))]
        if sfx_limpo:
            n_in = len([x for x in entradas if x == "-i"])
            entradas_l = ["-i", str(sfx_limpo)]
            rot_b.append(f"[{n_in}:a]")
        else:
            entradas_l = []
        filtro_saida = ";".join(partes[:-1] + div + [
            f"{''.join(rot_a)}amix=inputs={len(rot_a)}:duration=first:normalize=0[pre]",
            f"{''.join(rot_b)}amix=inputs={len(rot_b)}:duration=first:normalize=0[pre_l]"])
        mapas_extra = entradas_l
    # master em 2 passadas: mede (loudnorm, json) e aplica ganho LINEAR + limitador de pico. (O loudnorm com
    # linear=true cai sozinho no modo dinâmico quando o ganho faria o pico passar do TP — o limitador evita isso.)
    med = _loudnorm_medir(entradas, filtro, total)
    ganho = -14.0 - float(med["input_i"])
    log(f"  master: medido {float(med['input_i']):.1f} LUFS, TP {float(med['input_tp']):.1f} dBTP, "
        f"LRA {float(med['input_lra']):.1f} -> ganho {ganho:+.1f} dB")
    teto = 10 ** (-2.0 / 20)  # pico (4× sobreamostrado) -2 dBFS → true peak abaixo de -1,5 dBTP
    master = f"volume={ganho:.2f}dB,aresample=192000,alimiter=limit={teto:.4f}:attack=2:release=80:level=0,aresample=48000"
    cmd = ["ffmpeg", "-y", "-v", "error", *entradas, *mapas_extra, "-filter_complex",
           f"{filtro_saida};[pre]{master}[a]" + (f";[pre_l]{master}[al]" if saida_limpa else ""), "-map", "[a]",
           "-t", f"{total:.3f}", "-ar", "48000", "-ac", "2", str(saida_audio)]
    if saida_limpa:
        cmd += ["-map", "[al]", "-t", f"{total:.3f}", "-ar", "48000", "-ac", "2", str(saida_limpa)]
    rodar(cmd)
    return creditos_mus


# ---------------------------------------------------------------- shorts e limpeza
def gerar_shorts(ep: Path, sb: dict, limpos: list[Path], audio: Path, total: float) -> None:
    """Concatena os blocos limpos + o mesmo mix em build/video_limpo.mp4, gera os Shorts a partir dele e apaga.
    Falha nos Shorts vira aviso: o episódio já está pronto."""
    import shorts
    video_limpo = ep / "build" / "video_limpo.mp4"
    lista = ep / "build" / "blocos_limpos.txt"
    try:
        if not shorts.tem_trechos(ep, sb):
            log("  shorts: nenhum trecho possível — pulando")
            return
        lista.write_text("\n".join(f"file '{x.resolve().as_posix()}'" for x in limpos), encoding="utf-8")
        rodar(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lista), "-i", str(audio),
               "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-b:a", "256k", "-t", f"{total:.3f}",
               str(video_limpo)])
        log("\nShorts (a partir da versão sem rótulos):")
        shorts.gerar(ep.name, video=video_limpo)
    except (Exception, SystemExit) as e:
        log(f"  aviso: Shorts falharam ({e}) — o episódio está pronto; rode `python pipeline/shorts.py {ep.name}`")
    finally:
        video_limpo.unlink(missing_ok=True)
        lista.unlink(missing_ok=True)


def limpar_build(ep: Path) -> None:
    """config.render.limpar_build: apaga os intermediários pesados (mezaninos, blocos, transições, shorts).
    O próximo montar.py re-renderiza tudo; narração, mídia e caches pequenos ficam."""
    import shutil
    livre = 0
    for nome in ("cenas", "blocos", "transicoes", "shorts"):
        d = ep / "build" / nome
        if d.is_dir() and not d.is_symlink():
            livre += sum(f.stat().st_size for f in d.rglob("*") if f.is_file())
            shutil.rmtree(d)
    f = ep / "build" / "video_mudo.mp4"
    if f.exists():
        livre += f.stat().st_size
        f.unlink()
    log(f"  build/ limpo: {livre / 1e9:.1f} GB liberados (render.limpar_build)")


# ---------------------------------------------------------------- principal
def ler_trecho(s: str | None) -> tuple[float, float] | None:
    if not s:
        return None

    def seg(x):
        p = [float(v) for v in x.split(":")]
        return sum(v * 60 ** i for i, v in enumerate(reversed(p)))
    a, b = s.split("-")
    return seg(a), seg(b)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("slug")
    ap.add_argument("--rascunho", action="store_true")
    ap.add_argument("--trecho", help="ex.: 0:30-1:30 — renderiza só as cenas nessa janela")
    ap.add_argument("--aceitar-faltando", action="store_true", help="final com placeholder onde faltar mídia (demo)")
    ap.add_argument("--sem-shorts", action="store_true", help="não gera os Shorts junto com o final")
    a = ap.parse_args()

    checar_ffmpeg()
    ep = pasta_episodio(a.slug)  # ativa o canal do episódio: config()/tokens() passam a ser os dele
    cfg = config()
    sb = ler_storyboard(ep)
    fps = cfg["video"]["fps"]
    w, h = (1280, 720) if a.rascunho else (cfg["video"]["largura"], cfg["video"]["altura"])
    (ep / "build").mkdir(exist_ok=True)
    final = ep / "final"
    final.mkdir(exist_ok=True)
    trecho = ler_trecho(a.trecho)

    cenas: list[Cena] = []
    faltando = []
    t = 0.0
    for c in sb["cenas"]:
        meta = ler_json(ep / "audio" / f"{c['id']}.json", None)
        if not meta:
            raise SystemExit(f"[erro] Sem narração para {c['id']}. Rode pipeline/narrar.py primeiro.")
        pausa = c.get("pausa_depois", cfg["pausa_padrao"])
        frames = max(1, round((meta["duracao"] + pausa) * fps))
        precisa = c["visual"]["tipo"] in TIPOS_COM_MIDIA
        midia = achar_midia(ep, c) if precisa or c["visual"]["tipo"] in remotion.TIPOS else None
        if precisa and midia is None:
            faltando.append(c["id"])
            if not (a.rascunho or a.aceitar_faltando):
                continue
        for parte, (dado, ini_f, n_f) in enumerate(dividir_em_subcortes(c, meta, frames, fps)):
            m = midia if parte == 0 else achar_midia(ep, dado)
            if parte and m is None and dado["visual"]["tipo"] in TIPOS_COM_MIDIA:
                faltando.append(dado["id"])
                if not (a.rascunho or a.aceitar_faltando):
                    continue
            cena = Cena(dado, m, n_f, inicio=t + ini_f / fps)
            desloc = ini_f / fps
            cena.extras["meta"] = {**meta, "palavras": [{**w, "ini": w["ini"] - desloc, "fim": w["fim"] - desloc}
                                                        for w in meta.get("palavras", [])]}
            cena.extras["orig"] = c["id"]
            cena.extras["meta_orig"] = meta
            cenas.append(cena)
        t += frames / fps
    if faltando and not (a.rascunho or a.aceitar_faltando):
        raise SystemExit(f"[erro] Falta mídia em: {', '.join(faltando)}. Rode buscar_midia/gerar_ia ou use --rascunho.")

    decidir_transicoes(cenas, fps, sb.get("versao", 1) >= 2)
    # CTAs (inscrever/like/comentar/combo): planejados no vídeo INTEIRO (o --trecho só recorta)
    ctas = cta.planejar(sb, cenas, fps)
    for x in ctas:
        log(f"  cta: {x['tipo']:<9} {mmss(x['t'])} ({x['dur']:.1f}s, {x['posicao']}, {x['origem']}, {x['cena']})")
    if trecho:
        cenas = [c for c in cenas if c.inicio + c.frames / fps > trecho[0] and c.inicio < trecho[1]]
        cenas[0].alca_antes = 0
        cenas[0].entrada = "corte"
        cenas[-1].alca_depois = 0

    # filtros do FFmpeg (zoompan, noise...) são quase todos single-thread: o ganho está em vários processos
    processos = cfg.get("render", {}).get("processos") or max(1, (os.cpu_count() or 4) // 3)
    for c in cenas:
        log(f"  {c.id}: {c.frames / fps:5.1f}s  {c.dado['visual']['tipo']:<17} entra:{c.entrada}")
    if remotion.disponivel():
        for c in parallax.escolher(cenas, fps, h):
            parallax.preparar(ep, c)
        for c in colagem.escolher(ep, cenas, fps):
            colagem.preparar(ep, c)
    animadas = [c for c in cenas if c.dado["visual"]["tipo"] in remotion.TIPOS]
    for c in animadas:  # era das cenas de mídia mais próximas → estilo de mapa/documento
        i = cenas.index(c)
        perto = sorted((x for x in cenas if x.midia), key=lambda x: abs(cenas.index(x) - i))
        c.extras["era_contexto"] = c.dado.get("era") or (estilo.era(perto[0].dado) if perto else "moderno")
    if animadas and remotion.disponivel():
        remotion.renderizar(ep, animadas, cenas, w, h, fps, a.rascunho, lambda c: vizinhas(ep, c, cenas))
    elif animadas:
        log("  aviso: Remotion indisponível (rode `python pipeline/remotion.py --instalar`) — usando cartelas simples")
        for c in animadas:
            c.dado = cartela_substituta(c.dado)
        animadas = []
    if ctas:
        ini_v, fim_v = cenas[0].inicio, cenas[0].inicio + sum(c.frames for c in cenas) / fps
        ctas = cta.renderizar(ep, cta.no_intervalo(ctas, ini_v, fim_v, False), w, h, fps)
    # objetos da história (cena.objetos): a coisa dita aparece e se transforma — por cima do acabamento, fora da
    # versão limpa (os Shorts renderizam os seus em 9:16)
    try:
        objs = objetos.renderizar(ep, objetos.planejar(sb, cenas), w, h, fps)
    except Exception as e:  # noqa: BLE001 — o vídeo sai sem os objetos, mas sai
        log(f"  aviso: objetos da história falharam ({type(e).__name__}: {e}) — vídeo sem eles")
        objs = []
    for x in objs:
        log(f"  objeto: {x['cena']} “{x['obj']['em']}” {mmss(x['t'])} ({x['dur']:.1f}s) "
            f"[{', '.join(a['tipo'] for a in x['acoes']) or 'aparece'}]")
    resto = [c for c in cenas if c not in animadas]
    with ThreadPoolExecutor(processos) as pool:
        for c, arq in zip(resto, pool.map(lambda c: render_cena(ep, c, cenas, w, h, fps, a.rascunho), resto)):
            c.arquivo = arq
    # tremor/flash pedidos no storyboard (som.eventos[].efeito, congelar): pós-passe em qualquer tipo de cena
    com_impacto = [c for c in cenas if impactos_da_cena(c, fps)]
    if com_impacto:
        with ThreadPoolExecutor(processos) as pool:
            list(pool.map(lambda c: aplicar_impactos(ep, c, w, h, fps), com_impacto))

    # Shorts saem do MESMO render: o bloco gera também uma versão sem rótulos/destaque (apagada no fim)
    fazer_shorts = (not a.rascunho and not trecho and not a.sem_shorts and cfg.get("shorts", {}).get("auto", True))
    grupos = blocos(cenas, processos)
    with ThreadPoolExecutor(processos) as pool:
        res = list(pool.map(lambda ig: render_bloco(ep, ig[0], ig[1], fps, not a.rascunho, ig[0] == 0,
                                                    ig[0] == len(grupos) - 1, trecho, w, h, fazer_shorts, (ctas or []) + objs),
                            enumerate(grupos)))
    arquivos = [r[0] for r in res]
    limpos = [r[1] for r in res if r[1]]
    lista = ep / "build" / "blocos.txt"
    lista.write_text("\n".join(f"file '{x.resolve().as_posix()}'" for x in arquivos), encoding="utf-8")
    video_mudo = ep / "build" / "video_mudo.mp4"
    rodar(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lista), "-c", "copy", str(video_mudo)])

    # narração: cada cena ORIGINAL (sub-cortes somados) preenchida até a sua duração no vídeo
    audios, palavras = [], []
    grupos_audio: dict[str, list[Cena]] = {}
    for c in cenas:
        grupos_audio.setdefault(c.extras["orig"], []).append(c)
    for orig, partes in grupos_audio.items():
        wav = ep / "build" / f"{orig}_audio.wav"
        dur = sum(x.frames for x in partes) / fps
        rodar(["ffmpeg", "-y", "-v", "error", "-i", str(ep / "audio" / f"{orig}.mp3"), "-af",
               f"apad=whole_dur={dur:.4f}", "-t", f"{dur:.4f}", "-ar", "48000", "-ac", "2", str(wav)])
        audios.append(wav)
        palavras += palavras_da_cena(partes[0].extras["meta_orig"], partes[0].inicio - cenas[0].inicio)
    lista_a = ep / "build" / "audios.txt"
    lista_a.write_text("\n".join(f"file '{x.resolve().as_posix()}'" for x in audios), encoding="utf-8")
    narracao = ep / "build" / "narracao.wav"
    rodar(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lista_a), "-c", "copy", str(narracao)])
    total = sum(c.frames for c in cenas) / fps
    audio = ep / "build" / "mix.wav"
    sfx, sfx_limpo, creditos_sfx = None, None, []
    audio_limpo = None
    if cfg.get("som", {}).get("sfx", True) and sb["meta"].get("sfx", True) is not False:
        eventos_sfx = som.planejar(cenas, fps)
        eventos_cta = (cta.eventos_sfx(ctas, cenas[0].inicio, total)
                       + objetos.eventos_sfx(objs, cenas[0].inicio, total))
        sfx = som.trilha_sfx(sorted(eventos_sfx + eventos_cta, key=lambda e: e["t"]), total, ep / "build" / "sfx.wav")
        creditos_sfx = som.creditos(eventos_sfx)
        if eventos_cta and fazer_shorts:
            # os Shorts saem da mix SEM os sons dos CTAs do longo (cada Short tem o seu)
            sfx_limpo = som.trilha_sfx(eventos_sfx, total, ep / "build" / "sfx_limpo.wav")
            audio_limpo = ep / "build" / "mix_limpo.wav"
    creditos_mus = mixar(ep, sb, narracao, total, audio, sfx, cenas, palavras, audio_limpo, sfx_limpo)

    sufixo = ("_rascunho" if a.rascunho else "") + ("_trecho" if trecho else "")
    saida = final / f"{sb['meta']['slug']}{sufixo}.mp4"
    rodar(["ffmpeg", "-y", "-v", "error", "-i", str(video_mudo), "-i", str(audio), "-map", "0:v", "-map", "1:a",
           "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-t", f"{total:.3f}", "-movflags", "+faststart", str(saida)])

    if not trecho:
        gerar_srt(palavras, final / f"{sb['meta']['slug']}.srt")
        try:
            thumbnail.gerar(ep.name)
        except Exception as e:  # thumbnail é proposta; não derruba o render
            log(f"  aviso: thumbnail falhou ({e})")
        # um início por cena do storyboard (sub-cortes também são Cena; o 1º pedaço marca o início)
        inicio_orig: dict[str, float] = {}
        for c in cenas:
            inicio_orig.setdefault(c.extras.get("orig", c.id), c.inicio)
        pend = gerar_descricao(sb, ep, [inicio_orig.get(c["id"], 0.0) for c in sb["cenas"]], total, final / "descricao.txt", creditos_mus,
                               creditos_sfx)
        pend.append("thumbnail_1..3.jpg: suba as 3 no 'Teste e compare' do Studio, modo 'Somente "
                    "miniatura' (títulos ficam para uma rodada depois — uma variável por teste); "
                    "depois registre o vencedor/CTR em final/ctr_log.json")
        salvar_json(final / "resumo.json", {"duracao": round(total, 2), "cenas": len(cenas), "faltando": faltando,
                                            "pendencias": pend, "video": saida.name, "cta": cta.resumo(ctas),
                                            "objetos": objetos.resumo(objs, cenas[0].inicio),
                                            "decisoes": {c.id: {"entrada": c.entrada, **{k: v for k, v in c.extras.items()
                                                                                          if k not in ("meta", "imagens_remotion")}} for c in cenas}})
    else:
        pend = []

    if fazer_shorts and len(limpos) == len(arquivos):
        gerar_shorts(ep, sb, limpos, audio_limpo or audio, total)
    elif fazer_shorts:
        log("  aviso: blocos limpos incompletos — Shorts não gerados")
    for x in limpos:  # a versão limpa não é guardada (~ tamanho do final)
        x.unlink(missing_ok=True)
    if audio_limpo:
        audio_limpo.unlink(missing_ok=True)
    if not a.rascunho and not trecho and cfg.get("render", {}).get("limpar_build", False):
        limpar_build(ep)

    log(f"\nPronto: {saida}  ({mmss(total)}, {duracao(saida):.1f}s)")
    if not trecho:
        log(f"Legendas: {final / (sb['meta']['slug'] + '.srt')}")
        log(f"Descrição: {final / 'descricao.txt'}")
    for p in pend:
        log(f"  PENDENTE: {p}")
    if faltando:
        log(f"  RASCUNHO com placeholders em: {', '.join(faltando)}")


if __name__ == "__main__":
    main()
