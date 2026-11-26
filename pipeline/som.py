"""Sound design: efeitos sincronizados com cortes, transições e animações.

Biblioteca
  assets/sfx/<categoria>/*.wav|mp3   arquivos seus (Sonniss GDC, Freesound CC0, Pixabay...) — têm prioridade.
                                     Registre a origem em assets/sfx/licencas.json.
  assets/sfx/_freesound/<categoria>/ baixados do freesound.org (só CC0 e CC BY) + manifesto.json com autor,
                                     licença e página. Precisa de FREESOUND_API_KEY; sem chave (e sem cache) = pula.
  assets/sfx/_gerados/               sintetizados pelo FFmpeg (sem licença de terceiros). Criados sob demanda.
Prioridade: seus arquivos > Freesound > sintetizados. Categorias: whoosh, impacto, riser, papel, tique, ambiente

Freesound (API v2, token simples): busca por categoria com filtro de licença CC0/CC BY (nunca BY-NC nem
Sampling+) e de duração, ordena por avaliação/downloads (CC0 leva vantagem no empate), baixa o preview HQ
(mp3), apara silêncio, normaliza loudness e guarda em cache. O cache é estável: uma vez cheio, não busca
de novo (variedade entre episódios vem da seed da cena, que depende da narração). Sons CC BY viram
crédito na descrição (montar.py) e nos eventos de build/sfx.json (creditos() serve também aos Shorts).
  python pipeline/som.py --freesound [--categorias whoosh,riser] [--atualizar]   baixa/renova o cache
  python pipeline/som.py --listar                                               mostra a biblioteca e as licenças

Regras (lições de pós-produção e do grio-video):
  - whoosh de transição sobe e TERMINA no corte; riser termina no início do capítulo;
  - impacto quando um número termina de contar / cartela entra; papel quando um documento aparece;
  - corte J: o som da cena que entra começa antes do corte (whoosh termina NO corte, impacto cai no corte);
  - SFX levemente abafados (lowpass) e bem abaixo da voz; cortes secos comuns só ganham um whoosh suave
    em ~1 de cada 3 (nunca no meio de uma frase nem colado a outro SFX) — se tudo faz barulho, nada chama atenção;
  - variante e afinação escolhidas pela seed da cena → nunca o mesmo som repetido em sequência.
"""
from __future__ import annotations

import json
import math
import re
import subprocess
from functools import lru_cache
from pathlib import Path

from common import RAIZ, baixar, chave, config, duracao, ler_json, log, rodar, salvar_json, user_agent
from estilo import rng

SFX = RAIZ / "assets" / "sfx"
GERADOS = SFX / "_gerados"
EXT = {".wav", ".mp3", ".ogg", ".flac"}

# ganho (dB) de cada categoria em relação à voz já normalizada
GANHO = {"whoosh": -23, "impacto": -18, "riser": -24, "papel": -24, "tique": -28, "ambiente": -34, "domino": -15,
         # CTAs animados (pipeline/cta.py): discretos, bem abaixo da voz
         "cta_clique": -24, "cta_pop": -24, "cta_sino": -27, "cta_brilho": -29}
# ajuste fino global em config.json → som.sfx_db (ex.: -3 = tudo 3 dB mais baixo)


def _sweep(filtro: str, f0: float, f1: float, dur: float, passos: int = 24, curva: float = 2.0) -> str:
    """asendcmd que varre a frequência de um filtro (whoosh/riser soam "passando")."""
    cmds = []
    for i in range(passos + 1):
        t = dur * i / passos
        k = (i / passos) ** curva
        cmds.append(f"{t:.3f} {filtro} f {f0 + (f1 - f0) * k:.0f}")
    return "asendcmd=c='" + ";".join(cmds) + "'"


