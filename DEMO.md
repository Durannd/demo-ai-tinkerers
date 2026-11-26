# Roteiro da demonstração

Objetivo: abrir o Claude Code neste repo, pedir UM vídeo em linguagem natural e mostrar o pipeline inteiro (storyboard → validação → voz → render → MP4), e depois provar o cache mudando um número.

## Antes (em casa, com internet)

1. `powershell -ExecutionPolicy Bypass -File scripts\preparar.ps1` (venv, pip, npm, Chrome do Remotion, modelo whisper ~460 MB).
2. Edite `.env` e coloque `GEMINI_API_KEY=...`. A cota gratuita do Gemini TTS é pequena (~100 requisições/dia por modelo; cada cena narrada = 1 requisição, e cena com baixo "casamento" é regerada: conte ~10–15 por vídeo). Não faça ensaios em excesso no dia.
3. `powershell -ExecutionPolicy Bypass -File scripts\checar.ps1 -Api` deve terminar em "TUDO PRONTO".
4. **Meça no notebook**: rode o fluxo completo uma vez com um assunto de teste (`zz-ensaio`, fica fora do git). Anote os tempos de narrar e montar. **Aquecer o cache:** esse primeiro run também aquece disco, Chrome e modelo.
5. Teste o plano B: `.venv\Scripts\python pipeline\montar.py demo-reserva --rascunho --sem-shorts` (offline; a narração está em cache).
6. No dia: internet estável, notificações desligadas, terminal com fonte grande, `claude` aberto na raiz do repo, notebook na tomada (modo desempenho).

## Assunto padrão

"Por que 0,1 + 0,2 não dá 0,3 no computador" (o storyboard pronto está em `episodios/demo-reserva`). Fato verificado: em ponto flutuante binário IEEE 754 (double, 64 bits), `0.1 + 0.2` resulta em `0.30000000000000004`; o 0,1 vira dízima em binário.

## Passo a passo ao vivo

| # | Ação | O que falar | Tempo esperado* |
|---|---|---|---|
| 1 | Prompt: `Faça um vídeo de 40 segundos sobre por que 0,1 + 0,2 não dá 0,3 no computador. Valide, narre e monte o rascunho.` | "O Claude lê o CLAUDE.md: só sabe usar estes tipos de cena e este fluxo." | 30–90 s escrevendo o storyboard |
| 2 | `validar` | "O schema e as regras barram erros: âncora que não existe, tipo proibido." Se der erro, mostre o Claude corrigindo. | < 1 s |
| 3 | `narrar` | "Voz Gemini ao vivo, uma chamada por cena; o whisper local marca o tempo de cada palavra." | ~1 min aqui; esperar 1,5–2,5 min |
| 4 | `montar --rascunho --sem-shorts` | "Cada cena é um componente React renderizado pelo Remotion; o FFmpeg junta tudo." Aproveite a espera para mostrar `storyboard.json` e `config.json → render`. | ~2 min aqui; esperar 3–6 min |
| 5 | Mostrar o MP4 e o `.srt` | Caminho impresso no fim. | — |
| 6 | Prompt de correção: `Troque o número da cena 3 para 32 bits.` (ou outro número/texto) | "Só a cena mudada é refeita: o cache é por hash." Mostre `remotion: 1 cena(s) para renderizar`. | ~0,5–1,5 min |
| 7 | Outro prompt: `Troque a cena 2 por um capítulo chamado "Binário".` | Mostra de novo só 1 cena. | idem |

*Medido nesta máquina de desenvolvimento (Ryzen 5 4500 6c/12t, 32 GB); a estimativa para o notebook é um chute de 1,5x a 2,5x, a confirmar medindo.

Dica: se a narração mudar de uma cena, ela é regerada (1 requisição). Para provar o cache de render sem gastar voz, mude só número/rótulo, não a fala.

## Plano B / C

- **B (sem Gemini ou sem internet):** `Use o episódio demo-reserva: rode validar e montar --rascunho --sem-shorts.` A narração está em `episodios/demo-reserva/audio/` e é reaproveitada. Para forçar render novo, apague `episodios/demo-reserva/build/`.
- **B2 (Gemini ok, Claude Code lento):** cole um storyboard salvo em `episodios/<slug>/storyboard.json` e rode os passos 2–4 na mão.
- **C (tudo falhou):** abra o vídeo pronto `episodios/demo-reserva/final/demo-reserva_rascunho.mp4` e, como reserva final, uma gravação de tela do ensaio feito no notebook (grave no ensaio).

## Se algo der errado

- `429`/`RESOURCE_EXHAUSTED` no narrar: cota do TTS acabou, vá ao plano B.
- Remotion travado/lento: confira `render.concorrencia_remotion` (2) e `render.gl_remotion` (`swiftshader`) em `config.json`; em máquina forte suba a concorrência para 8–12 e ponha `processos: null`.
- Aviso "só N% das palavras casaram": ouça `audio/cXX.mp3`; se estiver errado, apague `audio/cXX.*` e rode `narrar` de novo.
