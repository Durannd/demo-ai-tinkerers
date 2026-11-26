import React from 'react';
import { AbsoluteFill, interpolate, useCurrentFrame } from 'remotion';
import { quadro, tempoDe, Textura } from '../comp/Base';
import { definirTextura, Ficha, FiltroTermico, ICONES, Icone, Riscos, Surge, Vazamento } from '../comp/Elementos';
import type { FichaDados } from '../comp/Elementos';
import { Entrada, Saida } from '../comp/Movimento';
import type { TipoEntrada } from '../comp/Movimento';
import { alfa, clamp, cor, ease, fonte, q, rng, T, TEMPO } from '../comp/tokens';
import type { PropsCena } from '../tipos';

type Item = { icone: string; rotulo?: string; em?: string; termico?: boolean; vira?: string; vira_em?: string };

/**
 * Cena só de elementos gráficos (sem mídia), na linguagem da colagem editorial:
 *  fileira  2–6 ícones sobre um fio, cada um "estala" quando a narração o nomeia (com rótulo embaixo);
 *  mosaico  um ícone repetido em grade até encher a tela ("milhões de..."); uma fração acende em
 *           textura térmica na palavra `em` (proporção: destaque = 0,1 → 10% das células);
 *  fichas   1–4 fichas de dado (estilo tabela periódica) lado a lado, cada uma na sua palavra.
 */
