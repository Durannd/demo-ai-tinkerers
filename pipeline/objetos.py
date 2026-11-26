"""Objetos da história: a coisa de que a narração fala aparece na tela, na palavra em que é dita, e se transforma.

  cena.objetos: [{ "objeto": "frasco de vidro de laboratório, vazio",   ← descrição (vira imagem recortada)
                   "em": "frasco",                                      ← palavra EXATA em que entra
                   "acoes": [{"tipo": "enche", "em": "veneno", "cor": "#3FA34D"},
                             {"tipo": "quebra", "em": "estilhaçou"}],
                   "rotulo": "1 frasco", "posicao": "dir", "tamanho": 0.42, "entrada": "cai", "sai_em": "depois" }]

Fonte do objeto (uma das três):
  objeto  descrição → imagem gerada (config ia.provedor: gemini | local), fundo branco, recortada por ISNet.
          Só COISAS (objeto, planta, bicho, máquina, alimento) — nunca pessoa real, marca ou documento.
  midia   id de uma cena (ou caminho em midia/) com foto JÁ baixada → o sujeito dela, recortado.
  icone   nome de um ícone da biblioteca (render/src/comp/Elementos.tsx).
Ações: cor, enche, esvazia, multiplica (n), quebra, cresce, encolhe, gira, treme, acende, risca, some.
Personagem (opcional): "personagem": {"descricao": "19th century chemist in a dark frock coat", "lado": "esq",
"em": "cientista"} — figura GENÉRICA recortada (nunca uma pessoa real nem com nome) que entra andando e manuseia o
objeto com as ações pega, agita, ergue, despeja, joga, olha. A mão é medida no recorte (ponto mais à frente do braço).

Uso:
  python pipeline/objetos.py <slug>              # simulação: lista os objetos, o que falta gerar e a estimativa
  python pipeline/objetos.py <slug> --confirmar  # gera/recorta os que faltam → midia/objetos/<hash>.png

O montar.py renderiza cada objeto (Remotion, render/cta/Objeto.tsx, fundo transparente; cache em build/objetos/)
e sobrepõe à cena — fora da versão limpa: os Shorts renderizam o mesmo objeto de novo, enquadrado em 9:16
(shorts.renderizar). Objeto sem imagem pronta é pulado com aviso (o vídeo sai sem ele).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

from common import RAIZ, canal_ativo, config, idioma, ler_json, ler_storyboard, log, pasta_episodio, salvar_json, tokens

VERSAO = 1
ACOES = {"cor", "enche", "esvazia", "multiplica", "quebra", "cresce", "encolhe", "gira", "treme", "acende", "risca", "some",
         "pega", "agita", "ergue", "despeja", "joga", "olha"}
AMPLAS = {"multiplica", "quebra", "despeja", "joga", "ergue", "agita"}   # ações que pedem canvas com folga
PROMPT_PERSONAGEM = ("{desc}. Full body from head to shoes, standing, strict side profile facing right, one arm "
                     "extended straight forward at chest height with an open empty hand, nothing held. A generic "
                     "anonymous figure, not a real person: face mostly turned away and in shadow, no identifiable "
                     "features. Vintage hand-tinted photograph look. Isolated on a plain pure white seamless background, "
                     "soft even light. No text, no logos, no other people, no objects.")
CHEGA_ANTES = 1.0        # o personagem entra andando ~1 s antes da palavra do objeto
ENTRADAS = ("cai", "surge", "desliza", "gira")
PROMPT = ("{desc}. A single object, centered, the entire object visible with margin around it, isolated on a plain "
          "pure white seamless background, soft even studio light, realistic product photograph, sharp focus. "
          "No text, no labels, no logos, no people, no hands.")
DUR_MIN, DUR_MAX = 1.6, 12.0
ANTECIPA = 0.12          # o objeto começa a entrar um pouco antes da palavra (pousa nela)
SFX_DB = -27.0
# centro (frações da tela) por posição — 16:9 e 9:16 (faixa útil entre o gancho e a legenda)
POS_16 = {"esq": (0.2, 0.5), "dir": (0.8, 0.5), "centro": (0.5, 0.5), "esq_cima": (0.2, 0.32), "dir_cima": (0.8, 0.32),
          "esq_baixo": (0.2, 0.66), "dir_baixo": (0.8, 0.66)}
POS_9 = {"esq": (0.32, 0.39), "dir": (0.58, 0.39), "centro": (0.45, 0.39), "esq_cima": (0.32, 0.36), "dir_cima": (0.58, 0.36),
         "esq_baixo": (0.32, 0.41), "dir_baixo": (0.58, 0.41)}


def lista(cena: dict) -> list[dict]:
    return [o for o in cena.get("objetos") or [] if isinstance(o, dict) and o.get("em")]


def _hash_fonte(o: dict) -> str:
    return hashlib.sha1(f"{VERSAO}|{o.get('objeto', '')}|{o.get('midia', '')}".encode()).hexdigest()[:12]


def arquivo(ep: Path, o: dict) -> Path | None:
    """PNG recortado do objeto (None para ícone)."""
    if o.get("icone") and not o.get("objeto") and not o.get("midia"):
        return None
    return ep / "midia" / "objetos" / f"{_hash_fonte(o)}.png"


def arquivo_personagem(ep: Path, o: dict) -> Path | None:
    per = o.get("personagem") or {}
    if not per.get("descricao"):
        return None
    hs = hashlib.sha1(f"{VERSAO}|p|{per['descricao']}".encode()).hexdigest()[:12]
    return ep / "midia" / "objetos" / f"p_{hs}.png"


def _medir_mao(png: Path) -> dict:
    """Ponto da mão = o pixel opaco mais à DIREITA entre 22% e 62% da altura (braço estendido para a frente)."""
    import numpy as np
    from PIL import Image
    with Image.open(png) as im:
        a = np.asarray(im.convert("RGBA"))[:, :, 3] > 128
    hh, ww = a.shape
    y0, y1 = int(hh * 0.22), int(hh * 0.62)
    melhor = (0.92, 0.42)
    maxx = -1
    for y in range(y0, y1):
        xs = np.where(a[y])[0]
        if len(xs) and xs[-1] > maxx:
            maxx, melhor = int(xs[-1]), (max(0.0, xs[-1] / ww - 0.03), y / hh)
    dados = {"mao": [round(melhor[0], 4), round(melhor[1], 4)], "aspecto": round(ww / hh, 4)}
    png.with_suffix(".json").write_text(json.dumps(dados), encoding="utf-8")
    return dados


def _foto_da_midia(ep: Path, ref: str) -> Path | None:
    p = ep / "midia" / ref
    if p.is_file():
        return p
    for ext in (".jpg", ".jpeg", ".png", ".webp"):
        if (ep / "midia" / f"{ref}{ext}").exists():
            return ep / "midia" / f"{ref}{ext}"
    return None


def _recortar(foto: Path, destino: Path) -> bool:
    """Sujeito da foto (ISNet) → PNG RGBA aparado na caixa do sujeito, ≤ 900 px."""
    from PIL import Image

    import colagem
    tmp = destino.with_name(destino.stem + "_recorte.png")
    info = colagem._recorte(foto, tmp)
    if not info or not info.get("bbox") or not tmp.exists():
        tmp.unlink(missing_ok=True)
        tmp.with_suffix(".json").unlink(missing_ok=True)
        return False
    with Image.open(tmp) as im:
        im = im.convert("RGBA")
        caixa = im.getchannel("A").point(lambda v: 255 if v > 24 else 0).getbbox()
        if not caixa:
            return False
        im = im.crop(caixa)
        im.thumbnail((900, 900))
        im.save(destino)
    tmp.unlink(missing_ok=True)
    tmp.with_suffix(".json").unlink(missing_ok=True)
    return True


def preparar(ep: Path, sb: dict, confirmar: bool) -> None:
    """Gera (IA) e recorta as imagens que faltam. Sem --confirmar só lista."""
    objs = [(c["id"], o) for c in sb["cenas"] for o in lista(c)]
    if not objs:
        log("Nenhuma cena com `objetos`.")
        return
    prov = (config().get("ia") or {}).get("provedor", "gemini")
    gerar, recortar, vistos = [], [], set()
    for cid, o in objs:
        arq = arquivo(ep, o)
        estado = "ícone" if arq is None else "ok" if arq.exists() else "FALTA"
        log(f"  {cid}: {(o.get('objeto') or o.get('midia') or o.get('icone'))[:60]:<60} em “{o['em']}” "
            f"[{', '.join(a['tipo'] for a in o.get('acoes') or []) or 'só aparece'}] {estado}")
        if arq is None or arq.exists() or arq in vistos:
            continue
        vistos.add(arq)
        (recortar if o.get("midia") else gerar).append((cid, o, arq))
    for cid, o in objs:
        pa = arquivo_personagem(ep, o)
        if pa is None:
            continue
        log(f"  {cid}: personagem “{o['personagem']['descricao'][:50]}” {'ok' if pa.exists() else 'FALTA'}")
        if not pa.exists() and pa not in vistos:
            vistos.add(pa)
            gerar.append((cid, {"objeto": o["personagem"]["descricao"], "_personagem": True}, pa))
    if not gerar and not recortar:
        log(f"{len(objs)} objeto(s), todos prontos.")
        return
    est = ""
    if gerar and prov == "local":
        import ia_local
        est = f" (~{ia_local.estimar_minutos(len(gerar), 0):.0f} min de GPU local, sem custo)"
    elif gerar:
        est = f" ({prov}: {len(gerar)} imagem(ns) pagas, modelo {config().get(prov, {}).get('modelo_imagem')})"
    log(f"{len(gerar)} imagem(ns) a gerar{est}; {len(recortar)} recorte(s) de foto já baixada.")
    if not confirmar:
        log("Rode de novo com --confirmar para gerar.")
        return
    pasta = ep / "midia" / "objetos"
    pasta.mkdir(parents=True, exist_ok=True)
    for cid, o, arq in recortar:
        foto = _foto_da_midia(ep, o["midia"])
        ok = bool(foto) and _recortar(foto, arq)
        log(f"  {cid}: recorte de {o['midia']} {'ok' if ok else 'FALHOU (sem sujeito recortável)'}")
    brutos = {}
    if gerar and prov == "local":
        import ia_local
        tarefas = []
        for cid, o, arq in gerar:
            brutos[arq] = arq.with_name(arq.stem + "_bruto.png")
            pp = o.get("_personagem")
            tarefas.append(ia_local.tarefa_imagem(arq.stem, (PROMPT_PERSONAGEM if pp else PROMPT).format(desc=o["objeto"]),
                                                  brutos[arq], "768x1024" if pp else "1024x1024"))
        try:
            ia_local.gerar_wangp(tarefas)
        except Exception as e:  # noqa: BLE001
            log(f"  ERRO na IA local: {e}")
    elif gerar:
        import gerar_ia
        g = config().get("gemini", {})
        for cid, o, arq in gerar:
            brutos[arq] = arq.with_name(arq.stem + "_bruto.png")
            try:
                pp = o.get("_personagem")
                gerar_ia.gemini_imagem(g.get("modelo_imagem"), (PROMPT_PERSONAGEM if pp else PROMPT).format(desc=o["objeto"]),
                                       {"aspectRatio": "3:4" if pp else "1:1", "imageSize": "1K"}, brutos[arq])
            except Exception as e:  # noqa: BLE001
                log(f"  {cid}: ERRO {e}")
    cred = ler_json(ep / "midia" / "creditos.json", {}) or {}
    for cid, o, arq in gerar:
        bruto = brutos.get(arq)
        if not bruto or not bruto.exists():
            log(f"  {cid}: sem imagem gerada — objeto ficará de fora")
            continue
        ok = _recortar(bruto, arq)
        log(f"  {cid}: {o['objeto'][:50]} → {'ok ' + arq.name if ok else 'recorte FALHOU'}")
        if ok and o.get("_personagem"):
            _medir_mao(arq)
        if ok:
            cred[f"objeto_{arq.stem}"] = {"fonte": prov, "autor": f"Gerado por IA ({prov})", "licenca": "conteúdo gerado",
                                          "pagina": None, "requer_atribuicao": False, "sintetico": True,
                                          "arquivo": f"objetos/{arq.name}"}
    salvar_json(ep / "midia" / "creditos.json", cred)


# ---------------------------------------------------------------- plano (tempos pela fala)
def _achar(palavras: list[tuple[str, float, float]], expr: str | None, depois: float) -> float | None:
    import remotion
    return remotion.achar_na_fala([{"texto": p[0], "ini": p[1]} for p in palavras], expr, depois)


def planejar_cena(cena: dict, palavras: list[tuple[str, float, float]], ini: float, fim: float) -> list[dict]:
    """Objetos de uma cena com tempos ABSOLUTOS (relógio do vídeo): {t, dur, acoes:[{tipo, t (rel), cor, n}], …}.
    `palavras` = (texto, ini_abs, fim_abs) da cena; objeto cuja palavra não é achada fica de fora."""
    out = []
    for k, o in enumerate(lista(cena)):
        te = _achar(palavras, o["em"], ini - 1)
        if te is None:
            log(f"  aviso: objeto de {cena['id']}: palavra “{o['em']}” não está na narração — pulado")
            continue
        per = o.get("personagem") or {}
        tp = None
        if per.get("descricao"):
            tp = _achar(palavras, per.get("em"), ini - 1) if per.get("em") else None
            tp = max(ini, (tp - 0.3) if tp is not None else te - CHEGA_ANTES)
        t0 = max(ini, min(te - ANTECIPA, tp if tp is not None else 1e9))
        t1 = fim
        if o.get("sai_em"):
            ts = _achar(palavras, o["sai_em"], te + 0.3)
            if ts is not None:
                t1 = min(fim, ts)
        t1 = min(t1, t0 + DUR_MAX)
        if t1 - t0 < DUR_MIN:
            t1 = min(fim, t0 + DUR_MIN)
        if t1 - t0 < 0.8:
            continue
        acoes, ult = [], te
        for a in o.get("acoes") or []:
            if a.get("tipo") not in ACOES:
                continue
            ta = _achar(palavras, a.get("em"), ult + 0.05) if a.get("em") else None
            if ta is None:
                ta = ult + 0.9      # sem palavra (ou não achada): logo depois da anterior
            if ta > t1 - 0.3:
                continue
            ult = ta
            acoes.append({"tipo": a["tipo"], "t": round(ta - t0, 3), **({"cor": a["cor"]} if a.get("cor") else {}),
                          **({"n": int(a["n"])} if a.get("n") else {})})
        seed = int(hashlib.sha1(f"{cena['id']}|{k}|{o['em']}".encode()).hexdigest()[:6], 16)
        out.append({"cena": cena["id"], "k": k, "obj": o, "t": round(t0, 3), "dur": round(t1 - t0, 3), "acoes": acoes,
                    "seed": seed, "posicao": o.get("posicao") or ("dir", "esq")[k % 2],
                    "entra": round(max(0.0, te - ANTECIPA - t0), 3),
                    "per_t": round(tp - t0, 3) if tp is not None else None,
                    "entrada": o.get("entrada") or ENTRADAS[seed % len(ENTRADAS)]})
    return out


def planejar(sb: dict, cenas: list) -> list[dict]:
    """Plano do vídeo inteiro a partir das cenas do montar (sub-cortes agrupados pela cena original)."""
    por_orig: dict[str, list] = {}
    for c in cenas:
        por_orig.setdefault(c.extras.get("orig", c.id), []).append(c)
    fps = config()["video"]["fps"]
    out = []
    for dado in sb["cenas"]:
        cs = por_orig.get(dado["id"])
        if not cs or not lista(dado):
            continue
        ini = min(c.inicio for c in cs)
        fim = max(c.inicio + c.frames / fps for c in cs)
        meta = cs[0].extras.get("meta_orig") or cs[0].extras.get("meta") or {}
        pal = [(p["texto"], ini + p["ini"], ini + p["fim"]) for p in meta.get("palavras") or []]
        out += planejar_cena(dado, pal, ini, fim)
    return out


# ---------------------------------------------------------------- render (Remotion, render/cta)
def _versao_codigo() -> str:
    h = hashlib.sha1()
    pasta = RAIZ / "render"
    for f in (pasta / "cta" / "Objeto.tsx", pasta / "src" / "comp" / "tokens.ts", pasta / "src" / "comp" / "Elementos.tsx"):
        if f.exists():
            h.update(f.read_bytes())
    return h.hexdigest()


def renderizar(ep: Path, plano: list[dict], w: int, h: int, fps: int, vertical: bool = False) -> list[dict]:
    """Preenche arquivo/x/y/hash de cada objeto (mesmas chaves dos CTAs: cta.overlay/assinatura servem).
    Devolve só os que têm arquivo. Sem Remotion: []."""
    import remotion
    if not plano:
        return []
    if not remotion.disponivel():
        log("  aviso: Remotion indisponível — vídeo sai SEM os objetos da história")
        return []
    pasta = ep / "build" / "objetos"
    pasta.mkdir(parents=True, exist_ok=True)
    ver, pend, prontos = _versao_codigo(), {}, []
    for x in plano:
        o = x["obj"]
        png = arquivo(ep, o)
        if png is not None and not png.exists():
            log(f"  aviso: objeto de {x['cena']} (“{o['em']}”) sem imagem — rode `python pipeline/objetos.py "
                f"{ep.name} --confirmar`; pulado")
            continue
        tam = float(o.get("tamanho") or 0.42)
        pa = arquivo_personagem(ep, o)
        per = None
        if pa is not None and pa.exists() and x.get("per_t") is not None:
            dm = ler_json(pa.with_suffix(".json"), None) or _medir_mao(pa)
            per = {"src": remotion.publicar(pa), "mao": dm["mao"], "aspecto": dm["aspecto"],
                   "lado": (o["personagem"].get("lado") or "esq"), "t": x["per_t"]}
        elif pa is not None:
            log(f"  aviso: personagem de {x['cena']} sem imagem — objeto entra sozinho")
        if vertical and per:
            lado = min(tam * 0.8 * w, 0.31 * w)
            px, py = POS_9["centro"]
        elif vertical:
            lado = min(tam * 1.2 * w, 0.52 * w)
            px, py = POS_9.get(x["posicao"], POS_9["centro"])
        else:
            lado = min(tam, 0.38 if per else 0.7) * h
            px, py = POS_16.get(x["posicao"], POS_16["dir"])
            if per:   # a dupla personagem + objeto ocupa um terço da tela: fica mais para o meio
                px = {"esq": 0.3, "dir": 0.7}.get(x["posicao"][:3], 0.5)
                py = 0.52
        esc_u = (w / 1080) if vertical else (h / 1080)
        folga = 2.3 if any(a["tipo"] in AMPLAS for a in x["acoes"]) else 1.8
        cw = int(round(lado * (2.75 if per else folga) / 2) * 2)
        ch = int(round((lado * (2.3 if per else folga) + (80 * esc_u if o.get("rotulo") else 0)) / 2) * 2)
        props = {"id": f"obj_{x['cena']}_{x['k']}", "largura": cw, "altura": ch, "fps": fps,
                 "frames": max(8, round(x["dur"] * fps)), "lado": round(lado, 1),
                 "escala": round((w / 1080) if vertical else (h / 1080), 5), "seed": x["seed"],
                 "src": remotion.publicar(png) if png else None, "icone": o.get("icone") if png is None else None,
                 "entrada": x["entrada"], "acoes": x["acoes"], "rotulo": o.get("rotulo") or "",
                 "personagem": per, "entra": x.get("entra", 0.0),
                 "sai": round(max(0.4, x["dur"] - 0.24), 3), "canal": canal_ativo(), "idioma": idioma(),
                 "tokens": tokens()}
        hs = hashlib.sha1(json.dumps([VERSAO, props, ver, png.stat().st_mtime if png else 0,
                                      pa.stat().st_mtime if per else 0], sort_keys=True)
                          .encode()).hexdigest()[:14]
        y = {**x, "arquivo": pasta / f"{x['cena']}_{x['k']}_{'v' if vertical else 'h'}_{hs}.mov", "hash": hs,
             "x": min(max(-cw * 0.25, px * w - cw / 2), w - cw * 0.75), "y": min(max(-ch * 0.25, py * h - ch / 2), h - ch * 0.75)}
        prontos.append(y)
        if not y["arquivo"].exists():
            pend[y["arquivo"]] = props
    if pend:
        remotion.preparar_publico()
        fila = {"concorrencia": config().get("cta", {}).get("concorrencia") or None,
                "gl": config().get("render", {}).get("gl_remotion"), "entrada": "cta/index.ts",
                "trabalhos": [{"props": p, "saida": str(s.with_suffix(".tmp.mov")), "composicao": "Objeto", "alfa": True}
                              for s, p in pend.items()]}
        arq = remotion.RENDER / f".fila_objetos_{ep.name[:8]}.json"
        arq.write_text(json.dumps(fila, ensure_ascii=False), encoding="utf-8")
        log(f"  objetos: {len(pend)} animação(ões) para renderizar (Remotion, fundo transparente)")
        proc = subprocess.run([remotion.node(), str(remotion.RENDER / "renderizar.mjs"), str(arq)], cwd=remotion.RENDER,
                              capture_output=True, text=True, encoding="utf-8", errors="replace")
        arq.unlink(missing_ok=True)
        if proc.returncode:
            sys.stderr.write(proc.stdout[-3000:] + proc.stderr[-3000:])
            raise RuntimeError("render Remotion dos objetos falhou (veja acima)")
        for s in pend:
            s.with_suffix(".tmp.mov").replace(s)
    return prontos


def eventos_sfx(objs: list[dict], t_origem: float, total: float) -> list[dict]:
    """Um 'pop' sintetizado quando o objeto pousa (formato do som.planejar / cta.mixar_sfx)."""
    import som
    out = []
    for x in objs:
        t = x["t"] + x.get("entra", 0.0) + ANTECIPA - t_origem
        if not 0 <= t <= total:
            continue
        arq, taxa = som.escolher("cta_pop", {"id": f"obj-{x['cena']}-{x['k']}", "narracao": x["obj"]["em"]}, "0")
        out.append({"t": round(t, 3), "arquivo": str(arq), "ganho_db": SFX_DB, "taxa": round(taxa, 3),
                    "categoria": "cta_pop", "cena": x["cena"]})
    return out


def resumo(objs: list[dict], t_origem: float = 0.0) -> list[dict]:
    return [{"cena": x["cena"], "em": x["obj"]["em"], "t": round(x["t"] - t_origem, 2), "dur": x["dur"],
             "acoes": [a["tipo"] for a in x["acoes"]]} for x in objs]


def main() -> None:
    ap = argparse.ArgumentParser(description="Objetos da história: gera e recorta as imagens de cena.objetos")
    ap.add_argument("slug")
    ap.add_argument("--confirmar", action="store_true", help="gera de verdade (sem isso, só lista)")
    a = ap.parse_args()
    ep = pasta_episodio(a.slug)
    preparar(ep, ler_storyboard(ep), a.confirmar)


if __name__ == "__main__":
    main()
