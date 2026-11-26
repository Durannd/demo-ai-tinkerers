"""Alinha palavras transcritas (com tempo) ao TEXTO DO ROTEIRO, para a legenda usar a grafia do roteiro.

Entrada:  texto do roteiro + lista [{texto, ini, fim}] vinda do Scribe (ou de um alinhador local)
Saída:    lista [{texto, ini, fim}] com as palavras DO ROTEIRO, uma a uma, e a taxa de casamento.

Como: normaliza as duas sequências (minúsculas, sem acento/pontuação, números → extenso) e casa com
difflib.SequenceMatcher. Palavra do roteiro casada herda o tempo; não casada é interpolada entre vizinhas.
Uma palavra do roteiro como "1919" pode virar várias na fala ("mil novecentos e dezenove"): por isso a
normalização expande números ANTES de casar e depois agrupa de volta.
"""
from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

UNIDADES = ["zero", "um", "dois", "tres", "quatro", "cinco", "seis", "sete", "oito", "nove", "dez", "onze", "doze",
            "treze", "quatorze", "quinze", "dezesseis", "dezessete", "dezoito", "dezenove"]
DEZENAS = ["", "", "vinte", "trinta", "quarenta", "cinquenta", "sessenta", "setenta", "oitenta", "noventa"]
CENTENAS = ["", "cento", "duzentos", "trezentos", "quatrocentos", "quinhentos", "seiscentos", "setecentos",
            "oitocentos", "novecentos"]


def extenso(n: int) -> list[str]:
    """Número inteiro → palavras em pt-BR (até bilhões). Suficiente para casar com a fala."""
    if n < 20:
        return [UNIDADES[n]]
    if n < 100:
        d, u = divmod(n, 10)
        return [DEZENAS[d]] + (["e", UNIDADES[u]] if u else [])
    if n < 1000:
        if n == 100:
            return ["cem"]
        c, r = divmod(n, 100)
        return [CENTENAS[c]] + (["e"] + extenso(r) if r else [])
    for valor, sing, plur in ((10 ** 9, "bilhao", "bilhoes"), (10 ** 6, "milhao", "milhoes"), (1000, "mil", "mil")):
        if n >= valor:
            q, r = divmod(n, valor)
            cab = ([] if (valor == 1000 and q == 1) else extenso(q)) + [sing if q == 1 else plur]
            if not r:
                return cab
            return cab + (["e"] if r < 100 or r % 100 == 0 else []) + extenso(r)
    return [str(n)]


EN_UNIDADES = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven",
               "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"]
EN_DEZENAS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]


def extenso_en(n: int) -> list[str]:
    """Número inteiro → palavras em inglês. Anos 1100–1999 / 2010+ como se falam ("nineteen nineteen")."""
    if n < 20:
        return [EN_UNIDADES[n]]
    if n < 100:
        d, u = divmod(n, 10)
        return [EN_DEZENAS[d]] + ([EN_UNIDADES[u]] if u else [])
    if 1100 <= n < 2000 or 2010 <= n < 2100:
        a, b = divmod(n, 100)
        return extenso_en(a) + (["hundred"] if b == 0 else (["oh"] if b < 10 else []) + extenso_en(b))
    if n < 1000:
        c, r = divmod(n, 100)
        return extenso_en(c) + ["hundred"] + (extenso_en(r) if r else [])
    for valor, nome in ((10 ** 9, "billion"), (10 ** 6, "million"), (1000, "thousand")):
        if n >= valor:
            q, r = divmod(n, valor)
            return extenso_en(q) + [nome] + (extenso_en(r) if r else [])
    return [str(n)]


def _ingles() -> bool:
    try:
        from common import idioma
        return idioma().lower().startswith("en")
    except Exception:  # noqa: BLE001
        return False


def normalizar(palavra: str, ingles: bool | None = None) -> list[str]:
    ingles = _ingles() if ingles is None else ingles
    s = unicodedata.normalize("NFD", palavra.lower())
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    # DEMO: o whisper escreve "0,1" como "0" + ",1": a vírgula falada ("zero vírgula um") precisa existir na transcrição
    s = re.sub(r"^,(?=\d)", "virgula " if not ingles else "point ", s)
    s = re.sub(r"[^\w%$]+", " ", s).strip()
    out = []
    for parte in s.split():
        if re.fullmatch(r"\d+", parte):
            out += extenso_en(int(parte)) if ingles else extenso(int(parte))
        elif parte == "%":
            out.append("percent" if ingles else "por cento")
        else:
            out.append(parte)
    return [x for p in out for x in p.split()] or [""]


def alinhar(roteiro: str, transcritas: list[dict]) -> tuple[list[dict], float]:
    palavras = roteiro.split()
    ingles = _ingles()
    # sequência "expandida" do roteiro, lembrando de qual palavra original cada token veio
    toks_r, dono = [], []
    for i, p in enumerate(palavras):
        for t in normalizar(p.replace(",", " , ").replace(".", " "), ingles):
            if t:
                toks_r.append(t)
                dono.append(i)
    toks_t, idx_t = [], []
    for j, p in enumerate(transcritas):
        for t in normalizar(p["texto"], ingles):
            if t:
                toks_t.append(t)
                idx_t.append(j)

    tempos: list[list[float]] = [[] for _ in palavras]
    sm = SequenceMatcher(a=toks_r, b=toks_t, autojunk=False)
    casados = 0
    for a, b, n in sm.get_matching_blocks():
        for k in range(n):
            p = transcritas[idx_t[b + k]]
            tempos[dono[a + k]] += [p["ini"], p["fim"]]
            casados += 1
    taxa = casados / max(1, len(toks_r))

    # palavras sem tempo: interpola entre a última conhecida e a próxima conhecida
    fim_total = transcritas[-1]["fim"] if transcritas else 0.0
    out = []
    for i, p in enumerate(palavras):
        if tempos[i]:
            out.append({"texto": p, "ini": min(tempos[i]), "fim": max(tempos[i])})
        else:
            out.append({"texto": p, "ini": None, "fim": None})
    i = 0
    while i < len(out):
        if out[i]["ini"] is not None:
            i += 1
            continue
        j = i
        while j < len(out) and out[j]["ini"] is None:
            j += 1
        t0 = out[i - 1]["fim"] if i > 0 else 0.0
        t1 = out[j]["ini"] if j < len(out) else fim_total
        passo = max(0.0, t1 - t0) / (j - i)
        for k in range(i, j):
            out[k]["ini"] = t0 + (k - i) * passo
            out[k]["fim"] = t0 + (k - i + 1) * passo
        i = j
    return [{"texto": p["texto"], "ini": round(p["ini"], 3), "fim": round(p["fim"], 3)} for p in out], taxa


if __name__ == "__main__":  # autoteste rápido: python pipeline/alinhar.py
    rot = "Em quinze de janeiro de 1919, uma onda varreu Boston. Eram 8,7 milhões de litros."
    fala = ("em quinze de janeiro de mil novecentos e dezenove uma onda varreu bóston eram oito vírgula "
            "sete milhões de litros").split()
    trans = [{"texto": p, "ini": i * 0.3, "fim": i * 0.3 + 0.25} for i, p in enumerate(fala)]
    res, taxa = alinhar(rot, trans)
    for r in res:
        print(f"{r['ini']:6.2f} {r['fim']:6.2f}  {r['texto']}")
    print(f"casamento: {taxa:.0%}")
