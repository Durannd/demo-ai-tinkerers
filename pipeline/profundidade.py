"""Mapa de profundidade (Depth Anything V2 Small, ONNX, CPU ou GPU) para o parallax 2.5D.

Licença do modelo: Apache 2.0 — SÓ o Small. Os modelos Base/Large são CC BY-NC (não usar no canal).
O modelo (~100 MB) é baixado na primeira vez para assets/modelos/ (fora do git).

Uso: python pipeline/profundidade.py imagem.jpg [saida.png]    # gera e mostra a "separação" da imagem
Dependências: pip install onnxruntime numpy   (NVIDIA: onnxruntime-gpu · AMD/Intel no Windows: onnxruntime-directml)
"""
from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageFilter

from common import RAIZ, baixar, log

MODELO = RAIZ / "assets" / "modelos" / "depth-anything-v2-small.onnx"
URL = "https://huggingface.co/onnx-community/depth-anything-v2-small/resolve/main/onnx/model.onnx"
LADO = 518  # múltiplo de 14 (patch do ViT)


def disponivel() -> bool:
    try:
        import numpy  # noqa: F401
        import onnxruntime  # noqa: F401
        return True
    except ImportError:
        return False


@lru_cache(maxsize=1)
def _sessao():
    import onnxruntime as ort

    if not MODELO.exists():
        log("  baixando Depth Anything V2 Small (~100 MB, Apache 2.0)...")
        MODELO.parent.mkdir(parents=True, exist_ok=True)
        baixar(URL, MODELO)
    prov = [p for p in ("CUDAExecutionProvider", "DmlExecutionProvider", "CPUExecutionProvider")
            if p in ort.get_available_providers()]
    return ort.InferenceSession(str(MODELO), providers=prov)


def profundidade(img_path: Path, destino: Path) -> tuple[Path, float]:
    """Gera PNG em tons de cinza (claro = perto), suavizado, no tamanho da imagem.
    Retorna (png, separacao) — separacao ~ quanto a cena tem planos distintos (0..1)."""
    import numpy as np

    with Image.open(img_path) as im:
        im = im.convert("RGB")
        w, h = im.size
        x = np.asarray(im.resize((LADO, LADO), Image.BICUBIC), dtype=np.float32) / 255.0
    x = (x - np.array([0.485, 0.456, 0.406], dtype=np.float32)) / np.array([0.229, 0.224, 0.225], dtype=np.float32)
    x = x.transpose(2, 0, 1)[None]
    s = _sessao()
    y = s.run(None, {s.get_inputs()[0].name: x})[0].squeeze()
    lo, hi = np.percentile(y, 2), np.percentile(y, 98)
    d = np.clip((y - lo) / max(1e-6, hi - lo), 0, 1)
    separacao = float(np.std(d)) * 2.4  # ~0.3 plano chapado (documento, parede) · ~0.8 primeiro plano forte
    mapa = Image.fromarray((d * 255).astype(np.uint8), "L").resize((w, h), Image.BICUBIC)
    # suaviza bordas: evita "rasgos" no deslocamento
    mapa = mapa.filter(ImageFilter.GaussianBlur(max(2, w // 300)))
    destino.parent.mkdir(parents=True, exist_ok=True)
    mapa.save(destino)
    return destino, min(1.0, separacao)


if __name__ == "__main__":
    src = Path(sys.argv[1])
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else src.with_name(src.stem + "_prof.png")
    p, sep = profundidade(src, out)
    print(f"{p}  separação={sep:.2f}")
