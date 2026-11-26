# Efeitos sonoros

Categorias: whoosh, impacto, riser, papel, tique (e ambiente). Para cada uma, o `pipeline/som.py` usa a primeira fonte que tiver arquivos:

1. **Seus arquivos** em `assets/sfx/<categoria>/` (ex.: `assets/sfx/whoosh/*.wav`).
2. **Freesound** (cache em `assets/sfx/_freesound/<categoria>/` + `manifesto.json` com id, nome, autor, licença e página).
3. **Sintetizados pelo FFmpeg** em `_gerados/` — sem licença a registrar.

## Freesound

Precisa de `FREESOUND_API_KEY` no `.env` (crie em https://freesound.org/apiv2/apply — conta grátis; use o campo "Client secret/Api key"). Sem chave e sem cache, nada muda: tudo sintetizado.

- Busca só **CC0** e **CC BY** (`license:("Creative Commons 0" OR "Attribution")`) e confere a licença de cada resultado de novo; **nunca** BY-NC nem Sampling+.
- Filtra por duração, ordena por avaliação/downloads (CC0 ganha no empate, para reduzir créditos) e pega 1 som por autor primeiro (variedade). Baixa o preview HQ (mp3, sem OAuth), apara silêncio nas pontas, corta no máximo da categoria e normaliza loudness (pico ≤ -3 dB, igual aos sintetizados).
- O cache é estável: uma vez baixado, não busca de novo. Variedade entre episódios vem da seed da cena.
- Sons **CC BY** entram sozinhos na descrição ("Efeitos sonoros (freesound.org):") e ficam nos eventos de `build/sfx.json` (campo `credito`). Não apague o `manifesto.json`: é ele que liga o arquivo ao autor.

```
python pipeline/som.py --listar                                  # de onde vem cada categoria + licenças
python pipeline/som.py --freesound                               # baixa o que faltar
python pipeline/som.py --freesound --atualizar --categorias riser # refaz a busca de uma categoria
```

Consulta/duração por categoria: `config.json → som.freesound.buscas` (ex.: `{"impacto": {"busca": "deep boom hit", "dur": [0.8, 4]}}`); `som.freesound.ativo: false` desliga; `por_categoria` = quantos sons guardar. Não gostou de um som? Apague o `.wav` e a entrada no manifesto (ou rode `--atualizar`).

## Arquivos próprios

Licenças aceitas: **CC0**, **Pixabay Content License** (pixabay.com/sound-effects), **Sonniss GDC Game Audio Bundle** (royalty-free, sem atribuição). Recusado: CC BY-NC, "free for personal use", ou sem licença clara. Arquivos próprios CC BY **não** entram sozinhos na descrição — prefira o cache do Freesound para esses.
Anote a origem de cada arquivo em `assets/sfx/<categoria>/ORIGEM.txt`.
