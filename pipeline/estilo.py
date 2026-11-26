"""Identidade visual e decisões de acabamento: tokens, era da imagem, seed estável, encoder (CPU/GPU)."""
from __future__ import annotations

import hashlib
import json
import random
import subprocess
from functools import lru_cache
from pathlib import Path

from common import RAIZ, config, log
from common import tokens as _tokens_canal

TIPOS_HISTORICOS = {"arquivo_historico"}
TIPOS_IA = {"ia_imagem", "ia_video"}
TIPOS_GRAFICOS = {"cartela", "mapa", "linha_do_tempo", "documento", "numero", "comparacao", "capitulo", "citacao",
                  "domino", "icones"}


def tokens() -> dict:
    """Tokens do canal ativo (assets/marca/tokens.json + canais/<id>/tokens.json)."""
    return _tokens_canal()


def caminho_fonte(nome: str) -> str:
    return str(RAIZ / tokens()["fontes"][nome])


def era(cena: dict) -> str:
    """historico | moderno | ia | grafico — decide o tratamento de cor."""
    v = cena["visual"]
    if cena.get("era") in ("historico", "moderno"):
        return cena["era"]
    if v["tipo"] in TIPOS_GRAFICOS:
        return "grafico"
    if v["tipo"] in TIPOS_IA:
        return "ia"
    if v["tipo"] in TIPOS_HISTORICOS or v.get("fonte") == "archive":
        return "historico"
    return "moderno"


def filtro_tratamento(cena: dict) -> str:
    return tokens()["tratamento"][era(cena)]


def rng(cena: dict, sal: str = "") -> random.Random:
    """Aleatoriedade estável: mesma cena → mesma escolha; cenas diferentes → escolhas diferentes."""
    base = f"{cena['id']}|{cena.get('narracao', '')}|{sal}"
    return random.Random(int(hashlib.sha1(base.encode()).hexdigest()[:12], 16))


def ease(t: str) -> str:
    """Expressão FFmpeg de easing (smootherstep) para t em [0,1]."""
    return f"(({t})*({t})*({t})*(({t})*(({t})*6-15)+10))"


# ---------------------------------------------------------------- encoder
CANDIDATOS_GPU = {
    "nvenc": ["-c:v", "h264_nvenc", "-preset", "p6", "-rc", "vbr", "-cq", "{q}", "-b:v", "0"],
    "amf": ["-c:v", "h264_amf", "-quality", "quality", "-rc", "cqp", "-qp_i", "{q}", "-qp_p", "{q}"],
    "qsv": ["-c:v", "h264_qsv", "-global_quality", "{q}"],
}


@lru_cache(maxsize=1)
def encoder_gpu() -> str | None:
    """Testa de verdade (1 quadro) se a GPU codifica; listar o encoder no ffmpeg não basta."""
    pref = config().get("render", {}).get("gpu", "auto")
    if pref in (False, "nao", "cpu"):
        return None
    ordem = [pref] if pref in CANDIDATOS_GPU else list(CANDIDATOS_GPU)
    for nome in ordem:
        args = [a.replace("{q}", "23") for a in CANDIDATOS_GPU[nome]]
        r = subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=256x144:d=0.1",
                            "-frames:v", "2", *args, "-f", "null", "-"], capture_output=True)
        if r.returncode == 0:
            log(f"  encoder de GPU disponível: {nome}")
            return nome
    return None


def args_encoder(final: bool) -> list[str]:
    """Encoder do vídeo entregue. final=False → rascunho rápido."""
    v = config()["video"]
    gpu = encoder_gpu()
    if gpu:
        q = str(v.get("cq_gpu", 21) if final else 28)
        return [a.replace("{q}", q) for a in CANDIDATOS_GPU[gpu]] + ["-pix_fmt", "yuv420p"]
    return args_encoder_cpu(final)


def args_encoder_cpu(final: bool) -> list[str]:
    """libx264: padrão sem GPU e reserva quando o encoder de GPU trava."""
    v = config()["video"]
    if final:
        return ["-c:v", "libx264", "-preset", v["preset"], "-crf", str(v["crf"]), "-pix_fmt", "yuv420p"]
    return ["-c:v", "libx264", "-preset", "veryfast", "-crf", "26", "-pix_fmt", "yuv420p"]


def args_encoder_limpo() -> list[str]:
    """Versão sem rótulos (fonte dos Shorts, apagada no fim): mesma GPU, qualidade um pouco menor."""
    v = config()["video"]
    gpu = encoder_gpu()
    if gpu:
        q = str(int(v.get("cq_gpu", 21)) + 2)
        return [a.replace("{q}", q) for a in CANDIDATOS_GPU[gpu]] + ["-pix_fmt", "yuv420p"]
    return ["-c:v", "libx264", "-preset", "veryfast", "-crf", str(int(v["crf"]) + 1), "-pix_fmt", "yuv420p"]


# Intermediário das cenas: rápido e quase sem perda (vai ser recodificado no acabamento).
ARGS_MEZANINO = ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "12", "-pix_fmt", "yuv420p",
                 "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709"]


def tem_arquivo(p: Path | None) -> bool:
    return bool(p and p.exists())