RECEITAS = {
    # (nome, duração, gerador lavfi, cadeia de filtros)
    "whoosh": [
        (0.75, "anoisesrc=color=pink:r=48000:a=0.9", lambda d: f"{_sweep('bandpass', 250, 3200, d * 0.6)},bandpass=f=250:width_type=o:w=1.4,"
         f"afade=t=in:d={d * 0.55:.2f}:curve=exp,afade=t=out:st={d * 0.55:.2f}:d={d * 0.45:.2f}"),
        (0.55, "anoisesrc=color=white:r=48000:a=0.7", lambda d: f"{_sweep('bandpass', 800, 5200, d * 0.5)},bandpass=f=800:width_type=o:w=1.0,"
         f"lowpass=f=7000,afade=t=in:d={d * 0.45:.2f}:curve=qsin,afade=t=out:st={d * 0.45:.2f}:d={d * 0.55:.2f}"),
        (1.0, "anoisesrc=color=brown:r=48000:a=1.0", lambda d: f"{_sweep('bandpass', 120, 1400, d * 0.65, curva=1.5)},bandpass=f=120:width_type=o:w=1.6,"
         f"afade=t=in:d={d * 0.6:.2f}:curve=exp,afade=t=out:st={d * 0.6:.2f}:d={d * 0.4:.2f},volume=2.2"),
    ],
    "impacto": [
        (1.6, "aevalsrc='0.9*sin(2*PI*(58*t-14*t*t))*exp(-4.5*t)+0.35*(random(0)*2-1)*exp(-32*t)':s=48000",
         lambda d: "lowpass=f=2400,aecho=0.8:0.5:60|140:0.25|0.12"),
        (1.3, "aevalsrc='0.8*sin(2*PI*(44*t-8*t*t))*exp(-3.8*t)+0.5*(random(0)*2-1)*exp(-18*t)':s=48000",
         lambda d: "lowpass=f=1500,aecho=0.8:0.6:90|200:0.3|0.15"),
        (1.0, "aevalsrc='0.7*sin(2*PI*(80*t-30*t*t))*exp(-7*t)+0.4*(random(0)*2-1)*exp(-45*t)':s=48000",
         lambda d: "lowpass=f=3500,highpass=f=35"),
    ],
    "riser": [
        (2.6, "anoisesrc=color=pink:r=48000:a=0.8", lambda d: f"{_sweep('highpass', 150, 2600, d, curva=2.4)},highpass=f=150,"
         f"afade=t=in:d={d * 0.92:.2f}:curve=exp,afade=t=out:st={d * 0.94:.2f}:d={d * 0.06:.2f}"),
        (3.0, "aevalsrc='0.25*sin(2*PI*(110*t+40*t*t))+0.25*(random(0)*2-1)':s=48000",
         lambda d: f"{_sweep('bandpass', 200, 3000, d, curva=2.0)},bandpass=f=200:width_type=o:w=2,"
         f"afade=t=in:d={d * 0.9:.2f}:curve=exp,afade=t=out:st={d * 0.93:.2f}:d={d * 0.07:.2f}"),
    ],
    "papel": [
        (0.6, "aevalsrc='(random(0)*2-1)*pow(abs(sin(2*PI*9*t)),6)*exp(-3*t)':s=48000",
         lambda d: "highpass=f=1400,lowpass=f=9000,volume=2.5"),
        (0.8, "aevalsrc='(random(0)*2-1)*pow(abs(sin(2*PI*14*t+1)),8)*exp(-2.5*t)':s=48000",
         lambda d: "highpass=f=1800,lowpass=f=8000,volume=3"),
    ],
    "tique": [
        (0.08, "aevalsrc='sin(2*PI*2200*t)*exp(-90*t)':s=48000", lambda d: "highpass=f=800"),
    ],
    "ambiente": [
        (20.0, "anoisesrc=color=brown:r=48000:a=0.5", lambda d: "lowpass=f=600,highpass=f=40,volume=0.6"),
    ],
    # peça de dominó batendo na seguinte: estalo de resina/osso (parciais agudos curtíssimos) + "toc" grave da
    # peça + reflexão curta de mesa. Sem licença de terceiros.
    "domino": [
        (0.35, "aevalsrc='0.7*sin(2*PI*2300*t)*exp(-70*t)+0.5*sin(2*PI*3700*t)*exp(-110*t)"
               "+0.6*(random(0)*2-1)*exp(-160*t)+0.45*sin(2*PI*210*t)*exp(-35*t)':s=48000",
         lambda d: "highpass=f=90,aecho=0.6:0.3:18:0.16"),
        (0.35, "aevalsrc='0.7*sin(2*PI*1900*t)*exp(-60*t)+0.45*sin(2*PI*3100*t)*exp(-95*t)"
               "+0.6*(random(0)*2-1)*exp(-150*t)+0.5*sin(2*PI*180*t)*exp(-30*t)':s=48000",
         lambda d: "highpass=f=80,aecho=0.6:0.3:22:0.14"),
        (0.35, "aevalsrc='0.65*sin(2*PI*2650*t)*exp(-80*t)+0.5*sin(2*PI*4200*t)*exp(-120*t)"
               "+0.55*(random(0)*2-1)*exp(-170*t)+0.4*sin(2*PI*240*t)*exp(-40*t)':s=48000",
         lambda d: "highpass=f=100,aecho=0.6:0.3:16:0.15"),
    ],
}


def _parcial_sino(f: float, a: float, ofs: float) -> str:
    """Sino pequeno: fundamental + parciais inarmônicos (2,76× e 5,4×) e um 'hum' grave, com decaimentos diferentes."""
    t = f"(t-{ofs})" if ofs else "t"
    g = f"*gte(t,{ofs})" if ofs else ""
    return (f"{a}*(0.5*sin(2*PI*{f}*{t})*exp(-2.6*{t})+0.24*sin(2*PI*{f * 2.76:.1f}*{t})*exp(-5*{t})"
            f"+0.12*sin(2*PI*{f * 5.4:.1f}*{t})*exp(-9*{t})+0.18*sin(2*PI*{f * 0.5:.1f}*{t})*exp(-2*{t})){g}")


def _brilho(notas: list[float], passo: float) -> str:
    return "+".join(f"0.34*sin(2*PI*{f}*(t-{k * passo:.3f}))*exp(-16*(t-{k * passo:.3f}))*gte(t,{k * passo:.3f})"
                    for k, f in enumerate(notas))


