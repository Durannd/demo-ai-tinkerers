"""Valida o storyboard: schema + regras anti-"conteúdo inautêntico" + estimativa de duração.

Uso: python pipeline/validar.py <slug>
Sai com código 1 se houver ERROS. AVISOS não bloqueiam (mas os de variedade são problema real:
o YouTube desmonetiza canais "feitos por template, com pouca variação").
"""
from __future__ import annotations

import json
import re
import sys
import unicodedata
from collections import Counter

from common import EPISODIOS, RAIZ, canal_ativo, canal_do_storyboard, config, ler_json, ler_storyboard, log, pasta_episodio

PALAVRAS_POR_MIN = {"pt": 140, "en": 150, "es": 145}  # fallback; o ritmo vem de config canal.palavras_por_minuto
TIPOS_BANCO = ("stock_video", "stock_imagem", "arquivo_historico")
# domino conta como animado: é tela cheia gráfica (sem imagem de arquivo) e pesa no "vira apresentação"
TIPOS_ANIMADOS = ("mapa", "linha_do_tempo", "documento", "numero", "comparacao", "capitulo", "citacao", "domino",
                  "icones")
TIPOS_MIDIA = TIPOS_BANCO + ("ia_imagem", "ia_video", "local")   # aceitam `marca`
TIPOS_SO_IMAGEM = ("stock_imagem", "ia_imagem")                     # `congelar` não se aplica


def estimar_segundos(texto: str, idioma: str) -> float:
    """Duração estimada pelo ritmo do canal ativo (config canal.palavras_por_minuto) ou pelo idioma."""
    ppm = config().get("canal", {}).get("palavras_por_minuto") or PALAVRAS_POR_MIN.get(idioma[:2].lower(), 145)
    return len(texto.split()) / ppm * 60


def norm(s: str) -> str:
    s = unicodedata.normalize("NFD", s.lower())
    return "".join(ch for ch in s if ch.isalnum())


def tem_ancora(narracao: str, ancora: str | None) -> bool:
    if not ancora:
        return True
    alvo = norm(ancora.split()[0])
    return any(norm(w).startswith(alvo) for w in narracao.split())


def assinatura(c: dict) -> tuple:
    """O que o espectador percebe como 'o mesmo tipo de plano'."""
    v = c["visual"]
    t = v["tipo"]
    if t in TIPOS_ANIMADOS:
        sub = v.get(t) or {}
        detalhe = sub.get("modo") or sub.get("estilo") or ("rota" if sub.get("rota") else "")
        return (t, detalhe)
    return (t, c.get("movimento") or "auto", v.get("fonte"))


