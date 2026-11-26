"""Orquestra o episódio inteiro: importar → validar → narrar → buscar mídia → (IA) → montar.

Uso:
  python pipeline/produzir.py --importar caminho/storyboard.json   # cria episodios/<slug>/ a partir do JSON do Projeto
  python pipeline/produzir.py <slug> --rascunho                    # rascunho 720p
  python pipeline/produzir.py <slug> --confirmar-ia                # final 1080p, gerando IA de verdade
  python pipeline/produzir.py <slug> --mock --rascunho             # teste sem nenhuma API
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from common import achar_episodio, canal_do_storyboard, log, nova_pasta_episodio

AQUI = Path(__file__).resolve().parent


def etapa(script: str, *args: str) -> None:
    log(f"\n=== {script} {' '.join(args)}")
    r = subprocess.run([sys.executable, str(AQUI / script), *args])
    if r.returncode != 0:
        sys.exit(f"[parou] {script} falhou.")


def importar(caminho: str) -> str:
    texto = Path(caminho).read_text(encoding="utf-8").strip()
    if texto.startswith("```"):  # aceita colar com cerca de código
        texto = texto.split("\n", 1)[1].rsplit("```", 1)[0]
    sb = json.loads(texto)
    slug = sb["meta"]["slug"]
    pasta = achar_episodio(slug) or nova_pasta_episodio(slug, canal_do_storyboard(sb))
    pasta.mkdir(parents=True, exist_ok=True)
    destino = pasta / "storyboard.json"
    if destino.exists():
        destino.replace(pasta / "storyboard.anterior.json")
    destino.write_text(json.dumps(sb, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"Importado em {destino}")
    return slug


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("slug", nargs="?")
    ap.add_argument("--importar")
    ap.add_argument("--mock", action="store_true", help="narração falsa (sem ElevenLabs)")
    ap.add_argument("--rascunho", action="store_true")
    ap.add_argument("--confirmar-ia", action="store_true")
    ap.add_argument("--pular-busca", action="store_true")
    a = ap.parse_args()

    slug = importar(a.importar) if a.importar else a.slug
    if not slug:
        sys.exit("Informe o slug ou --importar arquivo.json")
    if a.importar and not (a.rascunho or a.confirmar_ia or a.mock):
        etapa("validar.py", slug)
        return

    etapa("validar.py", slug)
    etapa("narrar.py", slug, *(["--mock"] if a.mock else []))
    if not a.pular_busca:
        etapa("buscar_midia.py", slug)
    etapa("gerar_ia.py", slug, *(["--confirmar"] if a.confirmar_ia else []))
    etapa("montar.py", slug, *(["--rascunho"] if a.rascunho else []))


if __name__ == "__main__":
    main()