# CTAs animados (pipeline/cta.py): clique de mouse (dois estalos: desce/sobe), "pop" de bolha, sininho (dois
# toques, balançando) e brilho (arpejo agudo curtinho). Sintetizados — sem licença de terceiros.
RECEITAS.update({
    "cta_clique": [
        (0.09, "aevalsrc='0.9*(random(0)*2-1)*exp(-1100*t)+0.6*sin(2*PI*3400*t)*exp(-260*t)"
               "+0.5*(random(0)*2-1)*exp(-1300*(t-0.04))*gte(t,0.04)+0.3*sin(2*PI*2700*t)*exp(-300*(t-0.04))*gte(t,0.04)':s=48000",
         lambda d: "highpass=f=700,lowpass=f=9000"),
        (0.09, "aevalsrc='0.9*(random(0)*2-1)*exp(-1000*t)+0.6*sin(2*PI*3000*t)*exp(-240*t)"
               "+0.45*(random(0)*2-1)*exp(-1300*(t-0.045))*gte(t,0.045)+0.3*sin(2*PI*2400*t)*exp(-300*(t-0.045))*gte(t,0.045)':s=48000",
         lambda d: "highpass=f=600,lowpass=f=8500"),
    ],
    "cta_pop": [
        (0.16, "aevalsrc='0.9*sin(2*PI*(620*t-2200*t*t))*exp(-26*t)*min(1,t*400)+0.25*(random(0)*2-1)*exp(-600*t)':s=48000",
         lambda d: "lowpass=f=5000,highpass=f=120"),
        (0.16, "aevalsrc='0.9*sin(2*PI*(760*t-2600*t*t))*exp(-28*t)*min(1,t*400)+0.25*(random(0)*2-1)*exp(-600*t)':s=48000",
         lambda d: "lowpass=f=5500,highpass=f=140"),
    ],
    "cta_sino": [
        (1.6, f"aevalsrc='{_parcial_sino(1480, 1.0, 0)}+{_parcial_sino(1480, 0.7, 0.17)}':s=48000",
         lambda d: "highpass=f=300,aecho=0.7:0.4:45:0.18"),
        (1.6, f"aevalsrc='{_parcial_sino(1318, 1.0, 0)}+{_parcial_sino(1318, 0.7, 0.18)}':s=48000",
         lambda d: "highpass=f=280,aecho=0.7:0.4:50:0.18"),
    ],
    "cta_brilho": [
        (0.7, f"aevalsrc='{_brilho([1568, 2093, 2637, 3136], 0.05)}':s=48000",
         lambda d: "highpass=f=900,aecho=0.6:0.4:70:0.3"),
        (0.7, f"aevalsrc='{_brilho([1760, 2217, 2637, 3520], 0.045)}':s=48000",
         lambda d: "highpass=f=900,aecho=0.6:0.4:65:0.3"),
    ],
})

# categorias que NÃO buscam no Freesound sozinhas (o que a busca devolve não serve sem ouvir antes):
# só arquivos seus em assets/sfx/<cat>/, um cache baixado de propósito (som.py --freesound --categorias domino)
# ou os sintetizados
SO_SINTETIZADOS = {"domino", "cta_clique", "cta_pop", "cta_sino", "cta_brilho"}


def _gerar(categoria: str, i: int) -> Path:
    destino = GERADOS / categoria / f"{categoria}_{i + 1}.wav"
    if destino.exists():
        return destino
    destino.parent.mkdir(parents=True, exist_ok=True)
    dur, src, cadeia = RECEITAS[categoria][i]
    filtro = cadeia(dur)
    rodar(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"{src}:d={dur}" if "anoisesrc" in src else src,
           "-t", f"{dur}", "-af", f"{filtro},alimiter=limit=0.9,aformat=sample_rates=48000:channel_layouts=stereo",
           str(destino)])
    _normalizar_pico(destino)
    return destino


def _normalizar_pico(arq: Path, alvo_db: float = -3.0) -> None:
    """Todas as variantes com o mesmo pico: o ganho por categoria (GANHO) passa a ser o único controle."""
    import re
    import subprocess

    r = subprocess.run(["ffmpeg", "-i", str(arq), "-af", "volumedetect", "-f", "null", "-"], capture_output=True, text=True)
    m = re.search(r"max_volume: (-?[\d.]+) dB", r.stderr)
    if not m:
        return
    ganho = alvo_db - float(m.group(1))
    tmp = arq.with_name(arq.stem + "_n.wav")
    rodar(["ffmpeg", "-y", "-v", "error", "-i", str(arq), "-af", f"volume={ganho:.2f}dB", str(tmp)])
    tmp.replace(arq)