export const Icones: React.FC<{ p: PropsCena }> = ({ p }) => {
  const f = useCurrentFrame();
  const d = p.dados;
  const W = p.largura;
  const H = p.altura;
  const u = H / 1080;
  const C = T.colagem;
  const claro = d.base === 'clara';
  const fundo = claro ? C.fundo_claro : C.fundo_escuro;
  const corLinha = claro ? C.tinta_clara : C.linha;
  const corTexto = claro ? C.tinta_clara : cor.texto;
  const corNome = claro ? cor.destaque : C.nome;
  const ini = p.alca_antes + q(TEMPO.atrasoInicial, p.fps);
  const corpoS = p.corpo / p.fps;
  const ant = q(TEMPO.antecipacao, p.fps);
  const modo: string = d.modo ?? 'fileira';
  definirTextura(p.seed, d.textura);

  const titulo = d.titulo ? (
    <Surge inicio={Math.max(ini, quadro(p, tempoDe(p.palavras, [d.titulo], 0.2)) - ant)} dur={16} estilo={{ position: 'absolute', left: W * 0.06, top: H * 0.11, width: W * 0.88 }}>
      <div style={{ fontFamily: fonte.rotulo, fontWeight: 800, fontSize: 64 * u, lineHeight: 1, letterSpacing: '-0.02em', textTransform: 'uppercase', color: corTexto }}>{d.titulo}</div>
    </Surge>
  ) : null;

  let conteudo: React.ReactNode = null;

  if (modo === 'fileira') {
    const itens: Item[] = (d.itens ?? []).slice(0, 6);
    const n = Math.max(1, itens.length);
    const y = H * 0.52;
    const larg = Math.min(W * 0.8, n * W * 0.19);
    const x0 = (W - larg) / 2;
    const passo = larg / n;
    // sem âncora: distribui no meio da fala
    let ultimo = p.alca_antes - q(4, p.fps);
    const tempos = itens.map((it, i) => {
      const padrao = corpoS * (0.15 + (0.7 * i) / n);
      const t = Math.max(ini, ultimo + q(4, p.fps), quadro(p, tempoDe(p.palavras, [it.em, it.rotulo], padrao, (ultimo - p.alca_antes) / p.fps)) - ant);
      ultimo = t;
      return t;
    });
    const kFio = interpolate(f, [ini - 4, ini + q(16, p.fps)], [0, 1], { ...clamp, easing: ease.saida });
    const tam = Math.min(passo * 0.5, H * 0.17);
    const lf = larg + 60 * u;
    // a fileira escorrega no sentido da leitura; depois do último ícone, a câmera avança sobre ele
    const deriva = -interpolate(f, [0, p.frames], [0, 1], clamp) * W * 0.05;
    const tUlt = (tempos[tempos.length - 1] ?? ini) + q(14, p.fps);
    const kFim = interpolate(f, [tUlt, tUlt + q(26, p.fps)], [0, 1], { ...clamp, easing: ease.camera });
    const xUlt = x0 + passo * (n - 0.5);
    conteudo = (
      <div style={{ position: 'absolute', inset: 0, transform: `translateX(${deriva}px) scale(${1 + 0.22 * kFim})`, transformOrigin: `${xUlt}px ${y}px` }}>
        <div style={{ position: 'absolute', left: W / 2 - (lf / 2) * kFio, top: y + tam * 0.85, width: lf * kFio, height: Math.max(1, 1.6 * u), background: alfa(corLinha, 0.55) }} />
        {itens.map((it, i) => {
          const cx = x0 + passo * (i + 0.5);
          // o ícone cai de cima ou sobe de baixo (alternado) e só então estala no lugar
          const kv = interpolate(f, [tempos[i] - q(8, p.fps), tempos[i]], [0, 1], { ...clamp, easing: ease.saida });
          const dy = (1 - kv) * H * 0.35 * (i % 2 ? 1 : -1);
          return (
            <React.Fragment key={i}>
              <div style={{ position: 'absolute', inset: 0, transform: `translateY(${dy}px)`, opacity: f >= tempos[i] - q(8, p.fps) ? 1 : 0 }}>
                <Icone
                  nome={it.icone} x={cx} y={y} tam={tam} inicio={tempos[i] - q(6, p.fps)} seed={p.seed + i * 7} termico={it.termico ?? true} cor={corNome} u={u}
                  vira={it.vira} tVira={it.vira ? Math.max(tempos[i] + q(12, p.fps), quadro(p, tempoDe(p.palavras, [it.vira_em], corpoS * 0.8)) - ant) : undefined}
                />
              </div>
              {it.rotulo ? (
                <Surge inicio={tempos[i] + 4} estilo={{ position: 'absolute', left: cx - passo / 2, width: passo, top: y + tam * 0.85 + 18 * u, textAlign: 'center' }}>
                  <div style={{ fontFamily: fonte.rotulo, fontWeight: 700, fontSize: 26 * u, letterSpacing: '0.12em', textTransform: 'uppercase', color: corTexto }}>{it.rotulo}</div>
                </Surge>
              ) : null}
            </React.Fragment>
          );
        })}
      </div>
    );
  } else if (modo === 'mosaico') {
    const forma = ICONES[d.icone] ?? ICONES.pessoa;
    const formaB = d.vira ? ICONES[d.vira] ?? forma : null;
    const tVira = formaB ? quadro(p, tempoDe(p.palavras, [d.vira_em], corpoS * 0.75)) - ant : 1e7;
    const cel = (d.celula ?? 64) * u;
    const cols = Math.ceil(W / cel) + 1;
    const lins = Math.ceil(H / cel) + 1;
    const r = rng(p.seed);
    const frac: number = Math.min(1, Math.max(0, d.destaque ?? 0.08));
    const tAcende = d.em ? quadro(p, tempoDe(p.palavras, [d.em], corpoS * 0.5)) - ant : ini + q(30, p.fps);
    const onda = q(24, p.fps);
    const comuns: React.ReactNode[] = [];
    const quentes: React.ReactNode[] = [];
    for (let j = 0; j < lins; j++) {
      for (let i = 0; i < cols; i++) {
        const quente = r() < frac;
        // abre na horizontal a partir do centro (como uma fresta que se alarga), linha a linha
        const atraso = (Math.abs(i * cel - W / 2) / (W / 2)) * onda * 0.8 + (Math.abs(j * cel - H / 2) / (H / 2)) * onda * 0.2;
        const k = interpolate(f, [ini + atraso, ini + atraso + 8], [0, 1], { ...clamp, easing: ease.saida });
        if (k <= 0) continue;
        const salto = quente ? interpolate(f, [tAcende, tAcende + 5, tAcende + 12], [1, 1.45, 1], clamp) : 1;
        // metamorfose: cada célula gira no eixo vertical e volta como o outro ícone (onda do centro para fora)
        const atrasoV = (Math.hypot(i * cel - W / 2, j * cel - H / 2) / Math.hypot(W / 2, H / 2)) * q(20, p.fps);
        const kv = formaB ? interpolate(f, [tVira + atrasoV, tVira + atrasoV + 8], [0, 1], clamp) : 0;
        const sx = Math.abs(Math.cos(Math.PI * kv));
        const s = (cel / 100) * 0.62 * k * salto;
        const g = (
          <g key={`${i}-${j}`} transform={`translate(${i * cel + cel / 2 - 50 * s * sx},${j * cel + cel / 2 - 50 * s}) scale(${s * sx} ${s})`}>
            {kv >= 0.5 && formaB ? formaB : forma}
          </g>
        );
        (quente ? quentes : comuns).push(g);
      }
    }
    const kQ = interpolate(f, [tAcende, tAcende + 10], [0, 1], clamp);
    // a grade avança devagar e, quando acende, dá um empurrão
    const zm = 1 + 0.08 * interpolate(f, [0, p.frames], [0, 1], clamp) + 0.06 * interpolate(f, [tAcende, tAcende + q(20, p.fps)], [0, 1], { ...clamp, easing: ease.saida });
    conteudo = (
      <svg width={W} height={H} style={{ position: 'absolute', left: 0, top: 0, transform: `scale(${zm}) rotate(${-2 * interpolate(f, [0, p.frames], [0, 1], clamp)}deg)` }}>
        <defs>
          <mask id="mos-c" maskUnits="userSpaceOnUse" x="0" y="0" width={W} height={H}>
            <rect width={W} height={H} fill="#000" />
            {comuns}
          </mask>
          <mask id="mos-q" maskUnits="userSpaceOnUse" x="0" y="0" width={W} height={H}>
            <rect width={W} height={H} fill="#000" />
            {quentes}
          </mask>
          <FiltroTermico id="mos-t" seed={p.seed} escala={0.004 / u} progresso={Math.max(0, f - tAcende) / 300} />
        </defs>
        <rect width={W} height={H} fill={alfa(corLinha, 0.22)} mask="url(#mos-c)" />
        <rect width={W} height={H} fill={alfa(corLinha, 0.22)} mask="url(#mos-q)" />
        <g mask="url(#mos-q)" opacity={kQ}>
          <rect width={W} height={H} fill="#808080" filter="url(#mos-t)" />
        </g>
      </svg>
    );
  } else if (modo === 'fichas') {
    const fichas: FichaDados[] = (d.fichas ?? []).slice(0, 4);
    const n = Math.max(1, fichas.length);
    const tam = Math.min(H * 0.34, (W * 0.8) / n - 30 * u);
    const gap = tam * 0.06;
    const x0 = (W - (n * tam + (n - 1) * gap)) / 2;
    let ultimo = p.alca_antes - q(5, p.fps);
    const tempos = fichas.map((fi, i) => {
      ultimo = Math.max(ini, ultimo + q(5, p.fps), quadro(p, tempoDe(p.palavras, [fi.em, fi.texto], corpoS * (0.15 + (0.6 * i) / n), (ultimo - p.alca_antes) / p.fps)) - ant);
      return ultimo;
    });
    // depois da última ficha, a câmera avança sobre ela
    const tUlt = tempos[tempos.length - 1] + q(16, p.fps);
    const kFim = interpolate(f, [tUlt, tUlt + q(26, p.fps)], [0, 1], { ...clamp, easing: ease.camera });
    conteudo = (
      <div style={{ position: 'absolute', inset: 0, transform: `scale(${1 + 0.18 * kFim})`, transformOrigin: `${x0 + (n - 0.5) * (tam + gap)}px ${H / 2}px` }}>
        {fichas.map((fi, i) => {
          const t = tempos[i];
          const ents: TipoEntrada[] = ['lateral', 'escala', 'persiana', 'giro'];
          const espalha = (i - (n - 1) / 2) * gap * 3 * interpolate(f, [0, p.frames], [0, 1], clamp);
          const fx = x0 + i * (tam + gap) + espalha * 2;
          return (
            <Entrada
              key={i} tipo={ents[(i + (p.seed % 4)) % 4]} inicio={t} dur={q(16, p.fps)} cx={fx + tam / 2} cy={H / 2} w={tam * 1.1} h={tam * 1.1}
              W={W} H={H} de={i % 2 ? 1 : -1} id={`fi-${p.cena_id}-${i}`}
            >
              <Ficha
                x={fx} y={(H - tam) / 2} tam={tam} inicio={t} seed={p.seed + i * 13} texto={fi.texto} numero={fi.numero}
                cantos={fi.cantos ?? []} legenda={fi.legenda} termico={fi.termico ?? true} corLinha={alfa(corLinha, 0.85)} corTexto={corTexto} corAcento={corNome} u={u}
                vira={fi.vira} tVira={fi.vira ? Math.max(t + q(20, p.fps), quadro(p, tempoDe(p.palavras, [fi.vira_em], corpoS * 0.75)) - ant) : undefined}
              />
            </Entrada>
          );
        })}
      </div>
    );
  }

  return (
    <AbsoluteFill style={{ background: fundo, overflow: 'hidden' }}>
      <Vazamento frames={p.frames} seed={p.seed} claro={claro} />
      <Saida fim={p.alca_antes + p.corpo} cx={W / 2} cy={H / 2} tipo={(['recolhe', 'sobe', 'lado'] as const)[p.seed % 3]}>
        <AbsoluteFill style={{ transform: `scale(${1.05 - 0.05 * interpolate(f, [ini - 4, ini + q(24, p.fps)], [0, 1], { ...clamp, easing: ease.saida }) + 0.07 * interpolate(f, [0, p.frames], [0, 1], clamp)}) translateX(${-interpolate(f, [0, p.frames], [0, 1], clamp) * 30 * u}px)` }}>
          {conteudo}
          {titulo}
        </AbsoluteFill>
      </Saida>
      <Riscos W={W} H={H} seed={p.seed} claro={claro} />
      <Textura vinheta={claro ? 0.35 : 0.8} />
    </AbsoluteFill>
  );
};
