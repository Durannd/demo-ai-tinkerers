"""Ponte Python → Remotion: cenas animadas (número, capítulo, citação, mapa, linha do tempo, documento...).

Cada cena vira um JSON de props (contrato em render/src/tipos.ts) e um MP4 mezanino em build/cenas/.
Um único processo Node empacota o projeto uma vez e renderiza a fila inteira. Cache por hash.

Uso direto (depuração — o montar.py chama sozinho):
  python pipeline/remotion.py <slug> --still c02 --quadro 60   # PNG de um quadro em build/stills/
  python pipeline/remotion.py --instalar                      # npm install em render/
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

from common import RAIZ, canal_ativo, config, idioma, log, tokens

RENDER = RAIZ / "render"
PUBLICO = RENDER / "public"
TIPOS = {"numero", "capitulo", "citacao", "mapa", "linha_do_tempo", "documento", "comparacao", "parallax", "domino", "colagem", "icones"}
VERSAO = "1"


def node() -> str | None:
    return shutil.which("node")


def disponivel() -> bool:
    if config().get("render", {}).get("remotion") is False:
        return False
    return bool(node()) and (RENDER / "node_modules" / "remotion").exists()


def instalar() -> None:
    npm = shutil.which("npm")
    if not npm:
        sys.exit("[erro] Node.js/npm não encontrado. Instale o Node 18+ (https://nodejs.org).")
    subprocess.run([npm, "install", "--no-audit", "--no-fund"], cwd=RENDER, check=True)


def preparar_publico() -> None:
    destino = PUBLICO / "fontes"
    destino.mkdir(parents=True, exist_ok=True)
    for f in (RAIZ / "assets" / "fontes").glob("*.ttf"):
        alvo = destino / f.name
        if not alvo.exists() or alvo.stat().st_size != f.stat().st_size:
            shutil.copy2(f, alvo)


def preparar_mapas() -> None:
    origem = RENDER / "node_modules" / "world-atlas"
    destino = PUBLICO / "mapas"
    destino.mkdir(parents=True, exist_ok=True)
    for f in origem.glob("*.json"):
        if f.name != "package.json" and not (destino / f.name).exists():
            shutil.copy2(f, destino / f.name)


def publicar(arquivo: Path | None) -> str | None:
    """Copia um arquivo para render/public/cache/ (nome = hash) e devolve o caminho para staticFile()."""
    if not arquivo or not Path(arquivo).exists():
        return None
    arquivo = Path(arquivo)
    h = hashlib.sha1(f"{arquivo.resolve()}|{arquivo.stat().st_mtime}|{arquivo.stat().st_size}".encode()).hexdigest()[:16]
    nome = f"cache/{h}{arquivo.suffix.lower()}"
    alvo = PUBLICO / nome
    if not alvo.exists():
        alvo.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(arquivo, alvo)
    return nome


def _aspecto(img: Path) -> float:
    from PIL import Image
    try:
        with Image.open(img) as im:
            return round(im.width / im.height, 4)
    except OSError:  # vídeo (colagem/janela): o aspecto real vai em dados.aspecto
        return round(16 / 9, 4)


def seed(cena: dict) -> int:
    return int(hashlib.sha1(f"{cena['id']}|{cena.get('narracao', '')}".encode()).hexdigest()[:8], 16)


# ---------------------------------------------------------------- dominó (tempos compartilhados com som.py)
# Espelho da geometria de render/src/cenas/Domino.tsx (TH, GAP): o som do contato cai no quadro do contato.
DOMINO_TH, DOMINO_GAP = 620, 170
DOMINO_DQ = 0.42   # s da queda livre até encostar na peça seguinte


def _norm(x: str) -> str:
    import unicodedata
    x = unicodedata.normalize("NFD", str(x).lower())
    return "".join(ch for ch in x if ch.isalnum() or ch == "%")


def achar_na_fala(palavras: list[dict], expr: str | None, depois: float = -1e9) -> float | None:
    """Mesmo critério do acharNaFala (render/src/comp/Base.tsx): a frase inteira em sequência (a última
    palavra pode ser prefixo), senão só a 1ª palavra. Segundos relativos ao corpo da cena, ou None."""
    import re
    if not expr:
        return None
    alvo = [_norm(x) for x in re.split(r"[\s\-–—/]+", str(expr)) if _norm(x)]
    nar = [_norm(p["texto"]) for p in palavras]
    for n in (len(alvo), 1):
        for i in range(0, len(nar) - n + 1):
            if palavras[i]["ini"] < depois:
                continue
            if all(nar[i + k] == alvo[k] or (k == n - 1 and len(alvo[k]) >= 3 and nar[i + k].startswith(alvo[k]))
                   for k in range(n)):
                return float(palavras[i]["ini"])
    return None


def tempos_domino(dados: dict, palavras: list[dict], corpo: float) -> list[float]:
    """Início da queda de cada peça (s, relativo ao corpo). peca: 1 tempo (a peça atual); recapitulacao: um por
    peça, na âncora de cada uma (ou espalhados), nunca antes de a anterior encostar nela."""
    dq = DOMINO_DQ
    if dados.get("modo") == "recapitulacao":
        pecas = dados.get("pecas") or []
        n = max(2, len(pecas))
        fim = max(1.4, corpo - 1.6 - dq * 2.5)
        ts: list[float | None] = []
        ultimo = -1e9
        for i in range(n):
            t = achar_na_fala(palavras, (pecas[i] if i < len(pecas) else {}).get("ancora"), ultimo)
            ts.append(t)
            if t is not None:
                ultimo = t
        # sem âncora: espalha entre as vizinhas que têm (ou entre 0,5 s e o fim)
        for i in range(n):
            if ts[i] is None:
                a = next(((j, ts[j]) for j in range(i - 1, -1, -1) if ts[j] is not None), (-1, 1.0 - (fim - 1.0) / max(1, n - 1)))
                b = next(((j, ts[j]) for j in range(i + 1, n) if ts[j] is not None), (n, fim + (fim - 1.0) / max(1, n - 1)))
                ts[i] = a[1] + (b[1] - a[1]) * (i - a[0]) / (b[0] - a[0])
        out, minimo = [], 0.3
        for t in ts:
            t = max(float(t), minimo)
            out.append(round(t, 3))
            minimo = t + dq
        return out
    t = achar_na_fala(palavras, dados.get("ancora"))
    if t is None:
        t = max(1.8, corpo * 0.6)
    t = min(t, corpo - dq - 0.35)
    return [round(max(0.5, t), 3)]


def contatos_domino(dados: dict, quedas: list[float]) -> list[tuple[float, str]]:
    """(tempo, tipo) dos sons: 'peca' quando uma peça encosta na seguinte; 'chao' quando a última deita."""
    import math
    dq = DOMINO_DQ
    out = [(t + dq, "peca") for t in quedas]
    if dados.get("modo") == "recapitulacao" and quedas:
        out[-1] = (quedas[-1] + dq * math.sqrt((math.pi / 2) / math.asin(DOMINO_GAP / DOMINO_TH)), "chao")
    return out


def montar_props(c, w: int, h: int, fps: int, fundo: Path | None, imagens: list[Path]) -> dict:
    """c = montar.Cena. Os dados específicos do tipo vêm do sub-objeto visual.<tipo> (schema v2)."""
    v = c.dado["visual"]
    tipo = v["tipo"]
    dados = dict(v.get(tipo) or {})
    for k in ("titulo", "texto", "autor", "contexto", "ancora"):
        if k in v and k not in dados:
            dados[k] = v[k]
    meta = c.extras.get("meta") or {}
    if tipo in ("linha_do_tempo", "documento") and dados.get("base", "auto") == "auto":
        dados["base"] = "antiga" if c.extras.get("era_contexto") == "historico" else "escura"
    if tipo == "mapa":
        import geo
        dados["lugares"], avisos = geo.resolver_lugares(dados.get("lugares", []))
        for av in avisos:
            log(f"    mapa {c.id}: {av}")
        if dados.get("base", "auto") == "auto":
            dados["base"] = "antiga" if c.extras.get("era_contexto") == "historico" else "escura"
    if tipo == "domino":
        dados["quedas"] = tempos_domino(dados, meta.get("palavras") or [], c.frames / fps)
        dados["dq"] = DOMINO_DQ
    return {
        "cena_id": c.id, "tipo": tipo, "largura": w, "altura": h, "fps": fps,
        "frames": c.total, "alca_antes": c.alca_antes, "corpo": c.frames, "seed": seed(c.dado),
        "narracao": c.dado.get("narracao", ""), "palavras": meta.get("palavras") or [],
        "fundo": publicar(fundo), "imagens": [x for x in (publicar(i) for i in imagens) if x],
        "aspectos": [_aspecto(i) for i in imagens if i and Path(i).exists()],
        "dados": dados,
        # identidade e idioma do CANAL do episódio (render/src/comp/tokens.ts e i18n.ts aplicam no início da cena)
        "canal": canal_ativo(), "idioma": idioma(), "tokens": tokens(),
    }


def rodar_fila(trabalhos: list[dict]) -> None:
    preparar_publico()
    preparar_mapas()
    cfg = config().get("render", {})
    fila = {"concorrencia": cfg.get("concorrencia_remotion"), "gl": cfg.get("gl_remotion"), "trabalhos": trabalhos}
    arq = RENDER / ".fila.json"
    arq.write_text(json.dumps(fila, ensure_ascii=False), encoding="utf-8")
    proc = subprocess.Popen([node(), str(RENDER / "renderizar.mjs"), str(arq)], cwd=RENDER,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                            errors="replace")
    saida = []
    for linha in proc.stdout:
        saida.append(linha)
        if linha.startswith(("ok ", "bundle ")):
            log(f"    remotion: {linha.strip()}")
    if proc.wait() != 0:
        sys.stderr.write("".join(saida[-60:]))
        raise RuntimeError("render Remotion falhou (veja acima). Depure com: python pipeline/remotion.py <slug> --still <id>")


def renderizar(ep: Path, cenas: list, todas: list, w: int, h: int, fps: int, rascunho: bool, vizinha_fn) -> None:
    """Renderiza (ou reaproveita do cache) as cenas Remotion e preenche c.arquivo/c.hash."""
    pasta = ep / "build" / "cenas"
    pasta.mkdir(parents=True, exist_ok=True)
    pendentes = []
    for c in cenas:
        fundo, imagens = vizinha_fn(c)
        props = montar_props(c, w, h, fps, fundo, imagens)
        c.hash = hashlib.sha1(json.dumps([VERSAO, props, rascunho, _versao_codigo()], sort_keys=True).encode()).hexdigest()
        c.arquivo = pasta / f"{c.id}.mp4"
        marca = pasta / f"{c.id}.hash"
        (pasta / f"{c.id}.props.json").write_text(json.dumps(props, ensure_ascii=False, indent=1), encoding="utf-8")
        if c.arquivo.exists() and marca.exists() and marca.read_text() == c.hash:
            continue
        pendentes.append((c, {"props": props, "saida": str(c.arquivo)}))
    if not pendentes:
        return
    log(f"  Remotion: {len(pendentes)} cena(s) para renderizar")
    rodar_fila([t for _, t in pendentes])
    for c, _ in pendentes:
        (pasta / f"{c.id}.hash").write_text(c.hash)


def _versao_codigo() -> str:
    """Hash do código-fonte das cenas: mudar um componente invalida o cache das cenas daquele projeto."""
    h = hashlib.sha1()
    for f in sorted((RENDER / "src").rglob("*.ts*")):
        h.update(f.read_bytes())
    h.update((RAIZ / "assets" / "marca" / "tokens.json").read_bytes())
    return h.hexdigest()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("slug", nargs="?")
    ap.add_argument("--still")
    ap.add_argument("--quadro", type=int, default=45)
    ap.add_argument("--instalar", action="store_true")
    a = ap.parse_args()
    if a.instalar:
        instalar()
        return
    if not (a.slug and a.still):
        ap.error("use <slug> --still <id> [--quadro N] ou --instalar")
    from common import pasta_episodio
    ep = pasta_episodio(a.slug)
    props_p = ep / "build" / "cenas" / f"{a.still}.props.json"
    if not props_p.exists():
        sys.exit(f"[erro] {props_p} não existe — rode o montar.py (rascunho) antes")
    props = json.loads(props_p.read_text(encoding="utf-8"))
    destino = ep / "build" / "stills" / f"{a.still}_q{a.quadro}.png"
    destino.parent.mkdir(parents=True, exist_ok=True)
    rodar_fila([{"props": props, "saida": str(destino), "still": a.quadro}])
    print(destino)


if __name__ == "__main__":
    main()