# ---------------------------------------------------------------- Freesound
FREESOUND = SFX / "_freesound"
API_FS = "https://freesound.org/apiv2"
# consulta, duração aceita na busca (s), duração máxima depois de aparar (s) e loudness alvo (LUFS ≈ média
# dos sintetizados da mesma categoria, para o GANHO continuar valendo). config som.freesound.buscas sobrescreve.
BUSCAS_FS = {
    "whoosh":  {"busca": "whoosh", "dur": [0.3, 2.0], "max": 2.0, "lufs": -13},
    "impacto": {"busca": "cinematic impact boom", "dur": [0.6, 5.0], "max": 3.0, "lufs": -19},
    "riser":   {"busca": "riser", "dur": [1.5, 6.0], "max": 4.0, "lufs": -13},
    "papel":   {"busca": "paper rustle", "dur": [0.3, 2.5], "max": 1.5, "lufs": -13},
    "tique":   {"busca": "clock tick", "dur": [0.03, 0.8], "max": 0.3, "lufs": None},  # curto demais p/ LUFS: só pico
}
CAMPOS_FS = "id,name,username,license,duration,previews,avg_rating,num_ratings,num_downloads,url"
# só estas duas; a API devolve o nome ("Attribution") na busca ou a URL da licença nos detalhes
FILTRO_LICENCA = 'license:("Creative Commons 0" OR "Attribution")'


def _cfg_fs() -> dict:
    return config().get("som", {}).get("freesound", {}) or {}


def _spec_fs(categoria: str) -> dict:
    base = BUSCAS_FS.get(categoria, {"busca": categoria.replace("_", " "), "dur": [0.2, 6.0], "max": 4.0, "lufs": -16})
    return {**base, **(_cfg_fs().get("buscas", {}).get(categoria) or {})}


def licenca_fs(lic: str) -> tuple[str, str, bool] | None:
    """(nome, url, requer_atribuicao) para CC0 / CC BY; None para qualquer outra (BY-NC, Sampling+...)."""
    l = (lic or "").strip().lower()
    if l == "creative commons 0" or "publicdomain/zero" in l:
        return "CC0 1.0", "https://creativecommons.org/publicdomain/zero/1.0/", False
    if l == "attribution":
        return "CC BY", "https://creativecommons.org/licenses/by/4.0/", True   # versão só vem na URL
    m = re.search(r"creativecommons\.org/licenses/by/(\d\.\d)", l)   # "/by/" exato: by-nc, by-sa etc. não casam
    if m:
        return f"CC BY {m.group(1)}", f"https://creativecommons.org/licenses/by/{m.group(1)}/", True
    return None


def _manifesto(categoria: str) -> dict:
    return ler_json(FREESOUND / categoria / "manifesto.json", {})


def _nota_fs(s: dict) -> float:
    """Avaliação ponderada pelo nº de votos + popularidade; CC0 ganha 15% (menos créditos na descrição)."""
    n = (s.get("avg_rating") or 0) * math.log10(1 + (s.get("num_ratings") or 0)) + 0.6 * math.log10(1 + (s.get("num_downloads") or 0))
    lic = licenca_fs(str(s.get("license", "")))
    return n * (1.15 if lic and not lic[2] else 1.0)


def buscar_fs(categoria: str, api: str, n: int = 40) -> list[dict]:
    import requests

    sp = _spec_fs(categoria)
    a, b = sp["dur"]
    params = {"query": sp["busca"], "filter": f"{FILTRO_LICENCA} duration:[{a} TO {b}]", "sort": "rating_desc",
              "fields": CAMPOS_FS, "page_size": n}
    h = {"Authorization": f"Token {api}", "User-Agent": user_agent()}
    r = requests.get(f"{API_FS}/search/", params=params, headers=h, timeout=30)
    if r.status_code == 404:  # instâncias antigas da API: endpoint de texto
        r = requests.get(f"{API_FS}/search/text/", params=params, headers=h, timeout=30)
    if r.status_code in (401, 403):
        raise RuntimeError(f"Freesound recusou a chave ({r.status_code})")
    r.raise_for_status()
    return [s for s in r.json().get("results", []) if licenca_fs(str(s.get("license", "")))]


def _medir(arq: Path) -> tuple[float | None, float | None]:
    """(loudness integrado LUFS, pico dB) do arquivo."""
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(arq), "-af", "ebur128=peak=sample", "-f", "null", "-"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    i = re.findall(r"I:\s+(-?[\d.]+) LUFS", r.stderr)
    p = re.findall(r"Peak:\s+(-?[\d.]+|-inf) dBFS", r.stderr)
    lufs = float(i[-1]) if i else None
    pico = float(p[-1]) if p and p[-1] != "-inf" else None
    return (lufs if lufs is not None and lufs > -69 else None), pico


