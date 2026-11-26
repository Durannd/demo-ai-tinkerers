"""Chamadas para o público (CTA): inscrever, like, comentar e combo — ícones animados em Remotion.

Cada CTA é uma animação curta (~3–6 s) renderizada com FUNDO TRANSPARENTE (ProRes 4444, só a área do cartão,
não o quadro inteiro) por render/cta/ (entrada própria do Remotion: mexer nela NÃO invalida o cache das cenas)
e sobreposta pelo montar.py no bloco, DEPOIS do acabamento de cor (grão/vinheta não acinzentam o vermelho) e no
mesmo ramo dos rótulos — a versão limpa (fonte dos Shorts) sai sem ela, e a mix limpa sai sem os SFX dela.

  inscrever  botão "INSCREVA-SE" que um cursor clica e vira "INSCRITO"; depois o cursor toca o sininho, que balança
  like       polegar que pula com partículas/brilho, "+1" e contador subindo
  comentar   balão de fala que surge e a pergunta (`texto`) se digita dentro
  combo      like → inscrever → sino em sequência rápida (nos Shorts: like + inscrever, o sino toca sozinho)

Storyboard (opcional, retrocompatível):
  cena.cta  = {"tipo", "em": "palavra exata da narração", "texto": "pergunta (comentar)", "posicao"}
  meta.cta  = {"auto": true, "pergunta": "…", "posicao": "dir_baixo", "shorts": true}  (ou false = nenhum CTA)
Com `auto` (padrão: true quando meta.cta existe; sem meta.cta, config cta.auto — false) e nenhuma cena com `cta`,
o pipeline escolhe os momentos (planejar): inscrever logo depois do gancho, like perto da metade, comentar no bloco
`conclusao` antes da última frase. Paleta: tokens.cta (opcional) > tokens.domino (fundo, marfim, tijolo, ouro).
Textos fixos: pipeline/i18n.py (vão nas props; o i18n.ts das cenas não muda).
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from common import RAIZ, canal_ativo, config, idioma, log, tokens

TIPOS = ("inscrever", "like", "comentar", "combo")
POSICOES = ("dir_baixo", "dir_cima", "esq_cima")
TIPOS_SHORT = ("combo", "inscrever")
VERSAO = "1"
PADRAO = {
    "ativo": True,               # false desliga todos os CTAs (cena.cta e auto)
    "auto": False,               # sem meta.cta: episódios antigos não ganham CTA sozinhos
    "auto_tipos": ["inscrever", "like", "comentar"],
    "posicao": "dir_baixo",
    "min_inicio": 20.0,          # s: nada de CTA antes disso (o gancho é sagrado)
    "intervalo_min": 45.0,       # s entre os inícios de dois CTAs automáticos
    "inscrever_ate": 40.0,       # s depois da 1ª troca de bloco em que o inscrever ainda pode cair
    "sfx": True,
    "sfx_db": 0.0,               # ajuste fino dos SFX dos CTAs (somado ao som.GANHO de cada categoria)
    "concorrencia": 4,           # threads do Remotion para os CTAs (são pequenos; poupa memória)
}
# canvas de cada tipo em "u" (1 u = 1 px a 1080 de altura no 16:9; no 9:16, 1 u = 1 px a 1080 de largura).
# O cartão fica dentro, alinhado ao canto, com MARGEM u de folga para partículas, sombra e o cursor.
CANVAS = {"inscrever": (520, 196), "like": (500, 196), "combo": (580, 196)}
MARGEM = 40
COMENTAR_LARG = 520            # largura do balão (u)
COMENTAR_FONTE, COMENTAR_LINHA = 30, 1.28
COMENTAR_CPS = 22.0            # caracteres por segundo da digitação
TELA_X, TELA_Y = 36, 52        # u do canvas até a borda da tela (16:9)
# no 16:9 o cartão ocupa ~22–27% da largura: inscrever ≈ 23%, like ≈ 21%, combo ≈ 26%, comentar ≈ 27%
ESCALA_16X9 = {"inscrever": 1.15, "like": 1.15, "combo": 1.15, "comentar": 1.0}
SHORT_ESCALA = 1.3             # no 9:16 o combo ocupa ~52% da largura
SHORT_DUR = 2.8                # s do combo compacto do Short
SHORT_FOLGA_FIM = 0.6          # some antes dos últimos 0,6 s (não quebra o loop)
SHORT_BASE_Y = 1075            # px (em 1080×1920): base do canvas, acima da legenda pop (linha de base 1180)


def cfg() -> dict:
    d = dict(PADRAO)
    d.update(config().get("cta") or {})
    return d


# ---------------------------------------------------------------- tempos (fonte única: TSX e SFX usam estes)
def tempos(tipo: str, texto: str = "", compacto: bool = False, dur: float | None = None) -> dict:
    """Instantes (s desde o 1º quadro do CTA). `sai`→`fim` = animação de saída."""
    if tipo == "inscrever":
        if compacto:
            d = dur or SHORT_DUR
            return {"cursor": 0.12, "clique": 0.75, "sino": 1.0, "sai": d - 0.42, "fim": d}
        return {"cursor": 0.3, "clique": 1.05, "clique_sino": 1.85, "sino": 1.88, "sai": 3.55, "fim": 4.05}
    if tipo == "like":
        return {"like": 0.65, "sai": 3.25, "fim": 3.75}
    if tipo == "combo":
        if compacto:
            d = dur or SHORT_DUR
            return {"cursor": 0.1, "like": 0.48, "clique": 1.05, "sino": 1.3, "sai": d - 0.42, "fim": d}
        return {"cursor": 0.25, "like": 0.8, "clique": 1.55, "clique_sino": 2.3, "sino": 2.33, "sai": 3.9, "fim": 4.4}
    # comentar: o balão surge, três pontinhos, a pergunta se digita e fica ~1,8 s
    ini = 0.95
    fim_tipo = ini + len(texto) / COMENTAR_CPS
    sai = max(fim_tipo + 1.8, 3.6)
    return {"bolha": 0.12, "tipo": ini, "cps": COMENTAR_CPS, "tipo_fim": round(fim_tipo, 3), "sai": round(sai, 3),
            "fim": round(sai + 0.45, 3)}


def duracao(tipo: str, texto: str = "") -> float:
    return tempos(tipo, texto)["fim"]


def sfx_relativos(tipo: str, tp: dict) -> list[tuple[float, str, float]]:
    """(s desde o início do CTA, categoria do som.py, ganho extra em dB)."""
    ev = [(0.02, "cta_pop", -5.0)]
    if tp.get("like") is not None:
        ev += [(tp["like"] - 0.01, "cta_pop", 1.0), (tp["like"] + 0.05, "cta_brilho", 0.0)]
        if tipo == "combo":
            ev.append((tp["like"] - 0.03, "cta_clique", -2.0))
    if tp.get("clique") is not None:
        ev.append((tp["clique"] - 0.01, "cta_clique", 0.0))
    if tp.get("clique_sino") is not None:
        ev.append((tp["clique_sino"] - 0.01, "cta_clique", -1.0))
    if tp.get("sino") is not None:
        ev.append((tp["sino"], "cta_sino", 0.0))
    if tipo == "comentar":
        ev.append((tp["tipo_fim"] + 0.05, "cta_pop", -7.0))
    return ev


# ---------------------------------------------------------------- textos e tamanho do comentário
def textos() -> dict:
    import i18n
    return {k: i18n.t(f"cta_{k}") for k in ("inscrever", "inscrito", "like", "comentar")}


def linhas_comentario(texto: str) -> int:
    """Linhas que a pergunta ocupa no balão (mesma fonte e largura útil do TSX), para dimensionar o canvas."""
    try:
        import graficos
        f = graficos.fonte("rotulo", COMENTAR_FONTE * 4)
        medir = lambda s: f.getlength(s) / 4
    except Exception:  # noqa: BLE001 — sem a fonte, estimativa por caractere
        medir = lambda s: len(s) * COMENTAR_FONTE * 0.56
    util = COMENTAR_LARG - 2 * 26 - 14
    linhas, atual = 1, ""
    for p in texto.split():
        cand = f"{atual} {p}".strip()
        if medir(cand) > util and atual:
            linhas += 1
            atual = p
        else:
            atual = cand
    return linhas


def canvas(tipo: str, texto: str = "") -> tuple[int, int]:
    if tipo == "comentar":
        n = linhas_comentario(texto)
        alto = 46 + 12 + (n + 0.6) * COMENTAR_FONTE * COMENTAR_LINHA + 44 + 18
        return COMENTAR_LARG + 2 * MARGEM + 20, int(alto + 2 * MARGEM)
    return CANVAS[tipo]


# ---------------------------------------------------------------- planejamento (montar.py)
def meta_cta(sb: dict) -> dict | None:
    """meta.cta normalizado: None = ausente; {"desligado": True} = false explícito."""
    m = sb.get("meta", {}).get("cta")
    if m is False:
        return {"desligado": True}
    if m is True:
        return {}
    return m if isinstance(m, dict) else None


def tem_cta(sb: dict) -> bool:
    """O episódio pediu CTA (meta.cta ou cena.cta)? Usado pelos Shorts ('auto')."""
    if not cfg().get("ativo", True):
        return False
    m = meta_cta(sb)
    if m and m.get("desligado"):
        return False
    return m is not None or any(isinstance(c.get("cta"), dict) for c in sb.get("cenas", []))


def _auto_ligado(sb: dict) -> bool:
    m = meta_cta(sb)
    if m is None:
        return bool(cfg().get("auto"))
    return not m.get("desligado") and m.get("auto", True) is not False


def _norm(x: str) -> str:
    import unicodedata
    x = unicodedata.normalize("NFD", str(x).lower())
    return "".join(ch for ch in x if ch.isalnum() or ch == "%")


def _palavras_orig(cenas: list) -> list[tuple[str, float, float, str]]:
    """(texto, ini_abs, fim_abs, id da cena original) de todas as palavras do vídeo (sub-cortes: uma vez)."""
    out, vistos = [], set()
    for c in cenas:
        orig = c.extras.get("orig", c.id)
        if orig in vistos:
            continue
        vistos.add(orig)
        for p in (c.extras.get("meta_orig") or c.extras.get("meta") or {}).get("palavras") or []:
            out.append((p["texto"], c.inicio + p["ini"], c.inicio + p["fim"], orig))
    return out


def _ocupados(cenas: list, fps: int) -> list[tuple[float, float, str]]:
    """Janelas em que um CTA automático não entra: gráfico animado (Remotion, menos parallax), marcação desenhada
    e texto cinético na tela."""
    import marcas
    import remotion
    out = []
    for c in cenas:
        a, b = c.inicio, c.inicio + c.frames / fps
        tipo = c.dado["visual"]["tipo"]
        if tipo in remotion.TIPOS and tipo != "parallax":
            out.append((a, b, f"{c.id} ({tipo})"))
        elif marcas.lista(c.dado):
            out.append((a, b, f"{c.id} (marca)"))
        elif (c.dado.get("destaque") or {}).get("texto"):
            out.append((a, b, f"{c.id} (destaque)"))
    return out


def planejar(sb: dict, cenas: list, fps: int) -> list[dict]:
    """[{tipo, t (s no relógio do vídeo inteiro), posicao, texto, cena, origem, tempos, dur}] ordenados.
    cenas = montar.Cena do vídeo INTEIRO (antes do --trecho)."""
    c_cfg = cfg()
    m = meta_cta(sb) or {}
    if not c_cfg.get("ativo", True) or m.get("desligado") or not cenas:
        return []
    pos_padrao = m.get("posicao") or c_cfg.get("posicao", "dir_baixo")
    pergunta = (m.get("pergunta") or "").strip()
    total = sum(c.frames for c in cenas) / fps
    t0 = cenas[0].inicio
    out: list[dict] = []

    # 1. pedidos do roteiro (cena.cta): âncora = palavra exata da narração da cena
    import remotion
    explicitos = False
    for c in cenas:
        orig = c.extras.get("orig", c.id)
        pedido = c.dado.get("cta")
        if not isinstance(pedido, dict) or c.id != orig:
            continue
        explicitos = True
        tipo = pedido.get("tipo")
        if tipo not in TIPOS:
            log(f"  cta: {orig} com tipo '{tipo}' desconhecido — ignorado")
            continue
        pal = (c.extras.get("meta_orig") or c.extras.get("meta") or {}).get("palavras") or []
        tp = remotion.achar_na_fala(pal, pedido.get("em"))
        if tp is None:
            log(f"  cta: {orig} — '{pedido.get('em')}' não está na narração; CTA ignorado (rode o validar)")
            continue
        texto = (pedido.get("texto") or (pergunta if tipo == "comentar" else "")).strip()
        if tipo == "comentar" and not texto:
            log(f"  cta: {orig} — comentar sem 'texto' (nem meta.cta.pergunta); CTA ignorado")
            continue
        out.append({"tipo": tipo, "t": round(max(t0, c.inicio + tp - 0.1), 3), "posicao": pedido.get("posicao") or pos_padrao,
                    "texto": texto if tipo == "comentar" else "", "cena": orig, "origem": "cena"})

    # 2. automático (só sem pedidos nas cenas)
    if not explicitos and _auto_ligado(sb):
        out += _auto(sb, cenas, fps, total, pos_padrao, pergunta, c_cfg)

    for x in out:
        x["tempos"] = tempos(x["tipo"], x["texto"])
        x["dur"] = x["tempos"]["fim"]
        fim_video = t0 + total
        if x["t"] + x["dur"] > fim_video - 0.3:   # não atravessa o fim do vídeo
            x["t"] = round(max(t0, fim_video - 0.3 - x["dur"]), 3)
    return sorted(out, key=lambda x: x["t"])


def _auto(sb: dict, cenas: list, fps: int, total: float, pos: str, pergunta: str, c_cfg: dict) -> list[dict]:
    t0 = cenas[0].inicio
    fim_video = t0 + total
    ocup = _ocupados(cenas, fps)
    pal = _palavras_orig(cenas)
    # inícios de frase (preferidos) e de palavra
    frases = [p[1] for i, p in enumerate(pal) if i == 0 or pal[i - 1][3] != p[3] or re.search(r"[.!?…:;]$", pal[i - 1][0])]
    todas = [p[1] for p in pal]
    escolhidos: list[dict] = []
    tipos_auto = [t for t in (c_cfg.get("auto_tipos") or []) if t in ("inscrever", "like", "comentar")]
    min_ini = t0 + float(c_cfg.get("min_inicio", 20.0))
    intervalo = float(c_cfg.get("intervalo_min", 45.0))

    def livre(a: float, dur: float, relaxar: bool = False) -> bool:
        b = a + dur
        if a < min_ini or b > fim_video - 1.5:
            return False
        if any(abs(a - e["t"]) < intervalo or (a < e["t"] + e["dur"] and e["t"] < b) for e in escolhidos):
            return False
        return relaxar or not any(x < b and a < y for x, y, _ in ocup)

    def achar(lo: float, hi: float, dur: float, ordem: str, relaxar: bool = False) -> float | None:
        grade = [lo + k * 0.5 for k in range(int(max(0.0, hi - lo) / 0.5) + 1)]
        for cands in (frases, todas, grade):
            cs = [x - 0.1 for x in cands if lo <= x - 0.1 <= hi]
            if ordem == "cedo":
                cs.sort()
            elif ordem == "tarde":
                cs.sort(reverse=True)
            else:
                cs.sort(key=lambda x: abs(x - (lo + hi) / 2))
            for a in cs:
                if livre(a, dur, relaxar):
                    return round(a, 3)
        return None

    def add(tipo: str, a: float | None, texto: str = "", motivo: str = "") -> None:
        if a is None:
            log(f"  cta auto: sem lugar livre para '{tipo}'{(' — ' + motivo) if motivo else ''} — pulado")
            return
        cena = next((c.extras.get("orig", c.id) for c in cenas if c.inicio <= a < c.inicio + c.frames / fps),
                    cenas[-1].id)
        escolhidos.append({"tipo": tipo, "t": a, "posicao": pos, "texto": texto, "cena": cena, "origem": "auto",
                           "dur": duracao(tipo, texto)})

    blocos = [(c.inicio, c.dado.get("bloco")) for c in cenas if c.dado.get("bloco")]
    # comentar primeiro (é o mais preso: no fim, antes da última frase); depois inscrever e like
    if "comentar" in tipos_auto:
        if not pergunta:
            log("  cta auto: meta.cta.pergunta vazia — sem 'comentar'")
        else:
            dur = duracao("comentar", pergunta)
            ult_cena = cenas[-1].extras.get("orig", cenas[-1].id)
            ult = [p for p in pal if p[3] == ult_cena]
            idx = max([i for i, p in enumerate(ult) if i == 0 or re.search(r"[.!?…]$", ult[i - 1][0])] or [0])
            t_ult = ult[idx][1] if ult else fim_video - 2.0
            conc = next((a for a, b in blocos if b == "conclusao"), t0 + total * 0.75)
            hi = t_ult - 0.25 - dur
            lo = min(conc, hi - 20.0)
            a = achar(lo, hi, dur, "tarde")
            if a is None:
                a = achar(lo, hi, dur, "tarde", relaxar=True)
                if a is not None:
                    log(f"  cta auto: 'comentar' em {a - t0:.1f}s cai sobre gráfico/marca (o bloco final não tem plano livre)")
            add("comentar", a, pergunta, "conclusão curta demais para a pergunta")
    if "inscrever" in tipos_auto:
        dur = duracao("inscrever")
        primeiro = blocos[0][1] if blocos else None
        troca = next((a for a, b in blocos if b != primeiro), None)
        lo = max(min_ini, troca if troca is not None else t0 + 40.0)
        add("inscrever", achar(lo, lo + float(c_cfg.get("inscrever_ate", 40.0)), dur, "cedo"), "",
            "o começo está tomado por gráficos/marcas")
    if "like" in tipos_auto:
        dur = duracao("like")
        meio = t0 + total * 0.5
        add("like", achar(meio - total * 0.2, meio + total * 0.2, dur, "meio"), "",
            "vídeo curto ou meio tomado por gráficos/marcas")
    return [{k: v for k, v in e.items() if k != "dur"} for e in sorted(escolhidos, key=lambda e: e["t"])]


# ---------------------------------------------------------------- render (Remotion, render/cta)
def _versao_codigo() -> str:
    h = hashlib.sha1()
    pasta = RAIZ / "render"
    for f in sorted((pasta / "cta").rglob("*.ts*")) + [pasta / "src" / "comp" / "tokens.ts", pasta / "src" / "comp" / "Base.tsx"]:
        if f.exists():
            h.update(f.read_bytes())
    return h.hexdigest()


def _lado_ancora(posicao: str) -> tuple[str, str]:
    lado = "esq" if posicao.startswith("esq") else "dir"
    return lado, ("cima" if posicao.endswith("cima") else "baixo")


def _props(x: dict, esc: float, fps: int, lado: str, ancora: str, compacto: bool = False) -> dict:
    cw, ch = canvas(x["tipo"], x.get("texto", ""))
    seed = int(hashlib.sha1(f"{x.get('cena', '')}|{x['tipo']}|{x.get('texto', '')}".encode()).hexdigest()[:8], 16)
    tk = tokens()
    return {"id": f"cta_{x['tipo']}", "tipo": x["tipo"], "largura": int(round(cw * esc / 2) * 2),
            "altura": int(round(ch * esc / 2) * 2), "fps": fps, "frames": max(2, round(x["tempos"]["fim"] * fps)),
            "escala": round(esc, 5), "lado": lado, "ancora": ancora, "compacto": compacto, "tempos": x["tempos"],
            "texto": x.get("texto", ""), "textos": textos(), "seed": seed, "contador": 1000 + seed % 8000,
            "canal": canal_ativo(), "idioma": idioma(), "tokens": tk}


def _render_fila(trabalhos: list[tuple[Path, dict]]) -> None:
    import remotion
    pend = [(s, p) for s, p in trabalhos if not s.exists()]
    if not pend:
        return
    remotion.preparar_publico()
    c_cfg = cfg()
    fila = {"concorrencia": c_cfg.get("concorrencia") or None, "gl": config().get("render", {}).get("gl_remotion"),
            "entrada": "cta/index.ts",
            "trabalhos": [{"props": p, "saida": str(s.with_suffix(".tmp.mov")), "composicao": "Cta", "alfa": True}
                          for s, p in pend]}
    import subprocess
    import sys
    arq = remotion.RENDER / ".fila_cta.json"
    arq.write_text(json.dumps(fila, ensure_ascii=False), encoding="utf-8")
    log(f"  CTA: {len(pend)} animação(ões) para renderizar (Remotion, fundo transparente)")
    proc = subprocess.run([remotion.node(), str(remotion.RENDER / "renderizar.mjs"), str(arq)], cwd=remotion.RENDER,
                          capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode:
        sys.stderr.write(proc.stdout[-4000:] + proc.stderr[-3000:])
        raise RuntimeError("render Remotion dos CTAs falhou (veja acima)")
    for s, _ in pend:
        s.with_suffix(".tmp.mov").replace(s)


def renderizar(ep: Path, ctas: list[dict], w: int, h: int, fps: int) -> list[dict]:
    """16:9: preenche arquivo/x/y/hash de cada CTA (cache build/cta/<tipo>_<hash>.mov). Sem Remotion: []."""
    import remotion
    if not ctas:
        return []
    if not remotion.disponivel():
        log("  aviso: Remotion indisponível — vídeo sai SEM os CTAs")
        return []
    pasta = ep / "build" / "cta"
    pasta.mkdir(parents=True, exist_ok=True)
    trabalhos = []
    for x in ctas:
        lado, ancora = _lado_ancora(x.get("posicao") or "dir_baixo")
        esc = h / 1080 * ESCALA_16X9.get(x["tipo"], 1.0)
        props = _props(x, esc, fps, lado, ancora)
        hs = hashlib.sha1(json.dumps([VERSAO, props, _versao_codigo()], sort_keys=True).encode()).hexdigest()[:14]
        x["arquivo"] = pasta / f"{x['tipo']}_{hs}.mov"
        x["hash"] = hs
        cw, ch = props["largura"], props["altura"]
        x["x"] = (w - TELA_X * esc - cw) if lado == "dir" else TELA_X * esc
        x["y"] = (h - TELA_Y * esc - ch) if ancora == "baixo" else TELA_Y * esc
        trabalhos.append((x["arquivo"], props))
    _render_fila(trabalhos)
    return ctas


def renderizar_short(ep: Path, tipo: str, w: int, fps: int, total: float) -> dict | None:
    """CTA compacto do Short (9:16): aparece nos últimos ~3,4 s e some antes dos últimos 0,6 s (loop).
    Centrado na zona segura, acima da legenda pop. Devolve {arquivo, x, y, t, tempos, tipo} ou None."""
    import remotion
    if tipo not in TIPOS_SHORT or total < 10.0 or not remotion.disponivel():
        return None
    import shorts as sh
    esc = w / 1080 * SHORT_ESCALA
    tp = tempos(tipo, compacto=True, dur=SHORT_DUR)
    x = {"tipo": tipo, "tempos": tp, "cena": "short", "texto": ""}
    props = _props(x, esc, fps, "centro", "baixo", compacto=True)
    hs = hashlib.sha1(json.dumps([VERSAO, props, _versao_codigo()], sort_keys=True).encode()).hexdigest()[:14]
    pasta = ep / "build" / "cta"
    pasta.mkdir(parents=True, exist_ok=True)
    arq = pasta / f"short_{tipo}_{hs}.mov"
    _render_fila([(arq, props)])
    cx = (sh.SEG_ESQ + 20 + sh.W - sh.SEG_DIR - 20) / 2 * (w / 1080)
    return {"tipo": tipo, "arquivo": arq, "tempos": tp, "t": round(total - SHORT_FOLGA_FIM - SHORT_DUR, 3),
            "x": round(cx - props["largura"] / 2), "y": round(SHORT_BASE_Y * (w / 1080) - props["altura"])}


def tipo_do_short(sb: dict, pedido, padrao) -> str | None:
    """shorts[].cta (false | true | "combo" | "inscrever") > config shorts.edicao.cta ("auto" | tipo | false).
    'auto' = combo quando o episódio pediu CTA (meta.cta / cena.cta) e meta.cta.shorts não é false."""
    if not cfg().get("ativo", True):
        return None
    if pedido is False:
        return None
    if pedido is True:
        return "combo"
    if pedido in TIPOS_SHORT:
        return pedido
    if padrao in (None, False):
        return None
    m = meta_cta(sb) or {}
    if padrao == "auto":
        return "combo" if tem_cta(sb) and m.get("shorts", True) is not False else None
    return padrao if padrao in TIPOS_SHORT else None


# ---------------------------------------------------------------- composição (FFmpeg)
def no_intervalo(ctas: list[dict], a: float, b: float, renderizados: bool = True) -> list[dict]:
    """CTAs que aparecem em [a, b) (relógio do vídeo inteiro); `renderizados` = só os que já têm arquivo."""
    return [x for x in ctas if (x.get("arquivo") or not renderizados) and x["t"] < b and x["t"] + x["dur"] > a]


def assinatura(ctas: list[dict], a: float, b: float) -> list:
    return [(x["hash"], round(x["t"] - a, 3), round(x["x"]), round(x["y"])) for x in no_intervalo(ctas, a, b)]


def overlay(ctas: list[dict], a: float, b: float, entradas: list, filtros: list, ultimo: str, fps: int,
            sufixo: str = "") -> str:
    """Sobrepõe os CTAs que caem em [a, b) a partir de `ultimo` (relógio do filtro começa em a)."""
    for k, x in enumerate(no_intervalo(ctas, a, b)):
        idx = len([e for e in entradas if e == "-i"])
        entradas += ["-i", str(x["arquivo"])]
        off = x["t"] - a
        nome = f"cta{sufixo}_{k}"
        tempo = f"setpts=PTS-STARTPTS+{off:.4f}/TB" if off >= 0 else f"trim=start={-off:.4f},setpts=PTS-STARTPTS"
        filtros.append(f"[{idx}:v]fps={fps},format=rgba,{tempo}[{nome}]")
        filtros.append(f"{ultimo}[{nome}]overlay=x={round(x['x'])}:y={round(x['y'])}:eof_action=pass:format=auto[{nome}o]")
        ultimo = f"[{nome}o]"
    return ultimo


# ---------------------------------------------------------------- som
def eventos_sfx(ctas: list[dict], t_origem: float, total: float) -> list[dict]:
    """Eventos no formato do som.planejar (t relativo ao início do vídeo renderizado)."""
    import som
    c_cfg = cfg()
    if not c_cfg.get("sfx", True):
        return []
    out = []
    for x in ctas:
        if not x.get("arquivo"):
            continue
        ref = {"id": f"cta-{x.get('cena', '')}-{x['tipo']}", "narracao": x.get("texto", "")}
        for k, (dt, cat, ganho) in enumerate(sfx_relativos(x["tipo"], x["tempos"])):
            t = x["t"] + dt - t_origem
            if not 0 <= t <= total:
                continue
            arq, taxa = som.escolher(cat, ref, f"{k}")
            out.append({"t": round(t, 3), "arquivo": str(arq), "ganho_db": som.GANHO.get(cat, -26) + ganho
                        + float(c_cfg.get("sfx_db", 0.0)), "taxa": round(taxa if cat != "cta_sino" else 1.0, 3),
                        "categoria": cat, "cena": x.get("cena", "")})
    return out


def mixar_sfx(audio: Path, eventos: list[dict], destino: Path) -> Path:
    """Soma eventos (t em s do áudio) a um áudio já pronto (Shorts)."""
    from common import rodar
    if not eventos:
        return audio
    ent, fc = ["-i", str(audio)], []
    for i, e in enumerate(eventos):
        ms = int(max(0.0, e["t"]) * 1000)
        ent += ["-i", e["arquivo"]]
        fc.append(f"[{i + 1}:a]aformat=sample_rates=48000:channel_layouts=stereo,asetrate={int(48000 * e['taxa'])},"
                  f"aresample=48000,volume={e['ganho_db']:.1f}dB,adelay={ms}|{ms}[s{i}]")
    fc.append("[0:a]" + "".join(f"[s{i}]" for i in range(len(eventos))) +
              f"amix=inputs={len(eventos) + 1}:duration=first:normalize=0[a]")
    rodar(["ffmpeg", "-y", "-v", "error", *ent, "-filter_complex", ";".join(fc), "-map", "[a]", "-ar", "48000",
           "-ac", "2", str(destino)])
    return destino


def resumo(ctas: list[dict], t_origem: float = 0.0) -> list[dict]:
    return [{"tipo": x["tipo"], "t": round(x["t"] - t_origem, 2), "dur": round(x["dur"], 2), "posicao": x.get("posicao"),
             "cena": x.get("cena"), "origem": x.get("origem"), **({"texto": x["texto"]} if x.get("texto") else {}),
             **({"renderizado": False} if not x.get("arquivo") else {})} for x in ctas]
