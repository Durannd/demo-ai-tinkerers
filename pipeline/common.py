"""Utilidades compartilhadas do pipeline: caminhos, .env, config, ffmpeg, downloads."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import re
import sys
import time
from functools import lru_cache
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
EPISODIOS = RAIZ / "episodios"
# A Wikimedia exige User-Agent com contato real (URL ou e-mail), senão responde 403/429.
# Defina CONTATO_UA no .env, ex.: CONTATO_UA=https://youtube.com/@seucanal ou seu e-mail.
USER_AGENT = "canal-harness/1.0 (pipeline de documentario; {contato}) python-requests"


def carregar_env() -> None:
    """Lê RAIZ/.env sem dependências externas. Variáveis já definidas no sistema têm prioridade."""
    env = RAIZ / ".env"
    if not env.exists():
        return
    for linha in env.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        chave, valor = linha.split("=", 1)
        os.environ.setdefault(chave.strip(), valor.strip().strip('"').strip("'"))


def chave(nome: str, obrigatoria: bool = True) -> str | None:
    carregar_env()
    valor = os.environ.get(nome)
    if obrigatoria and not valor:
        sys.exit(f"[erro] Variável {nome} não definida. Coloque no arquivo .env (veja .env.example).")
    return valor


def user_agent() -> str:
    carregar_env()
    return USER_AGENT.format(contato=os.environ.get("CONTATO_UA") or "https://github.com/canal-harness")


# ---------------------------------------------------------------- canais
# Um harness, vários canais. O canal do episódio vem de storyboard.meta.canal (padrão: demo).
# config/tokens do canal = config.json / assets/marca/tokens.json da raiz + override PROFUNDO de
# canais/<id>/canal.json e canais/<id>/tokens.json. O canal "ativo" do processo é definido por
# pasta_episodio() (todo script de episódio passa por ela); config() e tokens() devolvem o do canal ativo.
CANAIS = RAIZ / "canais"
CANAL_PADRAO = "demo"
_ativo = {"canal": CANAL_PADRAO, "idioma": None}


def mesclar(base, extra):
    """Override profundo: dicts são mesclados chave a chave; qualquer outro valor (lista, número) substitui."""
    if isinstance(base, dict) and isinstance(extra, dict):
        out = dict(base)
        for k, v in extra.items():
            out[k] = mesclar(base.get(k), v) if k in base else v
        return out
    return extra


def canais_disponiveis() -> list[str]:
    return sorted(p.parent.name for p in CANAIS.glob("*/canal.json"))


def canal_do_storyboard(sb: dict | None) -> str:
    return ((sb or {}).get("meta") or {}).get("canal") or CANAL_PADRAO


def canal_da_pasta(ep: Path) -> str:
    try:
        return canal_do_storyboard(json.loads((ep / "storyboard.json").read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return CANAL_PADRAO


@lru_cache(maxsize=8)
def _config_canal(canal: str) -> str:
    base = json.loads((RAIZ / "config.json").read_text(encoding="utf-8"))
    arq = CANAIS / canal / "canal.json"
    if canal != CANAL_PADRAO and not arq.exists():
        sys.exit(f"[erro] Canal '{canal}' não existe (falta {arq}). Canais: {', '.join(canais_disponiveis())}")
    cfg = mesclar(base, json.loads(arq.read_text(encoding="utf-8"))) if arq.exists() else base
    cfg.setdefault("canal", {})["id"] = canal
    return json.dumps(cfg)


@lru_cache(maxsize=8)
def _tokens_canal(canal: str) -> str:
    base = json.loads((RAIZ / "assets" / "marca" / "tokens.json").read_text(encoding="utf-8"))
    arq = CANAIS / canal / "tokens.json"
    return json.dumps(mesclar(base, json.loads(arq.read_text(encoding="utf-8"))) if arq.exists() else base)


def ativar_canal(canal: str | None, idioma: str | None = None) -> None:
    """Define o canal (e o idioma do storyboard) do processo. Chamado por pasta_episodio()."""
    _ativo["canal"] = canal or CANAL_PADRAO
    _ativo["idioma"] = idioma
    _config_canal(_ativo["canal"])  # falha cedo se o canal não existe


def canal_ativo() -> str:
    return _ativo["canal"]


def config(canal: str | None = None) -> dict:
    """config.json mesclado com o canal (o ativo, se não informado). Cópia nova a cada chamada."""
    return json.loads(_config_canal(canal or _ativo["canal"]))


def tokens(canal: str | None = None) -> dict:
    """Identidade visual (tokens) do canal (o ativo, se não informado)."""
    return json.loads(_tokens_canal(canal or _ativo["canal"]))


def idioma(canal: str | None = None) -> str:
    """Idioma do episódio: meta.idioma do storyboard ativo, senão o do canal (config canal.idioma)."""
    if _ativo["idioma"] and not canal:
        return _ativo["idioma"]
    return config(canal).get("canal", {}).get("idioma", "pt-BR")


def contexto_canal(ep_ou_sb) -> tuple[str, dict, dict]:
    """Função única de resolução: (id do canal, config mesclado, tokens mesclados) de um episódio
    (pasta ou storyboard já lido)."""
    canal = canal_da_pasta(ep_ou_sb) if isinstance(ep_ou_sb, Path) else canal_do_storyboard(ep_ou_sb)
    return canal, config(canal), tokens(canal)


PREFIXO_CANAL = {"demo": "DM"}
TESTES = EPISODIOS / "_testes"


def _sem_indice(nome: str) -> str:
    """'DM04-exemplo...' → 'como-uma-geada...' (pastas numeradas por canal)."""
    m = re.match(r"^[A-Z]{2}\d{2,}-(.+)$", nome)
    return m.group(1) if m else nome


def achar_episodio(slug: str) -> Path | None:
    """Pasta do episódio pelo slug puro, pelo nome numerado (DM04-...) ou em _testes/."""
    for p in (EPISODIOS / slug, TESTES / slug):
        if p.is_dir():
            return p
    slug = _sem_indice(slug)
    for p in EPISODIOS.iterdir() if EPISODIOS.exists() else ():
        if p.is_dir() and _sem_indice(p.name) == slug:
            return p
    return None


def nova_pasta_episodio(slug: str, canal: str | None) -> Path:
    """Próximo índice do canal: DM05-<slug>. Testes (zz-/teste-/exemplo) vão para _testes/."""
    if slug.startswith(("zz-", "teste", "exemplo")):
        return TESTES / slug
    pre = PREFIXO_CANAL.get(canal or CANAL_PADRAO, (canal or "XX")[:2].upper())
    nums = [int(m.group(1)) for p in EPISODIOS.iterdir()
            if (m := re.match(rf"^{pre}(\d+)-", p.name))] if EPISODIOS.exists() else []
    return EPISODIOS / f"{pre}{max(nums, default=0) + 1:02d}-{slug}"


def pasta_episodio(slug: str) -> Path:
    p = achar_episodio(slug)
    if p is None:
        sys.exit(f"[erro] Episódio não encontrado: {EPISODIOS / slug}")
    try:
        meta = json.loads((p / "storyboard.json").read_text(encoding="utf-8")).get("meta") or {}
    except (OSError, ValueError):
        meta = {}
    ativar_canal(meta.get("canal"), meta.get("idioma"))
    return p


def ler_storyboard(ep: Path) -> dict:
    return json.loads((ep / "storyboard.json").read_text(encoding="utf-8"))


def ler_json(caminho: Path, padrao):
    if caminho.exists():
        return json.loads(caminho.read_text(encoding="utf-8"))
    return padrao


def salvar_json(caminho: Path, dados) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(json.dumps(dados, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def checar_ffmpeg() -> None:
    for exe in ("ffmpeg", "ffprobe"):
        if not shutil.which(exe):
            sys.exit(f"[erro] {exe} não encontrado no PATH. Instale o FFmpeg (veja README).")


def rodar(args: list[str]) -> None:
    """Executa um comando sem shell (funciona igual no Windows, macOS e Linux)."""
    proc = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr[-3000:])
        raise RuntimeError(f"Comando falhou: {' '.join(args[:6])} ...")


def duracao(arquivo: Path) -> float:
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(arquivo)],
        capture_output=True, text=True,
    )
    try:
        return float(proc.stdout.strip())
    except ValueError:
        return 0.0


def baixar(url: str, destino: Path, headers: dict | None = None) -> Path:
    import requests

    destino.parent.mkdir(parents=True, exist_ok=True)
    h = {"User-Agent": user_agent()}
    h.update(headers or {})
    for tentativa in range(5):
        with requests.get(url, headers=h, stream=True, timeout=120) as r:
            if r.status_code in (429, 503) and tentativa < 4:
                espera = min(60, int(r.headers.get("Retry-After", 0) or 0) or 2 ** (tentativa + 1))
                log(f"    {r.status_code} em {url[:60]}... aguardando {espera}s")
                time.sleep(espera)
                continue
            r.raise_for_status()
            with open(destino, "wb") as f:
                for bloco in r.iter_content(1 << 16):
                    f.write(bloco)
            return destino
    return destino


def log(msg: str) -> None:
    print(msg, flush=True)