def preparar_fs(origem: Path, destino: Path, sp: dict) -> float:
    """mp3 do preview → wav 48 kHz estéreo: apara silêncio nas pontas, corta no máximo da categoria (com
    fade) e aplica ganho linear até o loudness alvo, sem passar de -3 dB de pico (igual aos sintetizados)."""
    tmp = destino.with_name(destino.stem + "_t.wav")
    apara = ("silenceremove=start_periods=1:start_threshold=-50dB:start_silence=0.005,areverse,"
             "silenceremove=start_periods=1:start_threshold=-55dB:start_silence=0.02,areverse")
    rodar(["ffmpeg", "-y", "-v", "error", "-i", str(origem), "-af",
           f"{apara},aformat=sample_rates=48000:channel_layouts=stereo", str(tmp)])
    d = duracao(tmp)
    cauda = ""
    if d > sp["max"]:
        fo = min(0.25, sp["max"] / 4)
        cauda = f"atrim=end={sp['max']:.3f},afade=t=out:st={sp['max'] - fo:.3f}:d={fo:.3f},"
        d = sp["max"]
    tmp2 = destino.with_name(destino.stem + "_c.wav")
    rodar(["ffmpeg", "-y", "-v", "error", "-i", str(tmp), "-af", f"{cauda}afade=t=in:d=0.004", str(tmp2)])
    lufs, pico = _medir(tmp2)
    ganho = -3.0 - pico if pico is not None else 0.0
    if sp.get("lufs") is not None and lufs is not None:
        ganho = min(sp["lufs"] - lufs, ganho)
    rodar(["ffmpeg", "-y", "-v", "error", "-i", str(tmp2), "-af", f"volume={ganho:.2f}dB", str(destino)])
    tmp.unlink(missing_ok=True)
    tmp2.unlink(missing_ok=True)
    return round(d, 3)


def baixar_fs(categoria: str, atualizar: bool = False) -> list[Path]:
    """Preenche assets/sfx/_freesound/<categoria>/ (se vazio ou --atualizar). Escolha determinística: mesma
    resposta da API → mesmos sons; autores diferentes primeiro (variedade de timbre)."""
    pasta = FREESOUND / categoria
    man = _manifesto(categoria)
    if man.get("itens") and not atualizar:
        return [pasta / it["arquivo"] for it in man["itens"] if (pasta / it["arquivo"]).exists()]
    api = chave("FREESOUND_API_KEY", obrigatoria=False)
    if not api:
        return []
    n = int(_cfg_fs().get("por_categoria", 5))
    sp = _spec_fs(categoria)
    sons = sorted(buscar_fs(categoria, api), key=lambda s: (-_nota_fs(s), s["id"]))
    escolhidos, autores = [], set()
    for rodada in (0, 1):  # 1ª passada: um som por autor; 2ª completa se faltar
        for s in sons:
            if len(escolhidos) >= n:
                break
            if s in escolhidos or (rodada == 0 and s.get("username") in autores):
                continue
            escolhidos.append(s)
            autores.add(s.get("username"))
    itens = []
    for s in escolhidos:
        nome_lic, url_lic, atrib = licenca_fs(str(s["license"]))
        prev = (s.get("previews") or {}).get("preview-hq-mp3")
        if not prev:
            continue
        arq = f"fs_{s['id']}.wav"
        try:
            mp3 = baixar(prev, pasta / "_previews" / f"{s['id']}.mp3")
            dur = preparar_fs(mp3, pasta / arq, sp)
            mp3.unlink(missing_ok=True)
        except Exception as e:  # um som ruim não derruba a categoria
            log(f"    freesound {categoria}: {s['id']} falhou ({e})")
            continue
        itens.append({"id": s["id"], "nome": s.get("name"), "autor": s.get("username"), "licenca": nome_lic,
                      "licenca_url": url_lic, "licenca_original": s.get("license"), "requer_atribuicao": atrib,
                      "url": s.get("url") or f"https://freesound.org/s/{s['id']}/", "arquivo": arq, "duracao": dur,
                      "nota": round(_nota_fs(s), 2)})
        log(f"    freesound {categoria}: {s['id']} {nome_lic:<9} {dur:5.2f}s  \"{s.get('name')}\" — {s.get('username')}")
    if itens:
        antigos = {it["arquivo"] for it in man.get("itens", [])} - {it["arquivo"] for it in itens}
        for a in antigos:
            (pasta / a).unlink(missing_ok=True)
        salvar_json(pasta / "manifesto.json", {"fonte": "freesound.org", "busca": sp["busca"], "duracao": sp["dur"],
                                               "itens": itens})
    return [pasta / it["arquivo"] for it in itens]


@lru_cache(maxsize=None)
def _freesound(categoria: str) -> tuple[Path, ...]:
    """Cache do Freesound da categoria; baixa uma vez se estiver vazio e houver chave. Qualquer falha = vazio
    (o pipeline segue com os sintetizados, como sem chave)."""
    if not _cfg_fs().get("ativo", True):
        return ()
    try:
        return tuple(baixar_fs(categoria))
    except Exception as e:
        log(f"  aviso: Freesound indisponível para '{categoria}' ({e}) — usando sintetizados")
        return ()


def credito_de(arq: Path) -> dict | None:
    """Item do manifesto (autor/licença/página) se o arquivo veio do Freesound."""
    arq = Path(arq)
    if arq.parent.parent != FREESOUND:
        return None
    return next((it for it in _manifesto(arq.parent.name).get("itens", []) if it["arquivo"] == arq.name), None)


