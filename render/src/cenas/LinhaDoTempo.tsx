import React from 'react';
import { AbsoluteFill, interpolate, useCurrentFrame } from 'remotion';
import { Fundo, quadro, tempoDe, Textura } from '../comp/Base';
import { Coreografia } from '../comp/Movimento';
import { dataCurta } from '../comp/i18n';
import { alfa, clamp, cor, ease, fonte, q, rng, TEMPO } from '../comp/tokens';
import type { PropsCena } from '../tipos';

type Evento = { data: string; rotulo: string; ancora?: string };

/** "1919-01-15" → "15 jan. 1919" (pt) / "Jan. 15 1919" (en); "1919-01" → "jan. 1919"; texto livre passa direto. */
const exibir = (s: string): { ano: string; resto: string } => {
  const m = String(s).match(/^(\d{3,4})-(\d{1,2})(?:-(\d{1,2}))?$/);
  if (!m) return { ano: s, resto: '' };
  return { ano: m[1], resto: dataCurta(m[3] ? Number(m[3]) : null, Number(m[2])) };
};

/** "1915", "1919-01-15", "jan 1919" → ano fracionário (escala proporcional ao tempo real). */
const anoDe = (s: string): number => {
  const m = String(s).match(/(\d{3,4})(?:-(\d{1,2}))?(?:-(\d{1,2}))?/);
  if (!m) return 0;
  return Number(m[1]) + (m[2] ? (Number(m[2]) - 1) / 12 : 0) + (m[3] ? Number(m[3]) / 365 : 0);
};

/**
 * Linha do tempo. Horizontal até 6 eventos; com mais, a câmera percorre a linha. Posições proporcionais
 * às datas reais (com distância mínima para não encavalar). Cada evento acende quando sua âncora é dita;
 * o evento "atual" fica em destaque e os anteriores esmaecem.
 * v3: régua com marcas de ano (maiores a cada 5/10), barra de progresso que AVANÇA de um evento ao outro
 * com ponta luminosa, marcadores em anel que se preenchem, haste ligando marcador ao texto, ano em serifa
 * grande + dia/mês em versalete, rótulo que sobe de trás de máscara. Base "antiga" ganha papel e fibra.
 */
