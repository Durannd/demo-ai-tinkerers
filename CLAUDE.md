# Canal Harness — DEMO enxuta

Este repositório é uma **demonstração**: transforma um pedido curto ("faça um vídeo de 40 segundos sobre X") em um vídeo de rascunho 720p com narração, cenas animadas (Remotion), legendas `.srt` e descrição. O Claude Code escreve o storyboard (JSON); os scripts fazem o resto.

Fale com o usuário em **português do Brasil**. Seja breve: estamos ao vivo, diante de uma plateia.

## Fluxo exato (sempre nesta ordem, sempre a partir da raiz do repo)

Use sempre `PYTHONUTF8=1` e o Python do venv (`.venv/Scripts/python`). No PowerShell: `$env:PYTHONUTF8=1; .venv\Scripts\python pipeline\...`. No Git Bash: `PYTHONUTF8=1 .venv/Scripts/python pipeline/...`.

1. Escreva `episodios/<slug>/storyboard.json` (slug em minúsculas com hífens, ex.: `por-que-o-ceu-e-azul`).
2. `python pipeline/validar.py <slug>` — corrija todos os ERROS e rode de novo até dar `OK`.
3. `python pipeline/narrar.py <slug>` — voz Gemini TTS ao vivo (1 requisição por cena) + alinhamento whisper. Informe a duração real que ele imprime.
4. `python pipeline/montar.py <slug> --rascunho --sem-shorts` — renderiza as cenas e monta o vídeo.
5. **Mostre o resultado**: diga o caminho completo do MP4 (`episodios/<slug>/final/<slug>_rascunho.mp4`), a duração e o tempo gasto, e abra o arquivo se o usuário pedir.

Se o usuário pedir uma mudança (trocar um número, um texto, uma cena), edite **só aquele trecho** do `storyboard.json` e repita os passos 2–4: o cache por hash re-renderiza apenas as cenas que mudaram (narração: só as cenas cuja fala mudou). Depois diga quais cenas foram re-renderizadas (o `montar` imprime `remotion: ok cXX`).

Não rode nada fora desse fluxo: nada de `buscar_midia`, IA, shorts, thumbnail, `npm`, instalação de pacotes. Se algo quebrar, mostre o erro e corrija o storyboard; não mexa em `pipeline/`, `render/` nem `config.json`.

## O que pode e o que não pode

**Tipos de cena permitidos** (`visual.tipo`) — todos gráficos, sem mídia externa e sem internet. O schema recusa qualquer outro:

| tipo | campos (dentro de `visual.<tipo>`) |
|---|---|
| `numero` | `valor` (número, obrigatório), `unidade`, `prefixo`, `casas` (0–3), `de`, `ancora`, `referencia: {valor, rotulo}` |
| `comparacao` | `modo: "numeros"`, `a` e `b`: `{rotulo, valor, unidade, ancora}` |
| `icones` | `modo`: `fileira` (2–6 `itens` `{icone, rotulo<=20 car., em}`) \| `mosaico` (`icone` + `em`) \| `fichas` (1–4 `{texto<=8 car., numero<=8, legenda<=30, em}`); `titulo<=40`. **Não aceita campos extras.** Ícones válidos: raio, interrogacao, exclamacao, x, dinheiro, radiacao, atomo, alerta, coracao, cruz, seta, caveira, olho, relogio, chave, gota, fogo, engrenagem, lupa, estrela, check, pessoa |
| `citacao` | `texto` (use `**palavra**` para destacar), `autor`, `contexto` |
| `capitulo` | `titulo` (obrigatório), `numero`, `subtitulo` |
| `linha_do_tempo` | `eventos` (mínimo 2): `{data: "1985" ou "1985-03", rotulo, ancora}` — a data TEM de conter o ano |
| `cartela` | `visual.cartela_texto` (texto curto; use no máximo 1) |

**Proibido nesta demo:** `mapa` (geocodifica na internet), `stock_*`, `arquivo_historico`, `documento`, `ia_*`, `domino`, `colagem`, `marca`, `congelar`, `cta`, `shorts`, música (`meta.musica`). Não pesquise na web e não baixe nada.

**Limites:** vídeo de **30 a 45 segundos**, **6 a 8 cenas**, cada cena com **1 ou 2 frases curtas** (8 a 20 palavras). **Orçamento de palavras: no máximo 90 palavras no total** (o `validar` não impõe isso; ele estima ~140 palavras/min, então 90 palavras ≈ 40 s com as pausas — confira a 'Duração estimada' e corte se passar de 0min45s). Pouca voz de propósito (cada cena é uma chamada paga/limitada ao Gemini). Misture pelo menos 3 tipos diferentes e não repita o mesmo tipo em cenas seguidas.