def creditos(eventos: list[dict], ini: float | None = None, fim: float | None = None, curto: bool = False) -> list[str]:
    """Linhas de atribuição dos SFX CC BY usados (CC0 e sintetizados não precisam). ini/fim (s, na linha do
    tempo dos eventos) filtram um trecho — para os Shorts, a partir de build/sfx.json."""
    import i18n

    vistos, linhas = set(), []
    for e in sorted(eventos, key=lambda x: x.get("t", 0)):
        cr = e.get("credito")
        if not cr or not cr.get("requer_atribuicao") or cr.get("url") in vistos:
            continue
        if (ini is not None and e["t"] < ini) or (fim is not None and e["t"] > fim):
            continue
        vistos.add(cr.get("url"))
        txt = f"\"{cr.get('nome')}\" — {cr.get('autor')} ({cr.get('licenca')}): {cr.get('url')}"
        linhas.append(i18n.t("sfx_curto", x=txt) if curto else f"- {txt}")
    return linhas


def biblioteca(categoria: str) -> list[Path]:
    proprios = sorted(p for p in (SFX / categoria).glob("*") if p.suffix.lower() in EXT) if (SFX / categoria).exists() else []
    if proprios:
        return proprios
    automatico = categoria not in SO_SINTETIZADOS or (FREESOUND / categoria / "manifesto.json").exists()
    fs = list(_freesound(categoria)) if automatico else []
    if fs:
        return fs
    if categoria not in RECEITAS:  # categoria nova sem nada no Freesound: cai no impacto sintetizado
        categoria = "impacto"
    return [_gerar(categoria, i) for i in range(len(RECEITAS[categoria]))]


def escolher(categoria: str, cena: dict, sal: str = "") -> tuple[Path, float]:
    """(arquivo, fator de afinação) estáveis por cena."""
    r = rng(cena, f"sfx-{categoria}-{sal}")
    arqs = biblioteca(categoria)
    return arqs[r.randrange(len(arqs))], r.uniform(0.92, 1.08)


def duracao_contagem(valor: float) -> float:
    """Mesma fórmula do render/src/cenas/Numero.tsx (o impacto cai quando a contagem termina)."""
    return min(2.2, max(0.8, 0.6 + 0.22 * math.log10(max(10, abs(valor)))))


# planos de mídia "comuns" (cortes secos entre eles podem ganhar um whoosh suave)
TIPOS_PLANO = {"stock_video", "stock_imagem", "arquivo_historico", "ia_imagem", "ia_video", "local", "foto", "video"}
J_WHOOSH_MAX = 12      # quadros: whoosh de transição começa no máx. 12 quadros antes e TERMINA no corte
J_WHOOSH_MIN = 4
SUAVE_A_CADA = 3       # ~1 whoosh suave a cada 3 cortes secos elegíveis
SUAVE_GANHO = -6       # dB abaixo do whoosh de transição
SUAVE_ANTES = 0.12     # s antes do corte
SUAVE_GAP = 0.15       # silêncio mínimo da narração em volta do corte
SUAVE_LONGE = 2.0      # distância mínima de qualquer outro SFX


def _palavras_abs(cenas: list) -> list[tuple[float, float]]:
    """(ini, fim) absolutos de todas as palavras (sub-cortes repetem a mesma fala: dedup)."""
    vistos, out = set(), []
    for c in cenas:
        for p in (c.extras.get("meta") or {}).get("palavras") or []:
            k = (round(c.inicio + p["ini"], 3), round(c.inicio + p["fim"], 3))
            if k not in vistos:
                vistos.add(k)
                out.append(k)
    return sorted(out)


def _gap_no_corte(palavras: list[tuple[float, float]], t: float) -> float:
    """Duração do silêncio da narração que contém t (0 se t cai dentro de uma palavra)."""
    antes, depois = 0.0, float("inf")
    for a, b in palavras:
        if a <= t <= b:
            return 0.0
        if b <= t:
            antes = max(antes, b)
        elif a >= t:
            depois = min(depois, a)
    return depois - antes


