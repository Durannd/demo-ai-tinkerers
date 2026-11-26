"""Textos fixos que vão para o PÚBLICO (descrição, SRT, Shorts, cartelas, cenas) em pt-BR e en.

O idioma vem do episódio ativo (common.idioma(): meta.idioma, senão canal.idioma). Mensagens de log e
pendências continuam em português (são para o operador). O Remotion tem o espelho em render/src/comp/i18n.ts.
"""
from __future__ import annotations

from common import idioma

TEXTOS: dict[str, dict] = {
    "pt": {
        "capitulos": "Capítulos:",
        "fontes": "Fontes:",
        "imagens_atribuicao": "Imagens e vídeos com atribuição:",
        "demais_imagens": "Demais imagens: {lista}.",
        "dominio_publico_longo": "domínio público (Wikimedia Commons, NASA)",
        "dominio_publico": "domínio público",
        "musica": "Música:",
        "musica_macleod": "Música: {nomes} — Kevin MacLeod (incompetech.com). Licensed under Creative Commons: "
                          "By Attribution 4.0 — http://creativecommons.org/licenses/by/4.0/",
        "musica_macleod_curto": "Música: {nomes} — Kevin MacLeod (incompetech.com). CC BY 4.0 — "
                                "http://creativecommons.org/licenses/by/4.0/",
        "musica_titulo": "Música: {titulo}",
        "sfx_atribuicao": "Efeitos sonoros (freesound.org):",
        "sfx_curto": "Som: {x}",
        "ia_ilustracoes": "Algumas ilustrações e reconstituições deste vídeo foram geradas por IA.",
        "ia_imagens": "Algumas imagens foram geradas por IA.",
        "voz_sintetica": "Narração com voz sintética.",
        "creditos_imagens": "Créditos das imagens e vídeos:",
        "creditos_no_fixado": "Créditos completos das imagens no comentário fixado.",
        "imagens": "Imagens: {x}",
        "desconhecido": "desconhecido",
        "blocos": {"gancho": "Introdução", "contexto": "Contexto", "desenvolvimento": "Desenvolvimento",
                   "virada": "Virada", "climax": "Clímax", "conclusao": "Conclusão"},
        "falta_midia": "FALTA MÍDIA",
        "peca": "PEÇA",
        "short_do_video": "Do vídeo completo: “{titulo}” — toque no link de vídeo relacionado acima do título.",
        "short_fixado": "Esse é um trecho do vídeo “{titulo}”. A história inteira, com as fontes, está no canal — "
                        "toque em “vídeo relacionado” acima do título. O que você não sabia?",
        "short_cta": "VÍDEO COMPLETO NO CANAL",
        # CTAs animados (pipeline/cta.py → render/cta): botão, estado depois do clique, like, comentário
        "cta_inscrever": "INSCREVA-SE", "cta_inscrito": "INSCRITO", "cta_like": "Deixe seu like",
        "cta_comentar": "Comenta aí",
        "decimal": ",", "milhar": ".",
    },
    "en": {
        "capitulos": "Chapters:",
        "fontes": "Sources:",
        "imagens_atribuicao": "Images and footage with attribution:",
        "demais_imagens": "Other images: {lista}.",
        "dominio_publico_longo": "public domain (Wikimedia Commons, NASA)",
        "dominio_publico": "public domain",
        "musica": "Music:",
        "musica_macleod": "Music: {nomes} — Kevin MacLeod (incompetech.com). Licensed under Creative Commons: "
                          "By Attribution 4.0 — http://creativecommons.org/licenses/by/4.0/",
        "musica_macleod_curto": "Music: {nomes} — Kevin MacLeod (incompetech.com). CC BY 4.0 — "
                                "http://creativecommons.org/licenses/by/4.0/",
        "musica_titulo": "Music: {titulo}",
        "sfx_atribuicao": "Sound effects (freesound.org):",
        "sfx_curto": "Sound: {x}",
        "ia_ilustracoes": "Some illustrations and reconstructions in this video were generated with AI.",
        "ia_imagens": "Some images were generated with AI.",
        "voz_sintetica": "Narrated with a synthetic voice.",
        "creditos_imagens": "Image and footage credits:",
        "creditos_no_fixado": "Full image credits in the pinned comment.",
        "imagens": "Images: {x}",
        "desconhecido": "unknown",
        "blocos": {"gancho": "Introduction", "contexto": "Context", "desenvolvimento": "How it works",
                   "virada": "The twist", "climax": "The big moment", "conclusao": "Conclusion"},
        "falta_midia": "MISSING MEDIA",
        "peca": "PIECE",
        "short_do_video": "From the full video: “{titulo}” — tap the related video link above the title.",
        "short_fixado": "This is a clip from “{titulo}”. The full story, with sources, is on the channel — "
                        "tap “related video” above the title. What surprised you?",
        "short_cta": "FULL VIDEO ON THE CHANNEL",
        "cta_inscrever": "SUBSCRIBE", "cta_inscrito": "SUBSCRIBED", "cta_like": "Leave a like",
        "cta_comentar": "Comment below",
        "decimal": ".", "milhar": ",",
    },
}

# Palavras que não devem terminar uma linha de legenda ("de / 1919" é ruim de ler)
LIGACAO = {
    "pt": {"a", "o", "as", "os", "um", "uma", "de", "da", "do", "das", "dos", "em", "na", "no", "nas", "nos",
           "e", "ou", "que", "para", "por", "com", "sem", "se", "ao", "à", "pelo", "pela", "mais", "seu", "sua"},
    "en": {"a", "an", "the", "of", "to", "in", "on", "at", "and", "or", "for", "with", "by", "from", "as", "that",
           "its", "his", "her", "their", "our", "your", "into", "than", "is", "was", "are", "were", "this", "these"},
}


def lang() -> str:
    """'pt' ou 'en' (idioma do episódio ativo)."""
    return "en" if idioma().lower().startswith("en") else "pt"


def t(chave: str, **kw) -> str:
    txt = TEXTOS[lang()][chave]
    return txt.format(**kw) if kw else txt


def bloco(nome: str) -> str:
    return TEXTOS[lang()]["blocos"].get(nome.lower(), nome.capitalize())


def numero(valor, casas: int = 0) -> str:
    """8700000 → '8.700.000' (pt) / '8,700,000' (en); 8.7 → '8,7' / '8.7'."""
    s = f"{valor:,.{casas}f}" if isinstance(valor, (int, float)) else str(valor)
    if not isinstance(valor, (int, float)):
        return s
    d = TEXTOS[lang()]
    return s.replace(",", "\0").replace(".", d["decimal"]).replace("\0", d["milhar"])