## Conteúdo: fatos

- O assunto vem do usuário. **Sem pesquisa web.** Use só fatos básicos, estáveis e que você tem certeza. **Nunca invente número, data, nome ou citação.** Na dúvida, escolha outro ângulo ou pergunte.
- É uma demonstração: em `meta.descricao` deixe claro que é um vídeo de demonstração. `fontes` é obrigatório (mínimo 1): use URLs reais e conhecidas (ex.: Wikipédia do tema), com `afirmacao` e `cenas`.
- Narração em português, para o ouvido: frases curtas, **números por extenso** ("sessenta e quatro", "zero vírgula um"), sem siglas difíceis de pronunciar, sem emojis nem markdown.

## Âncoras

`ancora`, `em` e `**destaque**` ligam o visual a uma palavra da narração. A âncora precisa ser uma palavra que **existe na narração da mesma cena**, escrita igual (acentos e maiúsculas não importam; só a 1ª palavra conta). Número em dígito na tela ("64") ≠ palavra na fala ("sessenta"): a âncora é a palavra falada.

## Storyboard mínimo válido

```json
{
  "versao": 2,
  "meta": { "slug": "exemplo", "titulo": "Título do vídeo", "canal": "demo", "idioma": "pt-BR",
            "descricao": "Vídeo de demonstração sobre ...", "tags": ["demonstração"] },
  "cenas": [
    { "id": "c01", "bloco": "gancho", "narracao": "Uma pergunta curta que prende a atenção.",
      "visual": { "tipo": "citacao", "citacao": { "texto": "Por que isso **acontece**?" } } },
    { "id": "c02", "bloco": "desenvolvimento", "narracao": "O Sol tem cerca de quatro mil e seiscentos milhões de anos.",
      "visual": { "tipo": "numero", "numero": { "valor": 4600, "unidade": "milhões de anos", "ancora": "quatro" } } },
    { "id": "c03", "bloco": "conclusao", "narracao": "Dez é maior que dois, mas o computador prefere o dois.",
      "visual": { "tipo": "comparacao", "comparacao": { "modo": "numeros",
        "a": { "rotulo": "decimal", "valor": 10, "ancora": "Dez" },
        "b": { "rotulo": "binário", "valor": 2, "ancora": "dois" } } } }
  ],
  "fontes": [ { "afirmacao": "Fato resumido", "url": "https://pt.wikipedia.org/wiki/...", "cenas": ["c02"] } ]
}
```

Campos obrigatórios: `meta.slug`, `meta.titulo`, `meta.idioma` (`"pt-BR"`), `meta.canal` (`"demo"`), cada cena com `id` (`c01`, `c02`... únicos), `narracao`, `visual`; e `fontes`. `bloco` é livre (gancho, contexto, desenvolvimento, conclusao). Há um exemplo completo e válido em `episodios/demo-reserva/storyboard.json`.

## Como ler o `validar.py`

- `ERRO` bloqueia: corrija. `schema: cenas/3/visual/tipo: 'mapa' is not one of [...]` = tipo proibido; `schema: ...: 'fontes' is a required property` = faltou `fontes`; `Additional properties are not allowed ('x' was unexpected)` = campo que não existe naquele tipo (apague); `is too long` = texto acima do limite de caracteres do campo; `evento '...' sem ano na data`; `âncora ... não está na narração` em `icones`/`linha_do_tempo`/`numero` é AVISO, mas corrija mesmo assim.
- `AVISO` de variedade (mesmo tipo seguido, "repete o plano"): troque o tipo de uma das cenas. Avisos de "cena curta/longa": ajuste o tamanho da narração só se estiver muito fora de 2,5–16 s.
- Depois do `narrar`, `AVISO cXX: só N% das palavras casaram`: significa que a voz leu algo diferente do texto; peça ao usuário para ouvir `episodios/<slug>/audio/cXX.mp3` e, se estiver errado, apague `audio/cXX.*` e rode o `narrar` de novo (gasta 1 requisição).
- Erro `429`/`RESOURCE_EXHAUSTED` no `narrar` = cota do Gemini TTS acabou. Pare e avise o usuário (plano B: `episodios/demo-reserva`, que tem a narração em cache).

## Ajustes de máquina (config.json → render)

Esta máquina é fraca (sem GPU dedicada): `render.gpu = "cpu"` (libx264), `render.processos = 2`, `render.concorrencia_remotion = 2`, vídeo 720p. Numa máquina forte, suba `concorrencia_remotion` (8–12) e ponha `processos` como `null` (automático). Não altere isso durante a demo.