def planejar(cenas: list, fps: int) -> list[dict]:
    """Eventos {t, arquivo, ganho_db, taxa[, dur, ofs]}. cenas = montar.Cena (inicio = segundos no vídeo).

    Corte J: o som da cena que entra começa ANTES do corte — whoosh de transição termina no corte,
    riser termina no corte, impacto (cartela/capítulo/flash) cai no corte."""
    ev: list[dict] = []
    t_origem = cenas[0].inicio if cenas else 0.0
    q = 1.0 / fps

    def add(t, cat, cena, sal="", ganho=0.0, dur=None, ofs=0.0):
        arq, taxa = escolher(cat, cena, sal)
        e = {"t": max(0.0, t - t_origem), "arquivo": str(arq), "ganho_db": GANHO.get(cat, -24) + ganho, "taxa": taxa,
             "categoria": cat, "cena": cena["id"]}
        cr = credito_de(arq)
        if cr:  # Freesound: autor/licença viajam com o evento (descrição e Shorts)
            e["credito"] = {k: cr.get(k) for k in ("id", "nome", "autor", "licenca", "licenca_url", "url", "requer_atribuicao")}
        if dur:
            e.update(dur=round(dur, 3), ofs=round(ofs, 3))
        ev.append(e)
        return arq, taxa

    def whoosh_j(t0, cena, sal, ganho=0.0):
        """Whoosh que começa 4–12 quadros antes e termina exatamente no corte (só a subida dele)."""
        arq, taxa = escolher("whoosh", cena, sal)
        d = min(max(duracao(arq) / taxa * 0.55, J_WHOOSH_MIN * q), J_WHOOSH_MAX * q)
        add(t0 - d, "whoosh", cena, sal, ganho, dur=d)

    for i, c in enumerate(cenas):
        d, v = c.dado, c.dado["visual"]
        tipo = v["tipo"]
        som = d.get("som") or {}
        if som.get("sfx") is False:
            continue
        t0 = c.inicio
        meta = c.extras.get("meta") or {}
        palavras = meta.get("palavras") or []
        # transições especiais
        if c.entrada in ("whip", "dissolve", "escuro", "flash", "zoom", "luz") and tipo != "capitulo":
            if c.entrada in ("whip", "escuro", "zoom"):
                whoosh_j(t0, d, c.entrada)
            elif c.entrada == "luz":
                whoosh_j(t0, d, "luz", -6)                         # film burn: sopro mais baixo
            elif c.entrada == "flash":
                add(t0 - 0.5 * q, "impacto", d, "flash", -4)        # cai no corte
        if tipo == "capitulo":
            arq, taxa = escolher("riser", d)
            add(t0 - duracao(arq) / taxa, "riser", d)             # o riser TERMINA no corte do capítulo
            add(t0, "impacto", d, "cap", -2)                      # e o impacto cai junto com a música nova
        elif tipo == "numero":
            dados = v.get("numero") or {}
            ancora = (dados.get("ancora") or "").lower()
            ta = next((p["ini"] for p in palavras if ancora and p["texto"].lower().strip(".,").startswith(ancora[:5])), 0.2)
            add(t0 + ta + duracao_contagem(float(dados.get("valor", 10))), "impacto", d, "num")
        elif tipo == "cartela":
            add(t0, "impacto", d, "cart", -5)                     # cai no corte
        elif tipo == "documento":
            add(t0 - 4 * q, "papel", d)
        elif tipo in ("mapa", "linha_do_tempo"):
            add(t0 - 6 * q, "whoosh", d, "mapa", -5)
        elif tipo == "domino":
            import remotion  # mesmos tempos do Domino.tsx (remotion.tempos_domino): o clique cai no contato
            dados = v.get("domino") or {}
            quedas = remotion.tempos_domino(dados, palavras, c.frames / fps)
            for k, (tc, tipo_c) in enumerate(remotion.contatos_domino(dados, quedas)):
                arq, taxa = add(t0 + tc - 0.5 * q, "domino", d, f"dom{k}", 2 if tipo_c == "chao" else 0)
                if tipo_c == "chao":
                    ev[-1]["taxa"] = round(taxa * 0.82, 3)          # a última deita na mesa: mais grave
        if c.entrada == "foco" and tipo != "capitulo":
            whoosh_j(t0, d, "foco", -8)                            # rack-focus: whoosh discreto
        pu = c.extras.get("punch")
        if pu and c.extras.get("enfase_pedida"):                   # ênfase do roteiro: "hit" seco no punch-in
            add(t0 + pu["tempos"][0] - c.alca_antes * q, "impacto", d, "enfase", -8)
        # sub-cortes repetem o `som` da cena original em cada parte: o evento só entra na parte em que a palavra
        # é dita (antes entrava uma vez por parte, dobrado); sem a palavra, só a 1ª parte usa o fallback antigo
        dur_c = c.frames / fps
        primeira = c.extras.get("orig", d["id"]) == d["id"]
        sil = som.get("silencio")
        if sil:  # silêncio dramático: impacto grave quando a música volta, na palavra
            alvo = (sil.get("antes_de") or "").lower()[:5]
            tp = next((p["ini"] for p in palavras if alvo and p["texto"].lower().strip(".,").startswith(alvo)), None)
            if tp is not None and -0.01 <= tp <= dur_c:
                add(t0 + tp, "impacto", d, "silencio", -3)
        for extra in som.get("eventos", []):  # storyboard pode pedir: {"em": "palavra", "sfx": "impacto"}
            alvo = extra.get("em", "").lower()[:5]
            tp = next((p["ini"] for p in palavras if p["texto"].lower().startswith(alvo)), None)
            if tp is None:
                if not primeira:
                    continue
                tp = 0                                             # palavra não achada: no início (como antes)
            elif not -0.01 <= tp <= dur_c:
                continue                                           # dita em outra parte (sub-corte)
            add(t0 + tp, extra.get("sfx", "impacto"), d, extra.get("em", ""))

    # whoosh suave em ~1/3 dos cortes secos entre planos de mídia (escolha estável pela seed)
    falas = _palavras_abs(cenas)
    ocupados = sorted(e["t"] for e in ev)
    elegiveis = 0
    passo = rng(cenas[0].dado, "whoosh-suave").randrange(SUAVE_A_CADA) if cenas else 0
    for i in range(1, len(cenas)):
        c, ant = cenas[i], cenas[i - 1]
        if c.entrada != "corte" or (c.dado.get("som") or {}).get("sfx") is False:
            continue
        if c.dado["visual"]["tipo"] not in TIPOS_PLANO or ant.dado["visual"]["tipo"] not in TIPOS_PLANO:
            continue
        tc = c.inicio - t_origem
        if _gap_no_corte(falas, c.inicio) < SUAVE_GAP:
            continue
        if any(abs(x - tc) < SUAVE_LONGE for x in ocupados):
            continue
        elegiveis += 1
        if (elegiveis + passo) % SUAVE_A_CADA:
            continue
        r = rng(c.dado, "whoosh-suave-dur")
        dur = r.uniform(0.18, 0.25)
        arq, taxa = escolher("whoosh", c.dado, "suave")
        pico = duracao(arq) / taxa * 0.5                              # janela em volta do pico do whoosh
        add(c.inicio - SUAVE_ANTES, "whoosh", c.dado, "suave", SUAVE_GANHO, dur=dur, ofs=max(0.0, pico - dur / 2))
        ev[-1]["categoria"] = "whoosh_suave"
        ocupados = sorted(ocupados + [tc])
    return sorted(ev, key=lambda e: e["t"])