export const LinhaDoTempo: React.FC<{ p: PropsCena }> = ({ p }) => {
  const f = useCurrentFrame();
  const d = p.dados;
  const r = rng(p.seed);
  const W = p.largura;
  const H = p.altura;
  const u = H / 1080;
  const evs: Evento[] = d.eventos ?? [];
  const papel = d.base === 'antiga';
  const corTexto = papel ? '#2c241a' : cor.texto;
  const corSub = papel ? '#6b5d48' : cor.texto_suave;
  const corTrilho = papel ? 'rgba(60,45,25,0.35)' : alfa(cor.texto, 0.18);
  const corMarca = papel ? 'rgba(60,45,25,0.55)' : alfa(cor.texto, 0.35);
  const anos = evs.map((e) => anoDe(e.data));
  const a0 = Math.min(...anos);
  const a1 = Math.max(...anos);
  const longa = evs.length > 6;
  const comprimento = longa ? W * 0.32 * evs.length : W * 0.74;
  // proporcional, com espaçamento mínimo
  const minGap = comprimento / (evs.length * 1.8);
  const xs: number[] = [];
  anos.forEach((a, i) => {
    const prop = a1 > a0 ? ((a - a0) / (a1 - a0)) * comprimento : (i / Math.max(1, evs.length - 1)) * comprimento;
    xs.push(i === 0 ? prop : Math.max(prop, xs[i - 1] + minGap));
  });
  const escala = xs[xs.length - 1] > comprimento ? comprimento / xs[xs.length - 1] : 1;
  const X = xs.map((x) => x * escala);
  // v4: cada evento acende quando é DITO (âncora → ano → rótulo), procurando sempre depois do anterior;
  // tempos monotônicos com intervalo mínimo (nunca dois eventos no mesmo quadro)
  const gapMin = q(TEMPO.entradaCurta, p.fps);
  const tEv: number[] = [];
  let depoisSeg = -Infinity;
  evs.forEach((e, i) => {
    const seg = tempoDe(p.palavras, [e.ancora, exibir(e.data).ano, e.rotulo], -1, depoisSeg);
    const t = quadro(p, seg >= 0 ? seg : 0.4 + i * 0.8) - q(TEMPO.antecipacao, p.fps);
    const minimo = i === 0 ? p.alca_antes + q(TEMPO.atrasoInicial, p.fps) : tEv[i - 1] + gapMin;
    tEv.push(Math.max(minimo, t));
    if (seg >= 0) depoisSeg = seg + 0.05;
  });
  const atual = tEv.reduce((acc, t, i) => (f >= t ? i : acc), -1);
  const yLinha = H * (0.54 + (r() - 0.5) * 0.04);
  const x0 = W * 0.13;
  // câmera: em linha longa, mantém o evento atual a ~40% da tela
  const alvoCam = longa && atual >= 0 ? Math.max(0, X[atual] - W * 0.4 + x0) : 0;
  const camPrev = longa ? Math.max(0, (X[Math.max(0, atual - 1)] ?? 0) - W * 0.4 + x0) : 0;
  const kCam = atual >= 0 ? interpolate(f, [tEv[atual], tEv[atual] + q(TEMPO.entradaLonga, p.fps)], [0, 1], { ...clamp, easing: ease.padrao }) : 0;
  const cam = camPrev + (alvoCam - camPrev) * kCam;
  const kLinha = interpolate(f, [p.alca_antes, p.alca_antes + q(TEMPO.entradaLonga, p.fps)], [0, 1], { ...clamp, easing: ease.padrao });
  // progresso viaja do evento anterior ao atual (não salta)
  const kProg = atual >= 0 ? interpolate(f, [tEv[atual] - q(TEMPO.atrasoInicial, p.fps), tEv[atual] + q(TEMPO.entradaCurta, p.fps)], [0, 1], { ...clamp, easing: ease.padrao }) : 0;
  const progresso = atual >= 0 ? (X[atual - 1] ?? 0) + (X[atual] - (X[atual - 1] ?? 0)) * kProg : 0;

  // régua: uma marca por ano (se couber), maiores a cada 5 e 10
  const span = a1 - a0;
  const passo = span > 120 ? 10 : span > 40 ? 5 : 1;
  const marcas: { x: number; ano: number; nivel: number }[] = [];
  if (span > 0 && escala === 1 && !xs.some((x, i) => i > 0 && Math.abs(x - ((anos[i] - a0) / span) * comprimento) > 1)) {
    for (let a = Math.ceil(a0 / passo) * passo; a <= a1 + 0.001; a += passo) {
      marcas.push({ x: ((a - a0) / span) * comprimento, ano: a, nivel: a % 10 === 0 ? 2 : a % 5 === 0 ? 1 : 0 });
    }
  }
  const trilho = comprimento + W * 0.04;

  return (
    <AbsoluteFill>
      <Fundo imagem={papel ? null : p.fundo} papel={papel} escurecer={0.86} />
      <Coreografia p={p} cx={W * 0.4} cy={yLinha} reenq={longa ? 'recua' : undefined} intensidade={0.6}>
      <div style={{ position: 'absolute', left: x0 - cam, top: 0, width: comprimento + W, height: H }}>
        {/* trilho */}
        <div style={{ position: 'absolute', left: -W * 0.02, top: yLinha - 1 * u, height: Math.max(2, 2 * u), width: trilho * kLinha, background: corTrilho }} />
        {/* régua */}
        {marcas.map((m, i) => {
          const km = interpolate(f, [p.alca_antes + (m.x / comprimento) * 24, p.alca_antes + (m.x / comprimento) * 24 + 8], [0, 1], clamp);
          const alt = (m.nivel === 2 ? 22 : m.nivel === 1 ? 14 : 8) * u;
          return (
            <React.Fragment key={i}>
              <div style={{ position: 'absolute', left: m.x, top: yLinha + 6 * u, width: 1, height: alt * km, background: corMarca }} />
              {m.nivel === 2 && passo < 10 ? (
                <div style={{ position: 'absolute', left: m.x + 6 * u, top: yLinha + 12 * u, fontFamily: fonte.rotulo, fontSize: 16 * u, color: corSub, opacity: km * 0.8, fontVariantNumeric: 'tabular-nums' }}>
                  {m.ano}
                </div>
              ) : null}
            </React.Fragment>
          );
        })}
        {/* progresso com ponta luminosa */}
        <div
          style={{
            position: 'absolute', left: 0, top: yLinha - 2.5 * u, height: 5 * u, width: progresso,
            background: `linear-gradient(90deg, ${alfa(cor.destaque, 0.5)}, ${cor.destaque})`,
          }}
        />
        {atual >= 0 && kProg < 1 ? (
          <div
            style={{
              position: 'absolute', left: progresso - 14 * u, top: yLinha - 14 * u, width: 28 * u, height: 28 * u, borderRadius: 99,
              background: `radial-gradient(circle, ${alfa(cor.destaque_claro, 0.9)} 0%, ${alfa(cor.destaque, 0.5)} 35%, ${alfa(cor.destaque, 0)} 70%)`,
            }}
          />
        ) : null}
        {evs.map((e, i) => {
          const k = interpolate(f, [tEv[i], tEv[i] + q(TEMPO.entrada, p.fps)], [0, 1], { ...clamp, easing: ease.saida });
          const ativo = i === atual;
          const passado = i < atual;
          const acima = i % 2 === 0;
          const aceso = f >= tEv[i];
          const dir = x0 + X[i] - cam > W * 0.66;
          const haste = 54 * u;
          const ds = exibir(e.data);
          const tamAno = (ativo ? 96 : 72) * u;
          const op = 0.3 + 0.7 * (aceso ? (passado ? 0.6 : 1) : 0);
          return (
            <div key={i} style={{ position: 'absolute', left: X[i], top: yLinha }}>
              {/* marcador: anel que se preenche */}
              <div
                style={{
                  position: 'absolute', left: -12 * u, top: -12 * u, width: 24 * u, height: 24 * u, borderRadius: 99,
                  border: `${Math.max(2, 3 * u)}px solid ${aceso ? cor.destaque : corMarca}`,
                  background: papel ? cor.papel : cor.tinta, boxSizing: 'border-box',
                  transform: `scale(${1 + (ativo ? 0.25 : 0) * k})`,
                  boxShadow: ativo && !papel ? `0 0 ${24 * u}px ${alfa(cor.destaque, 0.55 * k)}` : 'none',
                }}
              >
                <div style={{ position: 'absolute', inset: 3 * u, borderRadius: 99, background: cor.destaque, transform: `scale(${k})` }} />
              </div>
              {/* haste */}
              <div
                style={{
                  position: 'absolute', left: -0.5, width: 1, [acima ? 'bottom' : 'top']: 16 * u, height: haste * k,
                  background: aceso ? (papel ? 'rgba(44,36,26,0.5)' : alfa(cor.texto, 0.5)) : 'transparent',
                }}
              />
              <div
                style={{
                  position: 'absolute', width: W * 0.28, [acima ? 'bottom' : 'top']: haste + 28 * u,
                  ...(dir ? { right: -6 * u, textAlign: 'right' as const } : { left: -6 * u }),
                  opacity: op,
                  transform: `translateY(${(1 - k) * (acima ? 18 : -18) * u}px)`,
                }}
              >
                {ds.resto ? (
                  <div style={{ fontFamily: fonte.rotulo, fontWeight: 600, fontSize: 22 * u, letterSpacing: '0.24em', textTransform: 'uppercase', color: aceso ? cor.destaque : corSub, marginBottom: 6 * u }}>
                    {ds.resto}
                  </div>
                ) : null}
                <div
                  style={{
                    fontFamily: fonte.titulo, fontWeight: 700, fontSize: tamAno, color: ativo ? corTexto : corSub, lineHeight: 0.95,
                    letterSpacing: '-0.02em', fontVariantNumeric: 'lining-nums',
                  }}
                >
                  {ds.ano}
                </div>
                <div style={{ overflow: 'hidden', marginTop: 12 * u }}>
                  <div
                    style={{
                      fontFamily: fonte.titulo, fontStyle: 'italic', fontWeight: 400, fontSize: 34 * u, lineHeight: 1.2, color: corTexto,
                      transform: `translateY(${(1 - k) * 110}%)`,
                    }}
                  >
                    {e.rotulo}
                  </div>
                </div>
              </div>
            </div>
          );
        })}
      </div>
      </Coreografia>
      <Textura papel={papel} />
    </AbsoluteFill>
  );
};
