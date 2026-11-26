"""Gera a narração cena a cena e o tempo de cada palavra (para legendas e para sincronizar animações).

Provedores (config.json → voz.provedor):
  openrouter         ElevenLabs via OpenRouter (/audio/speech). Não devolve timestamps → alinhamento à parte.
  elevenlabs_direto  API da ElevenLabs (/with-timestamps): devolve o tempo de cada caractere.
  mock               áudio mudo com duração estimada (testes, sem gastar nada).
  chatterbox         LOCAL, pt-BR: Chatterbox Multilingual V3 pt-BR (MIT) na GPU, pelo venv do WanGP
                     (config ia_local; voz.chatterbox). Frase a frase, com checagem anti-alucinação.
  kokoro             LOCAL, inglês: Kokoro-82M ONNX (Apache) no próprio .venv, CPU ou DirectML (voz.kokoro).

Alinhamento (voz.alinhador para openrouter; voz.alinhador_local para chatterbox/kokoro):
  scribe   transcreve com elevenlabs/scribe-v2 via OpenRouter (~US$ 0,11/hora) e casa com o roteiro.
  whisper  transcreve offline com faster-whisper (CPU int8, voz.whisper_modelo) e casa com o roteiro. Como
           não é forçado, a taxa de casamento também denuncia voz que leu outra coisa (alucinação).
  local    alinhamento forçado offline com stable-ts (pip install stable-ts; melhor com GPU).
  nenhum   distribui as palavras pela duração (legenda aproximada).

Uso:
  python pipeline/narrar.py <slug>                 # gera só o que mudou (cache por hash do texto + voz)
  python pipeline/narrar.py <slug> --cenas c03,c07 # força refazer cenas específicas (GASTA)
  python pipeline/narrar.py <slug> --mock          # sem API
  python pipeline/narrar.py <slug> --realinhar     # refaz só o alinhamento (não regrava a voz)
  python pipeline/narrar.py <slug> --provedor chatterbox   # troca o provedor só nesta execução
  python pipeline/narrar.py --texto "Frase." --saida x.mp3 [--provedor kokoro] 
                                                   # narração avulsa (+ x.json com os tempos por palavra)

Saída: episodios/<slug>/audio/<id>.mp3 e <id>.json  {hash, texto, duracao, palavras:[{texto,ini,fim}], ...}
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import subprocess
import time
from pathlib import Path

from alinhar import alinhar, extenso, extenso_en
from common import (ativar_canal, canal_ativo, checar_ffmpeg, chave, config, duracao, ler_json, ler_storyboard, log, pasta_episodio,
                    rodar, salvar_json)
from validar import estimar_segundos

OPENROUTER = "https://openrouter.ai/api/v1"
ELEVEN_DIRETO = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/with-timestamps"
LIMITE_CARACTERES = {"eleven-v3": 5000, "eleven-v3-conversational": 5000}  # demais: 10 mil+
SEM_SPEED = ("eleven-v4",)  # v4 e v4-turbo rejeitam speed ≠ padrão
SEM_STITCHING = ("eleven-v3", "eleven_v3")
RE_VOICE_ID = re.compile(r"^[A-Za-z0-9]{18,24}$")
LOCAIS = ("chatterbox", "kokoro")  # provedores locais (sem custo por caractere; sem timestamps → alinhador_local)
CHATTERBOX_PADRAO = {"referencia": None, "exaggeration": 0.4, "cfg_weight": 0.5, "temperature": 0.8, "seed": 7,
                     "pausa": 0.25, "chars_por_segundo": 14.0, "max_tentativas": 3, "casamento_minimo": 0.8, "velocidade": 1.0,
                     "regeracoes_cena": 1, "dispositivo": "cuda", "codigo": "chatterbox-ptbr",
                     "modelos": "modelos/chatterbox-ptbr"}
KOKORO_PADRAO = {"voz": "am_michael", "velocidade": 1.0, "idioma": "en-us", "onnx": "cpu",
                 "modelo": "kokoro/kokoro-v1.0.fp16.onnx", "vozes": "kokoro/voices-v1.0.bin"}
GEMINI_PADRAO = {"modelo": "gemini-2.5-flash-preview-tts", "voz": "Algenib", "tentativas": 9, "casamento_minimo": 0.85,
                 "regeracoes_cena": 2,
                 "estilo": {"pt": "Narre em português do Brasil, tom de documentário, firme e natural: ",
                            "en": "Narrate in American English, documentary tone, firm and natural: "}}
# o que muda o áudio de cada provedor local (entra no hash do cache; os provedores pagos ficam com o hash antigo)
CHAVES_LOCAIS = {"chatterbox": ("referencia", "exaggeration", "cfg_weight", "temperature", "seed", "pausa"),
                 "kokoro": ("voz", "velocidade", "idioma", "modelo")}


def cfg_voz() -> dict:
    """Normaliza o config: aceita o formato antigo (voice_id/model_id) e o novo (provedor/modelo/voice)."""
    v = dict(config()["voz"])
    v.setdefault("provedor", "elevenlabs_direto" if "model_id" in v and "modelo" not in v else "openrouter")
    v.setdefault("alinhador", "scribe")
    v.setdefault("stitching", True)
    v["chatterbox"] = {**CHATTERBOX_PADRAO, **(v.get("chatterbox") or {})}
    v["kokoro"] = {**KOKORO_PADRAO, **(v.get("kokoro") or {})}
    v["gemini"] = {**GEMINI_PADRAO, **(v.get("gemini") or {})}
    v.setdefault("whisper_modelo", "small")
    v.setdefault("stutter_pausa_min", 0.15)   # pausa intra-palavra ≥ isso = stutter → regera a cena
    v.setdefault("stutter_regeracoes", 2)    # tentativas extras por cena (só provedores pagos)
    if v["provedor"] in LOCAIS:
        v["alinhador"] = v.get("alinhador_local") or "whisper"
    elif v["provedor"] == "gemini":
        v["alinhador"] = v.get("alinhador_local") or "whisper"  # o Gemini TTS não devolve tempos por palavra
    elif v["provedor"] == "openrouter":
        v.setdefault("modelo", "elevenlabs/eleven-multilingual-v2")
        v.setdefault("voice", v.get("voice_id", ""))
    else:
        v.setdefault("model_id", "eleven_multilingual_v2")
        v.setdefault("voice_id", v.get("voice", ""))
    return v


def hash_texto(texto: str, voz: dict) -> str:
    prov = voz.get("provedor")
    if prov in LOCAIS:  # só os ajustes do provedor local (trocar de voz paga não invalida a local e vice-versa)
        ajustes = {k: voz[prov].get(k) for k in CHAVES_LOCAIS[prov]}
        if prov == "chatterbox" and float(voz[prov].get("velocidade") or 1.0) != 1.0:  # 1.0 mantém o hash antigo
            ajustes["velocidade"] = float(voz[prov]["velocidade"])
        base = json.dumps([texto, prov, ajustes], sort_keys=True)
        return hashlib.sha1(base.encode()).hexdigest()[:12]
    if prov == "gemini":
        g = voz["gemini"]
        base = json.dumps([texto, prov, g.get("modelo"), g.get("voz"), g.get("estilo")], sort_keys=True)
        return hashlib.sha1(base.encode()).hexdigest()[:12]
    chaves = ["provedor", "modelo", "voice", "voice_id", "model_id", "voice_settings", "seed"]
    base = json.dumps([texto, {k: voz.get(k) for k in chaves}], sort_keys=True)
    return hashlib.sha1(base.encode()).hexdigest()[:12]


def _settings(voz: dict) -> dict:
    s = dict(voz.get("voice_settings") or {})
    modelo = voz.get("modelo", voz.get("model_id", ""))
    if any(m in modelo for m in SEM_SPEED) and s.get("speed", 1.0) != 1.0:
        log("  aviso: eleven-v4 não aceita 'speed' ≠ 1.0 — ignorando (use audio tags para ritmo)")
        s.pop("speed", None)
    return s


# ---------------------------------------------------------------- OpenRouter
def _post_openrouter(caminho: str, **kw):
    import requests

    h = {"Authorization": f"Bearer {chave('OPENROUTER_API_KEY')}", "HTTP-Referer": "https://github.com/canal-harness",
         "X-Title": "canal-harness"}
    r = requests.post(f"{OPENROUTER}{caminho}", headers=h, timeout=300, **kw)
    if r.status_code != 200:
        dica = ""
        if r.status_code in (400, 403, 404) and "voice" in r.text.lower():
            dica = " — vozes clonadas/desenhadas exigem BYOK (cadastre sua chave ElevenLabs nas integrações da OpenRouter)"
        raise RuntimeError(f"OpenRouter {caminho} {r.status_code}: {r.text[:400]}{dica}")
    return r


def narrar_openrouter(texto: str, voz: dict, anterior: str | None, proximo: str | None) -> tuple[bytes, dict]:
    modelo = voz["modelo"]
    limite = next((v for k, v in LIMITE_CARACTERES.items() if modelo.endswith(k)), 10000)
    if len(texto) > limite:
        raise RuntimeError(f"cena com {len(texto)} caracteres > limite {limite} de {modelo}: divida a cena")
    opcoes = {"voice_settings": _settings(voz)}
    if voz.get("seed") is not None:
        opcoes["seed"] = voz["seed"]
    if voz.get("idioma"):
        opcoes["language_code"] = voz["idioma"]
    # request stitching: continuidade de entonação entre cenas (não suportado no v3)
    if voz.get("stitching") and not any(m in modelo for m in SEM_STITCHING):
        if anterior:
            opcoes["previous_text"] = anterior
        if proximo:
            opcoes["next_text"] = proximo
    corpo = {"model": modelo, "input": texto, "voice": voz["voice"], "response_format": "mp3",
             "provider": {"options": {"elevenlabs": opcoes}}}
    r = _post_openrouter("/audio/speech", json=corpo)
    return r.content, {"geracao": r.headers.get("X-Generation-Id"), "opcoes_enviadas": opcoes}


# ---------------------------------------------------------------- Gemini TTS (Google, pago por token de áudio)
def narrar_gemini(texto: str, voz: dict, anterior: str | None = None, proximo: str | None = None) -> tuple[bytes, dict]:
    """Gemini TTS (voz.gemini: modelo, voz, estilo). Devolve mp3; sem tempos por palavra (alinhador whisper)."""
    import requests

    g = voz["gemini"]
    estilo = g["estilo"]
    if isinstance(estilo, dict):
        estilo = estilo.get(str(voz.get("idioma") or "pt")[:2], estilo.get("pt", ""))
    corpo = {"contents": [{"parts": [{"text": f"{estilo}{texto}"}]}],
             "generationConfig": {"responseModalities": ["AUDIO"],
                                  "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": g["voz"]}}}}}
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{g['modelo']}:generateContent"
    ultimo = ""
    for k in range(int(g["tentativas"])):
        r = requests.post(url, json=corpo, timeout=300,
                          headers={"x-goog-api-key": chave("GEMINI_API_KEY"), "Content-Type": "application/json"})
        if r.status_code == 200:
            try:
                parte = r.json()["candidates"][0]["content"]["parts"][0]["inlineData"]
                pcm = base64.b64decode(parte["data"])
            except (KeyError, IndexError):
                ultimo = f"resposta sem áudio: {r.text[:200]}"  # o modelo às vezes devolve texto em vez de áudio
                time.sleep(2)
                continue
            mp3 = subprocess.run(["ffmpeg", "-v", "error", "-f", "s16le", "-ar", "24000", "-ac", "1", "-i", "pipe:0",
                                  "-codec:a", "libmp3lame", "-q:a", "2", "-f", "mp3", "pipe:1"],
                                 input=pcm, capture_output=True, check=True).stdout
            return mp3, {"gemini": {"modelo": g["modelo"], "voz": g["voz"]}}
        ultimo = f"{r.status_code}: {r.text[:200]}"
        if r.status_code in (429, 500, 503):
            time.sleep(min(60, 5 * 2 ** k))
            continue
        break
    raise RuntimeError(f"Gemini TTS falhou — {ultimo}")


def transcrever_scribe(mp3_bytes: bytes, idioma: str, termos: list[str]) -> list[dict]:
    corpo = {"model": "elevenlabs/scribe-v2",
             "input_audio": {"data": base64.b64encode(mp3_bytes).decode(), "format": "mp3"},
             "language": idioma[:2], "response_format": "verbose_json", "timestamp_granularities": ["word"]}
    # 'keyterms' (nomes próprios) é recusado pelo OpenRouter (400, out/2026); termos fica para quando suportar
    dados = _post_openrouter("/audio/transcriptions", json=corpo).json()
    palavras = dados.get("words") or [w for s in dados.get("segments", []) for w in s.get("words", [])]
    return [{"texto": w.get("word") or w.get("text", ""), "ini": float(w["start"]), "fim": float(w["end"])}
            for w in palavras if (w.get("word") or w.get("text", "")).strip()]


def alinhar_local(mp3, texto: str, idioma: str) -> list[dict]:
    try:
        import stable_whisper  # type: ignore
    except ImportError:
        raise SystemExit("[erro] alinhador 'local' precisa do stable-ts: .venv/bin/pip install stable-ts "
                         "(com GPU NVIDIA, instale antes o torch com CUDA)")
    modelo = stable_whisper.load_model("base")
    res = modelo.align(str(mp3), texto, language=idioma[:2])
    return [{"texto": w.word.strip(), "ini": float(w.start), "fim": float(w.end)} for w in res.all_words()]


_WHISPER: dict = {}


def transcrever_whisper(mp3, idioma: str, modelo: str = "small", termos: list[str] | None = None) -> list[dict]:
    """Transcrição offline com tempo por palavra (faster-whisper, CPU int8). Não é forçada: se a voz falou outra
    coisa, a transcrição mostra, e a taxa de casamento do alinhar() cai."""
    try:
        from faster_whisper import WhisperModel  # type: ignore
    except ImportError:
        raise SystemExit("[erro] alinhador 'whisper' precisa do faster-whisper no .venv (sem trocar o onnxruntime-"
                         "directml): pip install --no-deps faster-whisper && pip install ctranslate2 tokenizers "
                         "huggingface_hub av")
    import numpy as np

    if modelo not in _WHISPER:
        from common import RAIZ  # DEMO: cache do modelo dentro do repo (scripts/preparar.ps1 baixa; assets/modelos/ é gitignored)
        _WHISPER[modelo] = WhisperModel(modelo, device="cpu", compute_type="int8",
                                        download_root=str(RAIZ / "assets" / "modelos" / "faster-whisper"))
    # decodifica com o ffmpeg (o decode_audio do faster-whisper quebra com PyAV ≥ 15)
    pcm = subprocess.run(["ffmpeg", "-v", "error", "-i", str(mp3), "-ac", "1", "-ar", "16000", "-f", "f32le", "-"],
                         capture_output=True, check=True).stdout
    segs, _ = _WHISPER[modelo].transcribe(np.frombuffer(pcm, np.float32), language=idioma[:2], beam_size=5,
                                          word_timestamps=True, vad_filter=False,
                                          initial_prompt=", ".join(termos[:40]) if termos else None)
    return [{"texto": w.word.strip(), "ini": float(w.start), "fim": float(w.end)}
            for s in segs for w in (s.words or []) if w.word.strip()]


# ---------------------------------------------------------------- provedores locais (chatterbox / kokoro)
ACENTOS = {"tres": "três", "milhao": "milhão", "milhoes": "milhões", "bilhao": "bilhão", "bilhoes": "bilhões"}


def texto_para_fala(texto: str, idioma: str) -> str:
    """Números → extenso antes do TTS local (os modelos locais tropeçam em "1817", "8,7", "1.500").
    Só altera o que vai para a voz; legenda e alinhamento continuam com o texto do roteiro."""
    if idioma.lower().startswith("en"):
        # o fonemizador do Kokoro lê números; só os anos viram "eighteen seventeen" (senão: "one thousand...")
        return re.sub(r"\b(1[1-9]\d\d|20\d\d)\b", lambda m: " ".join(extenso_en(int(m.group(1)))), texto)

    def pt(n: int) -> str:
        return " ".join(ACENTOS.get(w, w) for w in extenso(n))

    def troca(m: re.Match) -> str:
        s = m.group(0).replace(".", "")
        if "," in s:
            a, b = s.split(",", 1)
            dec = " ".join(pt(int(d)) for d in b) if b.startswith("0") else pt(int(b))
            return f"{pt(int(a))} vírgula {dec}"
        return pt(int(s))

    t = re.sub(r"\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+(?:,\d+)?", troca, texto)
    return re.sub(r"\s*%", " por cento", t)


def para_mp3(wav: Path, mp3: Path, velocidade: float = 1.0) -> None:
    # velocidade ≠ 1: atempo (muda o ritmo sem mudar o tom) — o Chatterbox pt-BR fala ~210 palavras/min
    filtro = ["-af", f"atempo={velocidade:.3f}"] if abs(velocidade - 1.0) > 1e-3 else []
    rodar(["ffmpeg", "-y", "-v", "error", "-i", str(wav), *filtro, "-ar", "44100", "-c:a", "libmp3lame", "-b:a", "192k",
           str(mp3)])


_KOKORO: dict = {}


def narrar_kokoro(texto: str, voz: dict, destino: Path) -> dict:
    """Kokoro-82M (ONNX) no próprio processo. destino = .mp3 (mesma saída dos outros provedores)."""
    import ia_local
    try:
        import onnxruntime as ort
        import soundfile as sf
        from kokoro_onnx import Kokoro  # type: ignore
    except ImportError:
        raise SystemExit("[erro] provedor 'kokoro' precisa do kokoro-onnx no .venv SEM trocar o onnxruntime-directml:"
                         " pip install --no-deps kokoro-onnx && pip install espeakng-loader phonemizer soundfile")
    k = voz["kokoro"]
    modelo, vozes = (Path(k[x]) if Path(k[x]).is_absolute() else ia_local.pasta() / k[x] for x in ("modelo", "vozes"))
    if not modelo.exists():
        raise SystemExit(f"[erro] modelo do Kokoro não encontrado: {modelo} (veja HANDOFF 17/10/2026)")
    if (modelo, k["onnx"]) not in _KOKORO:
        prov = ["DmlExecutionProvider", "CPUExecutionProvider"] if k["onnx"] == "directml" else ["CPUExecutionProvider"]
        _KOKORO[(modelo, k["onnx"])] = Kokoro.from_session(ort.InferenceSession(str(modelo), providers=prov),
                                                           str(vozes))
    t0 = time.time()
    amostras, sr = _KOKORO[(modelo, k["onnx"])].create(texto_para_fala(texto, "en"), voice=k["voz"],
                                                       speed=float(k["velocidade"]), lang=k["idioma"])
    wav = destino.with_suffix(".tmp.wav")
    sf.write(wav, amostras, sr)
    para_mp3(wav, destino)
    wav.unlink(missing_ok=True)
    return {"tts_local": {"segundos": round(time.time() - t0, 1), "voz": k["voz"]}}


def narrar_chatterbox_lote(itens: list[dict], voz: dict, idioma: str) -> dict[str, dict]:
    """Gera várias cenas numa chamada só (o modelo carrega uma vez na GPU). itens: [{id, texto, destino(.mp3), seed}].
    Devolve {id: info}. Roda no venv do WanGP via pipeline/ia_local_ponte.py."""
    import ia_local
    if not idioma.lower().startswith("pt"):
        log(f"  aviso: o checkpoint do Chatterbox instalado é pt-BR; idioma do episódio = {idioma}")
    c = voz["chatterbox"]
    base = ia_local.pasta()
    ref = c.get("referencia")
    if ref and not Path(ref).is_absolute():
        ref = str((Path(__file__).resolve().parent.parent / ref).resolve())
    job = {"tipo": "chatterbox", "codigo": str(base / c["codigo"]), "modelos": str(base / c["modelos"]),
           "referencia": ref, "dispositivo": c["dispositivo"],
           **{k: c[k] for k in ("exaggeration", "cfg_weight", "temperature", "pausa", "chars_por_segundo",
                                "max_tentativas")},
           "itens": [{"id": it["id"], "texto": texto_para_fala(it["texto"], idioma), "seed": it["seed"],
                      "destino": str(Path(it["destino"]).with_suffix(".tmp.wav"))} for it in itens]}
    out = {}
    for r in ia_local.rodar_ponte(job, "Chatterbox"):
        it = next(i for i in itens if i["id"] == r["id"])
        wav = Path(it["destino"]).with_suffix(".tmp.wav")
        para_mp3(wav, Path(it["destino"]), float(c.get("velocidade") or 1.0))
        wav.unlink(missing_ok=True)
        out[r["id"]] = {k: r[k] for k in ("segundos", "regeracoes", "avisos")}
    return out


# ---------------------------------------------------------------- ElevenLabs direto
def narrar_direto(texto: str, voz: dict, anterior: str | None, proximo: str | None) -> tuple[bytes, dict]:
    import requests

    corpo = {"text": texto, "model_id": voz["model_id"], "voice_settings": _settings(voz)}
    if voz.get("seed") is not None:
        corpo["seed"] = int(voz["seed"])
    if voz.get("stitching", True) and voz["model_id"] not in SEM_STITCHING:
        if anterior:
            corpo["previous_text"] = anterior
        if proximo:
            corpo["next_text"] = proximo
    r = requests.post(ELEVEN_DIRETO.format(voice_id=voz["voice_id"]),
                      params={"output_format": voz.get("output_format", "mp3_44100_128")},
                      headers={"xi-api-key": chave("ELEVENLABS_API_KEY"), "Content-Type": "application/json"},
                      json=corpo, timeout=180)
    if r.status_code != 200:
        raise RuntimeError(f"ElevenLabs {r.status_code}: {r.text[:400]}")
    dados = r.json()
    return base64.b64decode(dados["audio_base64"]), {"alignment": dados.get("alignment") or {}}


def palavras_de_caracteres(al: dict) -> list[dict]:
    out, atual, t0, ultimo = [], "", None, 0.0
    for ch, a, b in zip(al.get("characters", []), al.get("character_start_times_seconds", []),
                        al.get("character_end_times_seconds", [])):
        if ch.isspace():
            if atual:
                out.append({"texto": atual, "ini": t0, "fim": ultimo})
            atual, t0 = "", None
            continue
        t0 = a if t0 is None else t0
        atual += ch
        ultimo = b
    if atual:
        out.append({"texto": atual, "ini": t0, "fim": ultimo})
    return out


# -------------------------------------------- pós-cheque acústico (stutter / vazamento do stitching)
SR_VOZ = 16000


def _pcm_voz(mp3: Path):
    import numpy as np

    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(mp3), "-f", "s16le", "-ac", "1",
                          "-ar", str(SR_VOZ), "-"], capture_output=True).stdout
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768


def _trechos_voz(pcm, ini: float, fim: float, limiar: float = 0.018, minimo: float = 0.04) -> list:
    import numpy as np

    a, b = max(0, int(ini * SR_VOZ)), min(len(pcm), int(fim * SR_VOZ))
    trechos, s = [], None
    for i in range(a, b - 159, 160):
        on = float(np.sqrt(np.mean(pcm[i:i + 160] ** 2))) > limiar
        t = i / SR_VOZ
        if on and s is None:
            s = t
        elif not on and s is not None:
            if t - s >= minimo:
                trechos.append((s, t))
            s = None
    if s is not None and b / SR_VOZ - s >= minimo:
        trechos.append((s, b / SR_VOZ))
    return trechos


def fragmentos_borda(pcm, palavras: list, dur: float, lead: float = 0.10, cauda: float = 0.35) -> list:
    """Voz FORA do span alinhado ([1ª palavra − lead] … [última + cauda]). O request-stitching
    (previous_text/next_text) às vezes vaza um fonema da cena vizinha na cauda/cabeça do MP3 —
    ouvido emendado, vira um "F" solto antes do "Fleming" da próxima cena."""
    ini = max(0.0, float(palavras[0]["ini"]) - lead)
    fim = min(dur, float(palavras[-1]["fim"]) + cauda)
    return _trechos_voz(pcm, 0.0, ini, limiar=0.008) + _trechos_voz(pcm, fim, dur, limiar=0.008)


def _fracao_silencio(pcm, ini: float, fim: float, fundo: float = 0.014) -> float:
    """Fração das janelas de 10 ms em [ini, fim] com RMS < fundo (silêncio de verdade, sem respiração)."""
    import numpy as np

    a, b = max(0, int(ini * SR_VOZ)), min(len(pcm), int(fim * SR_VOZ))
    n = max(0, (b - a) // 160)
    if not n:
        return 0.0
    mudas = sum(1 for i in range(a, a + n * 160, 160)
                if float(np.sqrt(np.mean(pcm[i:i + 160] ** 2))) < fundo)
    return mudas / n


def pausas_intrapalavra(pcm, palavras: list, minimo: float = 0.15, fundo: float = 0.014) -> list:
    """Silêncio PROFUNDO ≥ minimo DENTRO do span alinhado de uma palavra, com voz dos dois lados: a
    assinatura do stutter do TTS (fonema inicial, pausa, palavra refeita). Oclusivas legítimas ficam
    < ~120 ms; cauda aspirada (~0,02 RMS) não é silêncio — por isso ≥70% das janelas do gap mudas.
    Com palavras uniformes (sem alinhador) cada span cobre a pausa entre palavras → não roda."""
    sus = []
    for w in palavras:
        ini, fim = float(w["ini"]), float(w["fim"])
        if fim - ini < minimo + 0.12:
            continue
        seg = _trechos_voz(pcm, ini, fim)
        for (_, t0), (s1, _) in zip(seg, seg[1:]):
            if s1 - t0 >= minimo and _fracao_silencio(pcm, t0, s1, fundo) >= 0.7:
                sus.append({"palavra": w["texto"], "ini": round(t0, 3), "fim": round(s1, 3)})
    return sus


def _alinhamento_real(palavras: list) -> bool:
    """Tempos vêm de transcrição/alinhamento de verdade? (palavras_uniformes é contíguo: fim = próx. ini)"""
    return len(palavras) < 2 or any(float(b["ini"]) - float(a["fim"]) > 0.005
                                  for a, b in zip(palavras, palavras[1:]))


def silenciar_trechos(mp3: Path, trechos: list, margem: float = 0.02) -> None:
    """Zera trechos do arquivo no lugar, sem mudar a duração (as pontas caem em quase-silêncio)."""
    filtro = ",".join(
        f"volume=0:enable='between(t,{max(0.0, s - margem):.3f},{t + margem:.3f})'" for s, t in trechos)
    tmp = mp3.with_name(mp3.stem + ".fix" + mp3.suffix)
    rodar(["ffmpeg", "-y", "-v", "error", "-i", str(mp3), "-af", filtro, str(tmp)])
    tmp.replace(mp3)


def excisar_pausas(mp3: Path, palavras: list, sus: list, dur: float, manter: float = 0.08) -> tuple:
    """Corta o excesso das pausas de stutter: mantém `manter` s do início de cada gap (o hold natural
    da consoante — "F" + "leming" cola de volta em "Fleming") e junta o resto. Reescreve o arquivo
    no lugar e devolve (palavras com tempos atualizados, nova duração)."""
    cortes = sorted({(s["ini"], s["fim"]) for s in sus})
    keeps, pos, removidos = [], 0.0, []
    for s, t in cortes:
        keeps.append((pos, s + manter))
        removidos.append((s + manter, t))
        pos = t
    keeps.append((pos, dur))
    filtro = "".join(f"[0:a]atrim=start={a:.3f}:end={b:.3f},asetpts=PTS-STARTPTS[k{i}];"
                     for i, (a, b) in enumerate(keeps)) + \
             "".join(f"[k{i}]" for i in range(len(keeps))) + f"concat=n={len(keeps)}:v=0:a=1[out]"
    tmp = mp3.with_name(mp3.stem + ".fix" + mp3.suffix)
    rodar(["ffmpeg", "-y", "-v", "error", "-i", str(mp3), "-filter_complex", filtro, "-map", "[out]", str(tmp)])
    tmp.replace(mp3)

    def novo_t(t: float) -> float:
        nt = t
        for a, b in removidos:
            if t >= b:
                nt -= b - a
            elif t > a:
                nt = a - sum(bb - aa for aa, bb in removidos if bb <= a)
                break
        return nt

    for w in palavras:
        w["ini"], w["fim"] = round(novo_t(float(w["ini"])), 3), round(novo_t(float(w["fim"])), 3)
    return palavras, duracao(mp3)


# ---------------------------------------------------------------- mock
def narrar_mock(texto: str, idioma: str, destino) -> list[dict]:
    seg = max(1.5, estimar_segundos(texto, idioma))
    rodar(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono", "-t", f"{seg:.2f}",
           "-c:a", "libmp3lame", "-b:a", "128k", str(destino)])
    ws = texto.split()
    pesos = [len(p) + 2 for p in ws]
    total, t, out = sum(pesos), 0.0, []
    for p, peso in zip(ws, pesos):
        d = seg * peso / total
        out.append({"texto": p, "ini": round(t, 3), "fim": round(t + d * 0.9, 3)})
        t += d
    return out


def palavras_uniformes(texto: str, dur: float) -> list[dict]:
    ws = texto.split()
    passo = dur / max(1, len(ws))
    return [{"texto": p, "ini": round(i * passo, 3), "fim": round((i + 1) * passo, 3)} for i, p in enumerate(ws)]


def termos_chave(sb: dict) -> list[str]:
    """Palavras com maiúscula no meio da frase (nomes próprios) → keyterms do Scribe."""
    nomes = set()
    for c in sb["cenas"]:
        for m in re.finditer(r"(?<![.!?]\s)(?<!^)\b([A-ZÁÉÍÓÚÂÊÔÃÕÇ][\wáéíóúâêôãõç]+)", c["narracao"]):
            nomes.add(m.group(1))
    return sorted(nomes)


def checar_voz(voz: dict) -> None:
    prov = voz["provedor"]
    if prov not in ("openrouter", "elevenlabs_direto", "mock", "gemini") + LOCAIS:
        raise SystemExit(f"[erro] voz.provedor '{prov}' desconhecido (openrouter | elevenlabs_direto | gemini | mock | "
                         f"{' | '.join(LOCAIS)})")
    if prov == "openrouter" and (not voz.get("voice") or voz["voice"].startswith("COLE_")):
        raise SystemExit("[erro] Defina voz.voice em config.json (nome premade, ex. \"george\", ou voice ID)")
    if prov == "elevenlabs_direto" and voz["voice_id"].startswith("COLE_"):
        raise SystemExit("[erro] Defina voz.voice_id em config.json")
    if prov == "openrouter" and RE_VOICE_ID.match(voz["voice"]):
        log("  nota: voice ID personalizado — se for voz clonada/desenhada da sua conta, a OpenRouter exige BYOK.")


def alinhar_audio(texto: str, mp3: Path, voz: dict, idioma: str, termos: list[str]) -> tuple[list[dict], float | None]:
    """Tempos por palavra pelo alinhador configurado (voz.alinhador). Devolve (palavras, taxa de casamento|None)."""
    metodo = voz["alinhador"]
    if metodo == "scribe":
        transcritas = transcrever_scribe(mp3.read_bytes(), idioma, termos)
    elif metodo == "whisper":
        transcritas = transcrever_whisper(mp3, idioma, voz["whisper_modelo"], termos)
    elif metodo == "local":
        transcritas = alinhar_local(mp3, texto, idioma)
    else:
        transcritas = []
    if transcritas:
        return alinhar(texto, transcritas)
    return palavras_uniformes(texto, duracao(mp3)), None


def narrar_avulsa(texto: str, saida: Path, prov: str | None, idioma: str | None) -> None:
    """Uma narração fora de episódio (comparar provedores, Short de teste). Grava saida(.mp3) + saida.json."""
    voz = cfg_voz()
    if prov:
        voz["provedor"] = prov
        if prov in LOCAIS:
            voz["alinhador"] = voz.get("alinhador_local") or "whisper"
    prov = voz["provedor"]
    checar_voz(voz)
    idioma = idioma or config().get("canal", {}).get("idioma", "pt-BR")
    if prov == "kokoro" and not idioma.lower().startswith("en"):  # Kokoro instalado = inglês americano
        idioma = "en"
        ativar_canal(canal_ativo(), "en")  # alinhar() expande números em inglês
    voz.setdefault("idioma", idioma[:2])
    mp3 = saida.with_suffix(".mp3")
    mp3.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    extra: dict = {}
    if prov == "mock":
        narrar_mock(texto, idioma, mp3)
    elif prov == "openrouter":
        audio, extra = narrar_openrouter(texto, voz, None, None)
        mp3.write_bytes(audio)
    elif prov == "elevenlabs_direto":
        audio, extra = narrar_direto(texto, voz, None, None)
        mp3.write_bytes(audio)
    elif prov == "gemini":
        audio, extra = narrar_gemini(texto, voz)
        mp3.write_bytes(audio)
    elif prov == "kokoro":
        extra = narrar_kokoro(texto, voz, mp3)
    else:
        info = narrar_chatterbox_lote([{"id": "avulsa", "texto": texto, "destino": str(mp3),
                                        "seed": voz["chatterbox"]["seed"]}], voz, idioma)
        extra = {"tts_local": info["avulsa"]}
    gerar = time.time() - t0
    if prov == "elevenlabs_direto":
        palavras, taxa = alinhar(texto, palavras_de_caracteres(extra.get("alignment") or {}))
    elif prov == "mock":
        palavras, taxa = palavras_uniformes(texto, duracao(mp3)), None
    else:
        palavras, taxa = alinhar_audio(texto, mp3, voz, idioma, [])
    dur = duracao(mp3)
    if prov != "mock" and palavras and _alinhamento_real(palavras):
        sus = pausas_intrapalavra(_pcm_voz(mp3), palavras, float(voz["stutter_pausa_min"]))
        if sus:
            palavras, dur = excisar_pausas(mp3, palavras, sus, dur)
            log(f"  stutter em {', '.join(sorted({s['palavra'] for s in sus}))} corrigido na edição")
        frags = fragmentos_borda(_pcm_voz(mp3), palavras, dur)
        if frags:
            silenciar_trechos(mp3, frags)
            dur = duracao(mp3)
            log(f"  {len(frags)} fragmento(s) de voz na borda (stitching) — silenciados")
    salvar_json(mp3.with_suffix(".json"), {"texto": texto, "duracao": dur, "provedor": prov, "palavras": palavras,
                                           "casamento": round(taxa, 3) if taxa is not None else None, **extra})
    if saida.suffix.lower() == ".wav":
        rodar(["ffmpeg", "-y", "-v", "error", "-i", str(mp3), str(saida)])
    log(f"{prov}: {dur:.1f}s de áudio em {gerar:.1f}s -> {saida}"
        + (f"  (casamento {taxa:.0%})" if taxa is not None else ""))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("slug", nargs="?")
    ap.add_argument("--cenas", default="")
    ap.add_argument("--mock", action="store_true")
    ap.add_argument("--realinhar", action="store_true")
    ap.add_argument("--provedor", help="sobrescreve voz.provedor nesta execução: " + " | ".join(
        ("openrouter", "elevenlabs_direto", "gemini", "mock") + LOCAIS))
    ap.add_argument("--texto", help="narração avulsa (sem episódio); use com --saida")
    ap.add_argument("--saida", help="arquivo da narração avulsa (.mp3 ou .wav)")
    ap.add_argument("--canal", help="canal da narração avulsa (config de voz): demo")
    a = ap.parse_args()

    checar_ffmpeg()
    if a.texto:
        if not a.saida:
            raise SystemExit("[erro] --texto precisa de --saida")
        ativar_canal(a.canal)
        narrar_avulsa(a.texto, Path(a.saida).resolve(), "mock" if a.mock else a.provedor, None)
        return
    if not a.slug:
        ap.error("informe o slug do episódio (ou --texto/--saida para narração avulsa)")
    ep = pasta_episodio(a.slug)
    sb = ler_storyboard(ep)
    voz = cfg_voz()
    if a.provedor:
        voz["provedor"] = a.provedor
        if a.provedor in LOCAIS:
            voz["alinhador"] = voz.get("alinhador_local") or "whisper"
    if a.mock:
        voz["provedor"] = "mock"
    prov = voz["provedor"]
    checar_voz(voz)
    idioma = sb["meta"]["idioma"]
    voz.setdefault("idioma", idioma[:2])
    forcar = {c.strip() for c in a.cenas.split(",") if c.strip()}
    pasta = ep / "audio"
    pasta.mkdir(exist_ok=True)
    cenas = sb["cenas"]
    total_chars, avisos, t_local = 0, [], 0.0
    termos = termos_chave(sb)

    def chave_cache(c: dict) -> tuple[Path, Path, str, dict, bool]:
        mp3, meta_p = pasta / f"{c['id']}.mp3", pasta / f"{c['id']}.json"
        h = hash_texto(c["narracao"], voz) + ("-mock" if prov == "mock" else "")
        antigo = ler_json(meta_p, {})
        return mp3, meta_p, h, antigo, mp3.exists() and antigo.get("hash") == h and c["id"] not in forcar

    # Chatterbox: todas as cenas pendentes numa chamada só (carregar o modelo na GPU custa ~1 min)
    lote: dict[str, dict] = {}
    seed_cb = int(voz["chatterbox"]["seed"])
    if prov == "chatterbox":
        pend = [{"id": c["id"], "texto": c["narracao"], "destino": str(pasta / f"{c['id']}.mp3"), "seed": seed_cb + i}
                for i, c in enumerate(cenas) if not chave_cache(c)[4]]
        if pend:
            t0 = time.time()
            log(f"  Chatterbox: {len(pend)} cena(s) na GPU...")
            lote = narrar_chatterbox_lote(pend, voz, idioma)
            t_local += time.time() - t0

    for i, c in enumerate(cenas):
        mp3, meta_p, h, antigo, em_cache = chave_cache(c)
        if em_cache and not a.realinhar:
            # pós-cheque de graça no cache: fragmento do stitching na borda é silenciado e pausa
            # de stutter intra-palavra é encurtada na edição — tudo in-place, sem regerar voz
            if prov != "mock" and antigo.get("palavras") and _alinhamento_real(antigo["palavras"]):
                pcm = _pcm_voz(mp3)
                sus = pausas_intrapalavra(pcm, antigo["palavras"], float(voz["stutter_pausa_min"]))
                if sus:
                    antigo["palavras"], antigo["duracao"] = excisar_pausas(
                        mp3, antigo["palavras"], sus, float(antigo.get("duracao") or 0))
                    salvar_json(meta_p, antigo)
                    pcm = _pcm_voz(mp3)  # o áudio mudou — re-decodifica antes do cheque de borda
                    avisos.append(f"{c['id']}: stutter em "
                                  f"{', '.join(sorted({s['palavra'] for s in sus}))} corrigido na edição "
                                  f"(pausa intra-palavra encurtada)")
                frags = fragmentos_borda(pcm, antigo["palavras"], float(antigo.get("duracao") or 0))
                if frags:
                    silenciar_trechos(mp3, frags)
                    avisos.append(f"{c['id']}: {len(frags)} fragmento(s) de voz na borda do áudio "
                                  f"(fonema vazado do stitching) — silenciados")
            continue
        anterior = cenas[i - 1]["narracao"] if i > 0 else None
        proximo = cenas[i + 1]["narracao"] if i + 1 < len(cenas) else None
        extra: dict = {}
        if em_cache:
            audio = mp3.read_bytes()
        elif prov == "mock":
            palavras = narrar_mock(c["narracao"], idioma, mp3)
        elif prov == "openrouter":
            audio, extra = narrar_openrouter(c["narracao"], voz, anterior, proximo)
            mp3.write_bytes(audio)
            total_chars += len(c["narracao"])
        elif prov == "gemini":
            audio, extra = narrar_gemini(c["narracao"], voz, anterior, proximo)
            mp3.write_bytes(audio)
            total_chars += len(c["narracao"])
        elif prov == "kokoro":
            extra = narrar_kokoro(c["narracao"], voz, mp3)
            t_local += extra["tts_local"]["segundos"]
        elif prov == "chatterbox":
            extra = {"tts_local": lote[c["id"]]}
            avisos += [f"{c['id']}: {av}" for av in lote[c["id"]].get("avisos", [])]
        else:
            audio, extra = narrar_direto(c["narracao"], voz, anterior, proximo)
            mp3.write_bytes(audio)
            total_chars += len(c["narracao"])
        dur = duracao(mp3)

        if prov == "mock":
            if em_cache:
                palavras = antigo.get("palavras") or palavras_uniformes(c["narracao"], dur)
        elif prov == "elevenlabs_direto" or (em_cache and antigo.get("alignment")):
            al = extra.get("alignment") or antigo.get("alignment") or {}
            palavras, taxa = alinhar(c["narracao"], palavras_de_caracteres(al))
            extra["alignment"] = al
        else:
            palavras, taxa = alinhar_audio(c["narracao"], mp3, voz, idioma, termos)
            # Chatterbox: casamento baixo = leu outra coisa/alucinou → regera a cena com outra seed (fica a melhor)
            cb = voz["chatterbox"]
            for k in range(int(cb["regeracoes_cena"]) if prov == "chatterbox" and not em_cache else 0):
                if taxa is None or taxa >= float(cb["casamento_minimo"]):
                    break
                log(f"  {c['id']}: casamento {taxa:.0%} < {float(cb['casamento_minimo']):.0%} — regerando a cena")
                novo = pasta / f"{c['id']}.regera.mp3"
                t0 = time.time()
                info = narrar_chatterbox_lote([{"id": c["id"], "texto": c["narracao"], "destino": str(novo),
                                                "seed": seed_cb + i + 1000 * (k + 1)}], voz, idioma)[c["id"]]
                t_local += time.time() - t0
                p2, t2 = alinhar_audio(c["narracao"], novo, voz, idioma, termos)
                if t2 is not None and t2 > taxa:
                    novo.replace(mp3)
                    palavras, taxa, dur, extra = p2, t2, duracao(mp3), {"tts_local": info}
                else:
                    novo.unlink(missing_ok=True)
            # Gemini: casamento baixo = leu a instrução de estilo/pulou trecho → regera (fica a melhor)
            gm = voz["gemini"]
            for k in range(int(gm["regeracoes_cena"]) if prov == "gemini" and not em_cache else 0):
                if taxa is None or taxa >= float(gm["casamento_minimo"]):
                    break
                log(f"  {c['id']}: casamento {taxa:.0%} < {float(gm['casamento_minimo']):.0%} — regerando a cena")
                novo = pasta / f"{c['id']}.regera.mp3"
                a2, ex2 = narrar_gemini(c["narracao"], voz, anterior, proximo)
                novo.write_bytes(a2)
                total_chars += len(c["narracao"])
                p2, t2 = alinhar_audio(c["narracao"], novo, voz, idioma, termos)
                if t2 is not None and t2 > taxa:
                    novo.replace(mp3)
                    palavras, taxa, dur, extra = p2, t2, duracao(mp3), ex2
                else:
                    novo.unlink(missing_ok=True)
            if taxa is not None:
                extra["casamento"] = round(taxa, 3)
                if taxa < 0.85:
                    avisos.append(f"{c['id']}: só {taxa:.0%} das palavras casaram — a voz pode ter lido algo "
                                  f"diferente do roteiro; ouça a cena")
        # ---- pós-cheque acústico: stutter intra-palavra (regera) + fragmento do stitching (silencia)
        if prov != "mock" and palavras and _alinhamento_real(palavras):
            pausa_min = float(voz["stutter_pausa_min"])
            sus = pausas_intrapalavra(_pcm_voz(mp3), palavras, pausa_min)
            tentativas = (int(voz["stutter_regeracoes"])
                          if prov in ("openrouter", "elevenlabs_direto") and not em_cache else 0)
            for k in range(tentativas):
                if not sus:
                    break
                log(f"  {c['id']}: pausa de {(sus[0]['fim'] - sus[0]['ini']) * 1000:.0f} ms dentro de "
                    f"'{sus[0]['palavra']}' — stutter provável, regerando")
                novo = pasta / f"{c['id']}.stutter{k + 1}.mp3"
                v2 = dict(voz)
                if v2.get("seed") is not None:
                    v2["seed"] = int(v2["seed"]) + 1001 * (k + 1)
                if prov == "openrouter":
                    audio2, ex2 = narrar_openrouter(c["narracao"], v2, anterior, proximo)
                    novo.write_bytes(audio2)
                    p2, t2 = alinhar_audio(c["narracao"], novo, v2, idioma, termos)
                else:
                    audio2, ex2 = narrar_direto(c["narracao"], v2, anterior, proximo)
                    novo.write_bytes(audio2)
                    p2, t2 = alinhar(c["narracao"], palavras_de_caracteres(ex2.get("alignment") or {}))
                total_chars += len(c["narracao"])
                sus2 = pausas_intrapalavra(_pcm_voz(novo), p2, pausa_min)
                if len(sus2) < len(sus) or (len(sus2) == len(sus) and (t2 or 0) > (taxa or 0)):
                    novo.replace(mp3)
                    palavras, taxa, extra, dur = p2, t2, ex2, duracao(mp3)
                    if t2 is not None:
                        extra["casamento"] = round(t2, 3)
                    sus = sus2
                else:
                    novo.unlink(missing_ok=True)
            if sus:
                # regen não resolveu (ou provedor sem regen) → correção cirúrgica, grátis
                palavras, dur = excisar_pausas(mp3, palavras, sus, dur)
                avisos.append(f"{c['id']}: stutter em {', '.join(sorted({s['palavra'] for s in sus}))} "
                              f"corrigido na edição (pausa intra-palavra encurtada)")
            frags = fragmentos_borda(_pcm_voz(mp3), palavras, duracao(mp3))
            if frags:
                silenciar_trechos(mp3, frags)
                dur = duracao(mp3)
                avisos.append(f"{c['id']}: {len(frags)} fragmento(s) de voz na borda do áudio "
                              f"(fonema vazado do stitching) — silenciados")
        salvar_json(meta_p, {"hash": h, "texto": c["narracao"], "duracao": dur, "provedor": prov,
                             "palavras": palavras, **extra})
        log(f"  {c['id']}: {dur:.1f}s" + (f"  casamento {extra['casamento']:.0%}" if "casamento" in extra else ""))

    soma = sum(ler_json(pasta / f"{c['id']}.json", {}).get("duracao", 0) for c in cenas)
    if prov in LOCAIS:
        log(f"Narração pronta: {int(soma // 60)}min{int(soma % 60):02d}s de áudio. Voz local ({prov}): "
            f"{t_local / 60:.1f} min de {'GPU' if prov == 'chatterbox' else 'CPU'} agora, sem custo por caractere")
    else:
        preco = config().get("custos", {}).get("voz_por_milhao_caracteres", 40)
        log(f"Narração pronta: {int(soma // 60)}min{int(soma % 60):02d}s de áudio. "
            f"Caracteres enviados agora: {total_chars} (~US$ {total_chars * preco / 1e6:.2f})")
    for av in avisos:
        log(f"  AVISO {av}")


if __name__ == "__main__":
    main()