def _recorte(e: dict) -> str:
    """Trecho do arquivo (eventos com 'dur'): atrim + fades curtos para não estalar."""
    if not e.get("dur"):
        return ""
    d, fi = e["dur"], 0.03 if e.get("ofs") else 0.0
    fo = min(0.06, d / 3)
    return (f"atrim=start={e.get('ofs', 0):.3f}:duration={d:.3f},asetpts=PTS-STARTPTS,"
            + (f"afade=t=in:d={fi:.3f}," if fi else "") + f"afade=t=out:st={d - fo:.3f}:d={fo:.3f},")


def trilha_sfx(eventos: list[dict], total: float, destino: Path) -> Path | None:
    """Renderiza todos os eventos numa trilha estéreo 48 kHz do tamanho do vídeo."""
    if not eventos:
        destino.with_suffix(".json").unlink(missing_ok=True)   # sem créditos velhos para os Shorts
        return None
    entradas, filtros = [], []
    for i, e in enumerate(eventos):
        entradas += ["-i", e["arquivo"]]
        ms = int(e["t"] * 1000)
        filtros.append(f"[{i}:a]aformat=sample_rates=48000:channel_layouts=stereo,"
                       f"asetrate={int(48000 * e['taxa'])},aresample=48000,{_recorte(e)}volume={e['ganho_db']}dB,"
                       f"adelay={ms}|{ms}[e{i}]")
    filtros.append("".join(f"[e{i}]" for i in range(len(eventos))) +
                   f"amix=inputs={len(eventos)}:normalize=0,lowpass=f=11000,apad=whole_dur={total:.3f}[s]")
    # muitos eventos: o FFmpeg aguenta centenas de entradas, mas em lotes fica mais leve
    rodar(["ffmpeg", "-y", "-v", "error", *entradas, "-filter_complex", ";".join(filtros), "-map", "[s]",
           "-t", f"{total:.3f}", "-ar", "48000", "-ac", "2", str(destino)])
    destino.with_suffix(".json").write_text(json.dumps(eventos, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"  sfx: {len(eventos)} evento(s)")
    return destino


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser(description="Biblioteca de SFX: cache do Freesound e inventário.")
    ap.add_argument("--freesound", action="store_true", help="baixa o que faltar do Freesound (precisa de FREESOUND_API_KEY)")
    ap.add_argument("--atualizar", action="store_true", help="refaz a busca e substitui o cache das categorias")
    ap.add_argument("--categorias", default=",".join(BUSCAS_FS), help="lista separada por vírgula")
    ap.add_argument("--listar", action="store_true", help="mostra de onde vem cada categoria e as licenças")
    a = ap.parse_args()
    cats = [c.strip() for c in a.categorias.split(",") if c.strip()]
    if a.freesound or a.atualizar:
        if not chave("FREESOUND_API_KEY", obrigatoria=False):
            raise SystemExit("[erro] FREESOUND_API_KEY não definida no .env — crie em https://freesound.org/apiv2/apply")
        for c in cats:
            log(f"freesound: {c} — \"{_spec_fs(c)['busca']}\"")
            arqs = baixar_fs(c, atualizar=a.atualizar)
            log(f"  {len(arqs)} som(ns) em {FREESOUND / c}")
    if a.listar or not (a.freesound or a.atualizar):
        for c in cats:
            arqs = biblioteca(c)
            origem = "seus arquivos" if arqs and arqs[0].parent == SFX / c else                 "freesound" if arqs and arqs[0].parent.parent == FREESOUND else "sintetizados"
            log(f"{c:<8} {len(arqs)} arquivo(s) — {origem}")
            for x in arqs:
                cr = credito_de(x)
                log(f"    {x.name:<16} {duracao(x):5.2f}s" + (f"  {cr['licenca']:<9} {cr['autor']} — {cr['url']}" if cr else ""))


if __name__ == "__main__":
    main()