def checar_visual(cid: str, v: dict, narracao: str, erros: list, avisos: list) -> None:
    t = v["tipo"]
    if t in TIPOS_BANCO and not v.get("busca") and not v.get("arquivo"):
        erros.append(f"{cid}: tipo {t} precisa de 'busca' ou 'arquivo'")
    if t in TIPOS_BANCO and not v.get("fonte") and not v.get("arquivo"):
        erros.append(f"{cid}: tipo {t} precisa de 'fonte'")
    if t in ("ia_imagem", "ia_video") and not v.get("prompt"):
        erros.append(f"{cid}: tipo {t} precisa de 'prompt'")
    if t == "cartela" and not v.get("cartela_texto"):
        erros.append(f"{cid}: cartela sem 'cartela_texto'")
    if t == "local" and not v.get("arquivo"):
        erros.append(f"{cid}: tipo local precisa de 'arquivo'")
    d = v.get(t) or {}
    if t == "mapa":
        for l in d.get("lugares", []):
            if l.get("lat") is None:
                avisos.append(f"{cid}: '{l['nome']}' sem lat/lon — será geocodificado (OSM); confira no rascunho")
            if not tem_ancora(narracao, l.get("ancora")):
                avisos.append(f"{cid}: âncora '{l['ancora']}' não está na narração")
    if t == "documento":
        if d.get("estilo", "scan" if (v.get("busca") or v.get("arquivo")) else "ficha") == "scan" \
                and not (v.get("busca") or v.get("arquivo")):
            erros.append(f"{cid}: documento 'scan' precisa da imagem real (busca/arquivo) — ou use estilo 'ficha'")
        if len(d.get("trecho", "")) > 180:
            avisos.append(f"{cid}: trecho de documento longo ({len(d['trecho'])} caracteres) — corte para o essencial")
    if t == "linha_do_tempo":
        for e in d.get("eventos", []):
            if not re.search(r"\d{3,4}", str(e.get("data", ""))):
                erros.append(f"{cid}: evento '{e.get('rotulo')}' sem ano na data")
            if not tem_ancora(narracao, e.get("ancora")):
                avisos.append(f"{cid}: âncora '{e['ancora']}' não está na narração")
    if t == "numero" and not tem_ancora(narracao, d.get("ancora")):
        avisos.append(f"{cid}: âncora '{d['ancora']}' não está na narração")
    if t == "domino":
        if d.get("modo") == "recapitulacao":
            pecas = d.get("pecas") or []
            if len(pecas) < 2:
                erros.append(f"{cid}: domino 'recapitulacao' precisa de 'pecas' (2 a 8, em ordem)")
            for k, pc in enumerate(pecas, 1):
                if not pc.get("titulo"):
                    erros.append(f"{cid}: domino, peça {k} sem 'titulo'")
                if not tem_ancora(narracao, pc.get("ancora")):
                    erros.append(f"{cid}: domino, âncora '{pc['ancora']}' da peça {k} não está na narração")
        else:
            if not d.get("numero") or not d.get("titulo"):
                erros.append(f"{cid}: domino 'peca' precisa de 'numero' e 'titulo'")
            if len(d.get("titulo", "")) > 32:
                avisos.append(f"{cid}: título da peça longo ({len(d['titulo'])} caracteres) — 2 a 5 palavras leem melhor")
            if not tem_ancora(narracao, d.get("ancora")):
                erros.append(f"{cid}: domino, âncora '{d['ancora']}' não está na narração")
    if t == "icones":
        modo = d.get("modo")
        if modo == "fileira" and len(d.get("itens") or []) < 2:
            erros.append(f"{cid}: icones 'fileira' precisa de 2 a 6 'itens'")
        if modo == "mosaico" and not d.get("icone"):
            erros.append(f"{cid}: icones 'mosaico' precisa de 'icone'")
        if modo == "fichas" and not d.get("fichas"):
            erros.append(f"{cid}: icones 'fichas' precisa de 1 a 4 'fichas'")
        for x in (d.get("itens") or []) + (d.get("fichas") or []) + [d]:
            if x.get("em") and not tem_ancora(narracao, x["em"]):
                avisos.append(f"{cid}: âncora '{x['em']}' não está na narração")
    col = v.get("colagem")
    if col:
        if t not in TIPOS_MIDIA:
            erros.append(f"{cid}: 'colagem' só vale para cena com mídia ({', '.join(TIPOS_MIDIA)}); use 'icones' para cena só gráfica")
        if isinstance(col, dict):
            for nome, expr in (("termico", col.get("termico")), ("icone.em", (col.get("icone") or {}).get("em")),
                               ("ficha.em", (col.get("ficha") or {}).get("em"))):
                if isinstance(expr, str) and not tem_ancora(narracao, expr):
                    avisos.append(f"{cid}: colagem {nome} '{expr}' não está na narração (entra num tempo padrão)")
    if t == "comparacao":
        for lado in ("a", "b"):
            x = d.get(lado) or {}
            if d.get("modo") in ("lado_a_lado", "antes_depois") and not (x.get("busca") or x.get("arquivo")):
                erros.append(f"{cid}: comparação '{d['modo']}' precisa de imagem no lado {lado}")


def marcas_da_cena(c: dict) -> list[dict]:
    m = c.get("marca")
    return [x for x in (m if isinstance(m, list) else [m] if m else []) if isinstance(x, dict)]


def checar_edicao(c: dict, erros: list, avisos: list) -> None:
    """Campos de edição: marca, congelar, som.eventos[].efeito — âncoras têm de estar na narração."""
    cid, nar = c["id"], c["narracao"]
    tipos = {c["visual"]["tipo"], *(s["visual"]["tipo"] for s in c.get("sub") or [])}
    for m in marcas_da_cena(c):
        if not tipos & set(TIPOS_MIDIA):
            erros.append(f"{cid}: 'marca' só vale em cena de foto/vídeo (tipo {c['visual']['tipo']})")
        for campo in ("ancora", "ate"):
            if not tem_ancora(nar, m.get(campo)):
                erros.append(f"{cid}: marca com {campo} '{m[campo]}' que não está na narração")
        if m.get("texto") and len(m["texto"].split()) > 4:
            avisos.append(f"{cid}: texto da marca com mais de 4 palavras")
    cg = c.get("congelar")
    if cg:
        if not tem_ancora(nar, cg.get("em")):
            erros.append(f"{cid}: congelar em '{cg.get('em')}', que não está na narração")
        if c["visual"]["tipo"] in TIPOS_SO_IMAGEM or c["visual"]["tipo"] in TIPOS_ANIMADOS:
            avisos.append(f"{cid}: 'congelar' só faz efeito em vídeo (tipo {c['visual']['tipo']})")
    for e in (c.get("som") or {}).get("eventos") or []:
        if not tem_ancora(nar, e.get("em")):
            (erros if e.get("efeito") else avisos).append(
                f"{cid}: som.eventos em '{e.get('em')}', que não está na narração")


