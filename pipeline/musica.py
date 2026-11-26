"""Trilha sonora: escolhe, baixa e encadeia músicas por bloco do roteiro, com licença registrada.

Fonte automática: catálogo do Kevin MacLeod (incompetech.com, ~1.400 faixas, CC BY 4.0 — exige o crédito,
que vai sozinho para a descrição). Uma faixa por trecho do vídeo (blocos curtos são agrupados), trocando
cravado no corte do capítulo/bloco (a anterior sai em 0,4 s, a nova entra no corte); nunca a mesma faixa em
dois episódios. O ducking sob a voz é um envelope calculado dos tempos por palavra (envelope()).

Ordem de prioridade:
  1. meta.musica.arquivo         arquivo seu (assets/musica/ ou caminho) — loop no vídeo inteiro, como antes
  2. meta.musica.por_bloco       {"climax": "epico", ...} ajusta o clima de blocos específicos
  3. meta.musica.clima           clima geral (tenso, melancólico, misterioso, épico, sombrio, esperançoso...)
Arquivos da Biblioteca de Áudio do YouTube / Pixabay Music: coloque em assets/musica/ e use 'arquivo'.

Uso:
  python pipeline/musica.py buscar tenso            # lista faixas do catálogo para um clima
  python pipeline/musica.py ouvir "Dark Fog"        # baixa para assets/musica/incompetech/ (para escutar)
  python pipeline/musica.py plano <slug>            # mostra a trilha que o montar.py vai usar
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import unicodedata
import urllib.parse
from pathlib import Path

import requests

from common import EPISODIOS, RAIZ, ler_json, log, salvar_json, user_agent
from estilo import rng

PASTA = RAIZ / "assets" / "musica"
CACHE = PASTA / "incompetech"
CATALOGO = CACHE / "catalogo.json"
URL_CATALOGO = "https://incompetech.com/music/royalty-free/pieces.json"
URL_MP3 = "https://incompetech.com/music/royalty-free/mp3-royaltyfree/"
LICENCA = "Creative Commons: By Attribution 4.0 License — http://creativecommons.org/licenses/by/4.0/"

# clima (pt) → "feel" do catálogo (desejados) e o que evitar
CLIMAS = {
    "tenso": ["Suspenseful", "Unnerving", "Intense", "Dark"],
    "suspense": ["Suspenseful", "Mysterious", "Unnerving"],
    "misterioso": ["Mysterious", "Eerie", "Mystical"],
    "sombrio": ["Dark", "Somber", "Eerie"],
    "melancolico": ["Somber", "Calming", "Relaxed"],
    "triste": ["Somber", "Calming"],
    "reflexivo": ["Calming", "Relaxed", "Somber"],
    "epico": ["Epic", "Intense", "Driving"],
    "dramatico": ["Epic", "Somber", "Intense"],
    "acao": ["Action", "Driving", "Intense"],
    "urgente": ["Driving", "Intense", "Action"],
    "esperancoso": ["Uplifting", "Bright", "Calming"],
    "inspirador": ["Uplifting", "Epic", "Bright"],
    "curioso": ["Mysterious", "Bouncy", "Relaxed"],
    "leve": ["Relaxed", "Bright", "Calming"],
}
EVITAR = {"Humorous", "Grooving", "Ren Faire", "Medieval"}
# clima padrão de cada bloco quando o storyboard não diz nada (combinado com o clima geral)
POR_BLOCO = {"gancho": "misterioso", "contexto": "reflexivo", "desenvolvimento": "curioso", "virada": "tenso",
             "climax": "epico", "conclusao": "melancolico"}
MIN_TRECHO = 45.0      # trechos menores são absorvidos pelo anterior (música trocando demais cansa)
CROSSFADE = 3.0
# troca cravada no capítulo: a faixa anterior sai em SAIDA_CAP s ANTES do corte, a nova entra no corte
SAIDA_CAP = 0.4
ENTRADA_CAP = 0.06     # só o bastante para não estalar
JANELA_CAP = 20.0      # s: uma troca de bloco "puxa" para a cena capítulo mais próxima dentro desta janela


def norm(s: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFD", (s or "").lower()) if ch.isalnum())


def catalogo() -> list[dict]:
    if not CATALOGO.exists() or time.time() - CATALOGO.stat().st_mtime > 30 * 86400:
        r = requests.get(URL_CATALOGO, headers={"User-Agent": user_agent()}, timeout=60)
        r.raise_for_status()
        CACHE.mkdir(parents=True, exist_ok=True)
        CATALOGO.write_text(r.text, encoding="utf-8")
    out = []
    for p in json.loads(CATALOGO.read_text(encoding="utf-8")):
        h, m, s = (int(x) for x in (p.get("length") or "0:0:0").split(":"))
        feels = {f.strip() for f in (p.get("feel") or "").split(",") if f.strip()}
        out.append({**p, "segundos": h * 3600 + m * 60 + s, "feels": feels})
    return out


def feels_de(clima: str | None) -> list[str]:
    """Aceita texto livre ("instrumental curiosa e com pulsação; tensa nos trágicos"): casa cada palavra pelo
    radical, na ordem em que aparece (o primeiro clima citado pesa mais)."""
    out: list[str] = []
    for palavra in re.findall(r"\w+", clima or ""):
        p = norm(palavra)
        for k, v in CLIMAS.items():
            if len(p) >= 4 and p[:4] == norm(k)[:4]:
                out += [f for f in v if f not in out]
    return out


def pontuar(p: dict, desejados: list[str], minimo: float) -> float:
    if p["segundos"] < min(minimo, 120) or p["feels"] & EVITAR:
        return -1
    nota = sum(3 - i * 0.6 for i, f in enumerate(desejados) if f in p["feels"])
    nota += min(p["segundos"], 300) / 300           # faixas longas repetem menos
    if re.search(r"vocal|voice|choir", (p.get("instruments") or "").lower()):
        nota -= 2                                     # voz cantada briga com a narração
    return nota


def usadas_em_outros(slug: str) -> set[str]:
    """Trilhas já usadas em OUTROS episódios do MESMO canal (canais diferentes podem repetir)."""
    from common import achar_episodio, canal_ativo, canal_da_pasta
    atual = achar_episodio(slug)
    out = set()
    for f in EPISODIOS.glob("*/build/trilha.json"):
        if f.parent.parent != atual and canal_da_pasta(f.parent.parent) == canal_ativo():
            out |= {t["arquivo"] for t in ler_json(f, {}).get("trechos", [])}
    return out


def baixar(p: dict) -> Path:
    destino = CACHE / p["filename"]
    if not destino.exists():
        CACHE.mkdir(parents=True, exist_ok=True)
        log(f"  música: baixando '{p['title']}'")
        r = requests.get(URL_MP3 + urllib.parse.quote(p["filename"]), headers={"User-Agent": user_agent()}, timeout=120)
        r.raise_for_status()
        destino.write_bytes(r.content)
    creditos = ler_json(PASTA / "creditos.json", {})
    creditos[p["filename"]] = {"titulo": p["title"], "autor": "Kevin MacLeod", "pagina": "https://incompetech.com",
                               "licenca": LICENCA, "requer_atribuicao": True}
    salvar_json(PASTA / "creditos.json", creditos)
    return destino


def credito(p: dict) -> str:
    return f'Música: "{p["title"]}" Kevin MacLeod (incompetech.com) — Licensed under {LICENCA}'


def trechos(sb: dict, inicios: list[float], blocos: list[str | None], total: float,
            tipos: list[str] | None = None) -> list[dict]:
    """Agrupa as cenas em trechos de clima contínuo. Toda troca é cravada (trecho["cravado"]) num corte: o
    início da cena "capitulo" mais próxima (com `tipos`) ou, sem capítulo por perto, a 1ª cena do bloco."""
    mus = sb["meta"].get("musica") or {}
    geral = mus.get("clima")
    extra = {norm(k): v for k, v in (mus.get("por_bloco") or {}).items()}
    out, ultimo = [], None
    for t, b in zip(inicios, blocos):
        b = b or ultimo
        if b == ultimo and out:
            continue
        ultimo = b
        clima = extra.get(norm(b or "")) or POR_BLOCO.get(norm(b or ""))
        desejados = feels_de(clima)
        if geral:  # o clima geral pesa: os dois primeiros "feels" dele entram na frente
            desejados = list(dict.fromkeys(feels_de(geral)[:2] + desejados))
        out.append({"ini": t, "bloco": b, "clima": clima or geral, "feels": desejados or ["Mysterious", "Somber"]})
    # absorve trechos curtos no anterior
    fundidos = []
    for i, tr in enumerate(out):
        fim = out[i + 1]["ini"] if i + 1 < len(out) else total
        if fundidos and fim - tr["ini"] < MIN_TRECHO:
            continue
        fundidos.append(tr)
    if not fundidos:
        fundidos = [{"ini": 0.0, "bloco": None, "clima": geral, "feels": feels_de(geral) or ["Mysterious", "Somber"]}]
    fundidos[0]["ini"] = 0.0
    caps = [t for t, tp in zip(inicios, tipos or []) if tp == "capitulo"]
    for i in range(1, len(fundidos)):
        tr = fundidos[i]
        lo = fundidos[i - 1]["ini"] + 1.0
        hi = fundidos[i + 1]["ini"] - 1.0 if i + 1 < len(fundidos) else total - 1.0
        perto = [t for t in caps if lo < t < hi and abs(t - tr["ini"]) <= JANELA_CAP]
        if perto:
            tr["ini"] = min(perto, key=lambda t: abs(t - tr["ini"]))
        tr["cravado"] = True  # toda troca cai num corte (capítulo ou 1ª cena do bloco): nada de crossfade longo
    for i, tr in enumerate(fundidos):
        tr["fim"] = fundidos[i + 1]["ini"] if i + 1 < len(fundidos) else total
    return fundidos


def planejar(sb: dict, inicios: list[float], blocos: list[str | None], total: float,
             tipos: list[str] | None = None) -> list[dict]:
    slug = sb["meta"]["slug"]
    cat = catalogo()
    proibidas = usadas_em_outros(slug)
    usadas: set[str] = set()
    plano = []
    for k, tr in enumerate(trechos(sb, inicios, blocos, total, tipos)):
        dur = tr["fim"] - tr["ini"]
        cands = sorted(((pontuar(p, tr["feels"], dur), p) for p in cat
                        if p["filename"] not in proibidas | usadas), key=lambda x: -x[0])
        cands = [p for n, p in cands[:12] if n > 0]
        if not cands:
            continue
        p = rng({"id": slug}, f"musica-{k}").choice(cands[:6])   # estável por episódio, mas não sempre a 1ª
        usadas.add(p["filename"])
        plano.append({**tr, "titulo": p["title"], "arquivo": p["filename"], "feel": sorted(p["feels"]),
                      "faixa_seg": p["segundos"], "credito": credito(p), "_p": p})
    return plano


def preparar(ep: Path, sb: dict, inicios: list[float], blocos: list[str | None], total: float,
             tipos: list[str] | None = None) -> tuple[list[dict], list[str]]:
    """Baixa o que faltar e devolve (trechos com caminho local, créditos para a descrição). Cache em build/trilha.json."""
    destino = ep / "build" / "trilha.json"
    antigo = ler_json(destino, {})
    plano = planejar(sb, inicios, blocos, total, tipos)
    # mantém as faixas de um render anterior se os trechos não mudaram de clima (evita trocar a música a cada ajuste)
    ant = {(t["bloco"], t["clima"]): t for t in antigo.get("trechos", [])}
    cat = {p["filename"]: p for p in catalogo()}
    for t in plano:
        velho = ant.get((t["bloco"], t["clima"]))
        if velho and velho["arquivo"] in cat and velho["arquivo"] not in {x["arquivo"] for x in plano if x is not t}:
            p = cat[velho["arquivo"]]
            t.update(titulo=p["title"], arquivo=p["filename"], feel=sorted(p["feels"]), faixa_seg=p["segundos"],
                     credito=credito(p), _p=p)
    for t in plano:
        t["caminho"] = str(baixar(t.pop("_p")))
    salvar_json(destino, {"trechos": plano})
    for t in plano:
        log(f"  música {t['ini']:6.1f}–{t['fim']:6.1f}s{' (capítulo)' if t.get('cravado') else ''}  "
            f"[{t['clima']}] {t['titulo']} ({', '.join(t['feel'])})")
    return plano, list(dict.fromkeys(t["credito"] for t in plano))


def filtro_trilha(plano: list[dict], primeira_entrada: int, total: float) -> tuple[list[str], list[str]]:
    """(args de entrada, partes do filter_complex) que produzem [m]: as faixas encadeadas com crossfade
    (ou, na troca cravada num capítulo, saída de SAIDA_CAP s antes do corte e entrada seca no corte)."""
    entradas, partes = [], []
    for k, t in enumerate(plano):
        prox = plano[k + 1] if k + 1 < len(plano) else None
        cravado = k > 0 and t.get("cravado")
        ini = t["ini"] if k == 0 or cravado else t["ini"] - CROSSFADE / 2
        fim = t["fim"] + (CROSSFADE / 2 if prox and not prox.get("cravado") else 0)
        dur = max(1.0, fim - ini)
        fi = 2.0 if k == 0 else (ENTRADA_CAP if cravado else CROSSFADE)
        fo = SAIDA_CAP if prox and prox.get("cravado") else CROSSFADE
        # começa um pouco depois do início da faixa (introduções costumam ser vazias) só se ela for longa
        ofs = 4.0 if t["faixa_seg"] > dur + 20 else 0.0
        # entrada FINITA: com -stream_loop -1 o FFmpeg nunca fecha o grafo e a mixagem trava no fim
        voltas = int((dur + ofs) // max(1, t["faixa_seg"])) + 1
        entradas += ["-stream_loop", str(voltas), "-ss", f"{ofs:.1f}", "-t", f"{dur + 0.5:.3f}", "-i", t["caminho"]]
        idx = primeira_entrada + k
        partes.append(f"[{idx}:a]aresample=48000,aformat=channel_layouts=stereo,atrim=0:{dur:.3f},asetpts=PTS-STARTPTS,"
                      f"loudnorm=I=-20:TP=-2:LRA=7,"
                      f"afade=t=in:d={fi:.2f},afade=t=out:st={max(0, dur - fo):.2f}:d={fo:.2f},"
                      f"adelay={int(ini * 1000)}|{int(ini * 1000)}[mt{k}]")
    if len(plano) == 1:
        partes.append("[mt0]anull[mraw]")
    else:
        partes.append("".join(f"[mt{k}]" for k in range(len(plano))) + f"amix=inputs={len(plano)}:normalize=0[mraw]")
    partes.append(f"[mraw]apad,atrim=0:{total:.3f},afade=t=out:st={max(0, total - 4):.2f}:d=4[m]")
    return entradas, partes


# ---------------------------------------------------------------- ducking determinístico
ENV_HZ = 1000          # resolução do envelope (o FFmpeg reamostra para 48 kHz com interpolação)


def falas(palavras, juntar: float = 0.6) -> list[tuple[float, float]]:
    """Trechos com voz: palavras (texto, ini, fim) com pausas <= `juntar` s fundidas num trecho só."""
    out: list[list[float]] = []
    for _, a, b in sorted(palavras, key=lambda p: p[1]):
        if out and a - out[-1][1] <= juntar:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [(a, b) for a, b in out]


def envelope(palavras, total: float, pausa_db: float, voz_db: float, juntar: float = 0.6,
             antes: float = 0.15, rampa: float = 0.3, depois: float = 0.1,
             silencios: list[tuple[float, float]] | None = None) -> "np.ndarray":
    """Ganho linear da trilha a ENV_HZ amostras/s. Sob a voz = voz_db; em pausas > `juntar` s, cartelas e
    capítulos = pausa_db. Descida de `rampa` s centrada `antes` s antes da 1ª palavra (chega ao fundo na
    fala); subida de `rampa` s começando `depois` s após a última. Sem compressor: nada de "bombear"."""
    import numpy as np

    n = int(total * ENV_HZ) + 1
    t = np.arange(n) / ENV_HZ
    db = np.full(n, float(pausa_db))
    for a, b in falas(palavras, juntar):
        x0, x1 = a - antes - rampa / 2, a - antes + rampa / 2
        y0, y1 = b + depois, b + depois + rampa
        i0, i1 = max(0, int(x0 * ENV_HZ)), min(n, int(y1 * ENV_HZ) + 2)
        if i0 >= i1:
            continue
        curva = np.interp(t[i0:i1], [x0, x1, y0, y1], [pausa_db, voz_db, voz_db, pausa_db])
        db[i0:i1] = np.minimum(db[i0:i1], curva)
    # silêncio dramático (som.silencio): a música some `dur` s antes da palavra (saída de 150 ms) e
    # volta em 400 ms a partir dela — o impacto do som.py cai no retorno
    for tp, dur in silencios or []:
        a, b = tp - dur, tp
        i0, i1 = max(0, int((a - 0.15) * ENV_HZ)), min(n, int((b + 0.4) * ENV_HZ) + 2)
        if i0 < i1:
            curva = np.interp(t[i0:i1], [a - 0.15, a, b, b + 0.4], [0, -60, -60, 0])
            db[i0:i1] = db[i0:i1] + curva
    return (10 ** (db / 20)).astype("<f4")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("acao", choices=["buscar", "ouvir", "plano"])
    ap.add_argument("alvo")
    a = ap.parse_args()
    if a.acao == "buscar":
        fe = feels_de(a.alvo) or [a.alvo.capitalize()]
        for n, p in sorted(((pontuar(p, fe, 180), p) for p in catalogo()), key=lambda x: -x[0])[:20]:
            print(f"{n:4.1f}  {p['title']:<36} {p['length']}  {', '.join(sorted(p['feels']))}  — {p['description'][:70]}")
    elif a.acao == "ouvir":
        p = next((p for p in catalogo() if norm(p["title"]) == norm(a.alvo)), None)
        if not p:
            sys.exit("faixa não encontrada")
        print(baixar(p))
    else:
        from common import ler_storyboard, pasta_episodio
        ep = pasta_episodio(a.alvo)
        sb = ler_storyboard(ep)
        t, inis = 0.0, []
        for c in sb["cenas"]:
            inis.append(t)
            t += len(c["narracao"].split()) / 140 * 60 + 0.5
        for tr in planejar(sb, inis, [c.get("bloco") for c in sb["cenas"]], t):
            print(f"{tr['ini']:6.1f}–{tr['fim']:6.1f}s  [{tr['clima']}] {tr['titulo']}  ({', '.join(tr['feel'])})")


if __name__ == "__main__":
    main()
