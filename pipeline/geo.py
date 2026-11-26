"""Geocodificação de lugares citados nas cenas de mapa.

Ordem: coordenada explícita no storyboard (lat/lon) > cache local > Nominatim (OpenStreetMap).
Nominatim: máx. 1 requisição/s e User-Agent com contato (política de uso) — por isso o cache.
Os dados de geocodificação são © OpenStreetMap contributors (ODbL); só usamos a coordenada, não
renderizamos tiles OSM, mas o crédito vai para a descrição por cortesia.

Uso: python pipeline/geo.py "North End, Boston"      # testa uma busca
"""
from __future__ import annotations

import json
import sys
import time

from common import RAIZ, log, user_agent

CACHE = RAIZ / "assets" / "mapas" / "geocache.json"
_ultimo = [0.0]


def _cache() -> dict:
    return json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}


def geocodificar(nome: str) -> dict | None:
    """{lat, lon, nome_completo, bbox:[s,n,o,l]} ou None."""
    chave = nome.strip().lower()
    cache = _cache()
    if chave in cache:
        return cache[chave]
    import requests

    espera = 1.1 - (time.time() - _ultimo[0])
    if espera > 0:
        time.sleep(espera)
    r = requests.get("https://nominatim.openstreetmap.org/search", timeout=30,
                     headers={"User-Agent": user_agent()},
                     params={"q": nome, "format": "jsonv2", "limit": 1, "accept-language": "pt-BR,en"})
    _ultimo[0] = time.time()
    r.raise_for_status()
    res = r.json()
    if not res:
        return None
    x = res[0]
    bb = [float(v) for v in x.get("boundingbox", [])]
    dado = {"lat": float(x["lat"]), "lon": float(x["lon"]), "nome_completo": x.get("display_name", ""), "bbox": bb}
    cache[chave] = dado
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
    return dado


def resolver_lugares(lugares: list[dict]) -> tuple[list[dict], list[str]]:
    """Completa lat/lon. Devolve (lugares, avisos) — avisos listam o que foi geocodificado para conferir."""
    out, avisos = [], []
    for l in lugares:
        l = dict(l)
        if l.get("lat") is None or l.get("lon") is None:
            try:
                g = geocodificar(l.get("busca") or l["nome"])
            except Exception as e:  # noqa: BLE001
                g = None
                avisos.append(f"geocodificação falhou para '{l['nome']}': {e}")
            if g:
                l["lat"], l["lon"] = g["lat"], g["lon"]
                avisos.append(f"'{l['nome']}' → {g['lat']:.4f}, {g['lon']:.4f} ({g['nome_completo'][:70]})")
            else:
                avisos.append(f"'{l['nome']}' não encontrado — informe lat/lon no storyboard")
                continue
        out.append(l)
    return out, avisos


if __name__ == "__main__":
    for n in sys.argv[1:]:
        log(json.dumps(geocodificar(n), ensure_ascii=False))