def checar_frequencia_edicao(cenas: list, total: float, avisos: list) -> None:
    """Efeitos de edição perdem a força se repetidos: limites por minuto de vídeo."""
    minutos = max(1.0, total / 60)
    n_marca = sum(len(marcas_da_cena(c)) for c in cenas)
    if n_marca > total / 40 + 1:
        avisos.append(f"edição: {n_marca} marcações em {mmss(total)} — use ~1 a cada 40 s")
    n_cong = sum(1 for c in cenas if c.get("congelar"))
    if n_cong > 2 + int(minutos // 8):
        avisos.append(f"edição: {n_cong} congelamentos — 1 a 2 por vídeo")
    n_ef = sum(1 for c in cenas for e in (c.get("som") or {}).get("eventos") or [] if e.get("efeito"))
    if n_ef > total / 60 + 1:
        avisos.append(f"edição: {n_ef} tremores/flashes em {mmss(total)} — ~1 por minuto, só em impacto de verdade")
    trans = Counter(c.get("transicao") for c in cenas if c.get("transicao") in ("luz", "zoom"))
    for t, q in trans.items():
        if q > 2 + int(minutos // 5):
            avisos.append(f"edição: transição '{t}' {q}× — reserve para trocas de bloco/viradas")
    pecas = [c for c in cenas if c["visual"]["tipo"] == "domino" and (c["visual"].get("domino") or {}).get("modo") != "recapitulacao"]
    nums = [(c["visual"].get("domino") or {}).get("numero") for c in pecas]
    if nums and nums != list(range(nums[0], nums[0] + len(nums))):
        avisos.append(f"domino: peças fora de ordem ({nums}) — numere 1, 2, 3… na ordem da cadeia")


def checar_cta(sb: dict, ep, cfg: dict, erros: list, avisos: list) -> None:
    """CTAs (cena.cta / meta.cta, pipeline/cta.py): âncora na narração (ERRO), pergunta do 'comentar',
    frequência (~1 a cada 2 min) e nada nos primeiros 20 s (o gancho)."""
    meta = sb["meta"].get("cta")
    pergunta = (meta.get("pergunta") or "").strip() if isinstance(meta, dict) else ""
    if isinstance(meta, dict) and meta.get("auto", True) is not False and not pergunta             and not any(c.get("cta") for c in sb["cenas"]):
        avisos.append("cta: meta.cta sem 'pergunta' — o auto não põe o 'comentar' no fim")
    if len(pergunta) > 90:
        avisos.append(f"cta: pergunta com {len(pergunta)} caracteres — até ~90 lê bem no balão")
    idioma = sb["meta"]["idioma"]
    t, tempos = 0.0, []
    for c in sb["cenas"]:
        meta_a = ler_json(ep / "audio" / f"{c['id']}.json", None) or {}
        dur = meta_a.get("duracao") or estimar_segundos(c["narracao"], idioma)
        x = c.get("cta")
        if isinstance(x, dict):
            cid = c["id"]
            if not tem_ancora(c["narracao"], x.get("em")):
                erros.append(f"{cid}: cta em '{x.get('em')}', que não está na narração")
            elif x.get("tipo") == "comentar" and not ((x.get("texto") or "").strip() or pergunta):
                erros.append(f"{cid}: cta 'comentar' sem 'texto' (e sem meta.cta.pergunta)")
            else:
                alvo = norm(str(x["em"]).split()[0])
                pal = meta_a.get("palavras") or []
                tp = next((p["ini"] for p in pal if norm(p["texto"]).startswith(alvo)), None)
                if tp is None:
                    ws = c["narracao"].split()
                    k = next((i for i, w in enumerate(ws) if norm(w).startswith(alvo)), 0)
                    tp = dur * k / max(1, len(ws))
                tempos.append((t + tp, cid, x.get("tipo")))
            if len((x.get("texto") or "")) > 90:
                avisos.append(f"{cid}: texto do cta com mais de ~90 caracteres")
            if x.get("texto") and x.get("tipo") != "comentar":
                avisos.append(f"{cid}: 'texto' só é usado no cta 'comentar'")
        t += dur + c.get("pausa_depois", cfg["pausa_padrao"])
    for tc, cid, tipo in tempos:
        if tc < 20:
            avisos.append(f"{cid}: cta '{tipo}' em {mmss(tc)} — nos primeiros 20 s ele rouba o gancho")
    if len(tempos) > t / 120 + 1:
        avisos.append(f"cta: {len(tempos)} chamadas em {mmss(t)} — ~1 a cada 2 min (mais que isso cansa)")


def mmss(s: float) -> str:
    return f"{int(s // 60)}:{int(s % 60):02d}"


def linha_do_tempo(sb: dict, ep, cfg: dict) -> tuple[list[tuple[float, float, str, str]], list[float], float]:
    """Linha do tempo estimada: (planos [(ini, fim, id, tipo)], eventos [t], total). Usa a narração real
    (audio/<id>.json, com tempos por palavra) quando já existe; senão, estima pela contagem de palavras."""
    idioma = sb["meta"]["idioma"]
    planos, eventos, t = [], [], 0.0
    for c in sb["cenas"]:
        meta = ler_json(ep / "audio" / f"{c['id']}.json", None) or {}
        palavras = meta.get("palavras") or []
        dur = meta.get("duracao") or estimar_segundos(c["narracao"], idioma)
        total_c = dur + c.get("pausa_depois", cfg["pausa_padrao"])
        ws = c["narracao"].split()

        def tempo(palavra: str | None) -> float | None:
            alvo = norm((palavra or "").split(" ")[0]) if palavra else ""
            if not alvo:
                return None
            for p in palavras:
                if norm(p["texto"]).startswith(alvo):
                    return p["ini"]
            for i, w in enumerate(ws):
                if norm(w).startswith(alvo):
                    return dur * i / max(1, len(ws))
            return None

        cortes = [(0.0, c["id"], c["visual"]["tipo"])]
        subs = c.get("sub") or []
        for k, s in enumerate(subs, 1):
            x = tempo(s.get("ancora"))
            if x is None:
                x = dur * k / (len(subs) + 1)
            cortes.append((x, f"{c['id']}_s{k}", s["visual"]["tipo"]))
        cortes.sort()
        for j, (x, cid, tipo) in enumerate(cortes):
            fim = cortes[j + 1][0] if j + 1 < len(cortes) else total_c
            planos.append((t + x, t + fim, cid, tipo))
            eventos.append(t + x)
            if tipo in TIPOS_ANIMADOS or tipo == "parallax":
                eventos += [t + y for y in _passos(x, fim, 4.0)]  # gráfico animado: tem movimento próprio
        if (c.get("rotulo") or {}).get("texto") or c.get("texto_tela"):
            eventos.append(t + 0.45)
        for m in marcas_da_cena(c):
            eventos.append(t + (tempo(m.get("ancora")) or 0.4))
        if (c.get("congelar") or {}).get("em"):
            x = tempo(c["congelar"]["em"])
            if x is not None:
                eventos.append(t + x)
        for e in (c.get("som") or {}).get("eventos", []):
            x = tempo(e.get("em"))
            if x is not None:
                eventos.append(t + x)
        t += total_c
    return planos, sorted(eventos), t


def _passos(a: float, b: float, passo: float) -> list[float]:
    out, x = [], a + passo
    while x < b:
        out.append(x)
        x += passo
    return out


def checar_ritmo(sb: dict, ep, cfg: dict, avisos: list) -> None:
    """Gancho (abertura) e silêncio visual: o espectador decide nos primeiros 30 s se fica."""
    lim = cfg["limites"]
    planos, eventos, total = linha_do_tempo(sb, ep, cfg)
    g = lim.get("gancho_segundos", 30)
    abertura = [p for p in planos if p[0] < g]
    mudancas = len([p for p in abertura if p[0] > 0])
    if mudancas < lim.get("gancho_min_mudancas", 6):
        avisos.append(f"gancho: só {mudancas} mudança(s) visual(is) nos primeiros {g}s "
                      f"(mínimo {lim.get('gancho_min_mudancas', 6)}) — use sub-cortes na abertura")
    gmax = lim.get("gancho_max_plano", 5)
    for ini, fim, cid, tipo in abertura:
        if fim - ini > gmax:
            avisos.append(f"gancho: {cid} ({tipo}) fica {fim - ini:.1f}s parado em {mmss(ini)} "
                          f"(máximo {gmax}s nos primeiros {g}s) — divida com 'sub'")
    mx = lim.get("max_sem_evento", 20)
    pts = sorted(set([0.0, *eventos, total]))
    for a, b in zip(pts, pts[1:]):
        if b - a > mx:
            dono = next((p[2] for p in planos if p[0] <= a < p[1]), "?")
            avisos.append(f"ritmo: {b - a:.0f}s sem evento visual ({mmss(a)}–{mmss(b)}, a partir de {dono}) — "
                          f"acrescente sub-corte, rótulo ou som.eventos (máximo {mx}s)")


def episodios_anteriores(slug_atual: str, canal: str | None = None) -> list[dict]:
    """Storyboards de outros episódios do MESMO canal (repetição entre canais não denuncia template)."""
    canal = canal or canal_ativo()
    out = []
    for p in sorted(EPISODIOS.glob("*/storyboard.json")):
        if p.parent.name in (slug_atual,) or p.parent.name.startswith(("zz-", "_")):
            continue
        try:
            sb = json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if sb.get("meta", {}).get("slug") != slug_atual and canal_do_storyboard(sb) == canal:
            out.append(sb)
    return out


def validar(slug: str) -> bool:
    import jsonschema

    ep = pasta_episodio(slug)
    sb = ler_storyboard(ep)
    cfg = config()
    lim = cfg["limites"]
    erros: list[str] = []
    avisos: list[str] = []

    schema = ler_json(RAIZ / "storyboard.schema.json", {})
    for e in jsonschema.Draft202012Validator(schema).iter_errors(sb):
        caminho = "/".join(str(p) for p in e.path)
        erros.append(f"schema: {caminho}: {e.message[:200]}")
    if erros:
        return relatorio(erros, avisos, sb, 0)

    v2 = sb.get("versao", 1) >= 2
    idioma_canal = cfg.get("canal", {}).get("idioma", "pt-BR")
    if sb["meta"]["idioma"][:2].lower() != idioma_canal[:2].lower():
        erros.append(f"meta.idioma '{sb['meta']['idioma']}' não bate com o canal '{canal_ativo()}' ({idioma_canal}) "
                     f"— confira meta.canal")
    cenas = sb["cenas"]
    idioma = sb["meta"]["idioma"]
    ids = [c["id"] for c in cenas]
    for dup, n in Counter(ids).items():
        if n > 1:
            erros.append(f"id repetido: {dup}")

    total = 0.0
    for c in cenas:
        v = c["visual"]
        seg = estimar_segundos(c["narracao"], idioma)
        total += seg + c.get("pausa_depois", cfg["pausa_padrao"])
        if "[VERIFICAR" in c["narracao"].upper():
            erros.append(f"{c['id']}: narração ainda tem [VERIFICAR]")
        if seg < lim["segundos_min_cena"] and v["tipo"] != "capitulo":
            avisos.append(f"{c['id']}: cena curta (~{seg:.1f}s)")
        if seg > lim["segundos_max_cena"] and not c.get("sub"):
            avisos.append(f"{c['id']}: cena longa (~{seg:.1f}s) sem sub-cortes — divida ou use 'sub'")
        checar_visual(c["id"], v, c["narracao"], erros, avisos)
        for k, s in enumerate(c.get("sub") or [], 1):
            checar_visual(f"{c['id']}_s{k}", s["visual"], c["narracao"], erros, avisos)
            if not tem_ancora(c["narracao"], s.get("ancora")):
                erros.append(f"{c['id']}: sub-corte {k} com âncora '{s.get('ancora')}' que não está na narração")
        checar_edicao(c, erros, avisos)
        txt = (c.get("rotulo") or {}).get("texto") or c.get("texto_tela")
        if txt and len(txt.split()) > 6:
            avisos.append(f"{c['id']}: rótulo com mais de 6 palavras")
        if not v2 and v["tipo"] in TIPOS_ANIMADOS:
            avisos.append(f"{c['id']}: tipo '{v['tipo']}' é da v2 — declare \"versao\": 2 no storyboard")

    # ---- variedade dentro do episódio
    tipos = Counter(c["visual"]["tipo"] for c in cenas)
    n = len(cenas)
    for t, q in tipos.items():
        if n >= 6 and q / n > lim["max_percentual_mesmo_tipo"]:
            avisos.append(f"variedade: '{t}' ocupa {q / n:.0%} das cenas (limite {lim['max_percentual_mesmo_tipo']:.0%})")
    if n >= 6 and (tipos.get("cartela", 0)) / n > lim["max_percentual_cartela"]:
        avisos.append(f"variedade: cartelas demais ({tipos['cartela'] / n:.0%})")
    if tipos.get("ia_video", 0) > lim["max_ia_video"]:
        erros.append(f"custo: {tipos['ia_video']} cenas ia_video (máximo {lim['max_ia_video']})")
    if v2 and n >= 12 and len(tipos) < lim.get("min_tipos_distintos", 4):
        avisos.append(f"variedade: só {len(tipos)} tipos de visual em {n} cenas (mínimo {lim.get('min_tipos_distintos', 4)})")
    animadas = sum(tipos.get(t, 0) for t in TIPOS_ANIMADOS)
    if v2 and n >= 12 and animadas / n > lim.get("max_percentual_animadas", 0.4):
        avisos.append(f"variedade: {animadas / n:.0%} das cenas são gráficos animados — o vídeo vira 'apresentação'")

    seguidos = 1
    for a, b in zip(cenas, cenas[1:]):
        mesma = assinatura(a) == assinatura(b)
        seguidos = seguidos + 1 if mesma else 1
        if seguidos > lim["max_iguais_seguidos"]:
            avisos.append(f"variedade: {seguidos} cenas seguidas iguais até {b['id']} ({assinatura(b)[0]})")
    janela = lim.get("janela_assinatura", 3)
    for i, c in enumerate(cenas):
        if c["visual"]["tipo"] in TIPOS_ANIMADOS:
            for j in range(max(0, i - janela), i):
                if assinatura(cenas[j]) == assinatura(c) and j != i - 1:
                    avisos.append(f"variedade: {c['id']} repete o plano de {cenas[j]['id']} logo antes ({assinatura(c)})")
                    break

    # ---- variedade ENTRE episódios (o que mais denuncia "template")
    anteriores = episodios_anteriores(sb["meta"]["slug"])
    abertura = [assinatura(c)[0] for c in cenas[:4]]
    caps = {norm((c["visual"].get("capitulo") or {}).get("titulo", "")) for c in cenas if c["visual"]["tipo"] == "capitulo"}
    for outro in anteriores:
        slug_o = outro["meta"]["slug"]
        if len(abertura) == 4 and [assinatura(c)[0] for c in outro["cenas"][:4]] == abertura:
            avisos.append(f"entre episódios: a abertura (4 primeiros planos) é igual à de '{slug_o}' — mude a ordem/tipos")
        caps_o = {norm((c["visual"].get("capitulo") or {}).get("titulo", "")) for c in outro["cenas"]
                  if c["visual"]["tipo"] == "capitulo"}
        if caps & caps_o - {""}:
            avisos.append(f"entre episódios: título de capítulo repetido de '{slug_o}'")
        mus = (sb["meta"].get("musica") or {}).get("arquivo")
        if mus and mus == (outro["meta"].get("musica") or {}).get("arquivo"):
            avisos.append(f"entre episódios: mesma trilha de '{slug_o}' ({mus})")

    checar_frequencia_edicao(cenas, total, avisos)
    checar_cta(sb, ep, cfg, erros, avisos)
    checar_ritmo(sb, ep, cfg, avisos)

    if not sb.get("fontes"):
        erros.append("sem fontes")

    return relatorio(erros, avisos, sb, total, tipos)


def relatorio(erros, avisos, sb, total, tipos=None) -> bool:
    log(f"== Validação: {sb.get('meta', {}).get('slug', '?')} (v{sb.get('versao', 1)}, canal {canal_ativo()})")
    if tipos:
        log("Cenas por tipo: " + ", ".join(f"{t}={q}" for t, q in tipos.most_common()))
        log(f"Duração estimada: {int(total // 60)}min{int(total % 60):02d}s ({len(sb['cenas'])} cenas)")
    for a in avisos:
        log(f"  AVISO  {a}")
    for e in erros:
        log(f"  ERRO   {e}")
    log("OK" if not erros else f"{len(erros)} erro(s). Corrija antes de renderizar.")
    return not erros


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("uso: python pipeline/validar.py <slug>")
    sys.exit(0 if validar(sys.argv[1]) else 1)
