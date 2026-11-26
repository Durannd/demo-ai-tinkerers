import React from 'react';
import { AbsoluteFill, Easing, interpolate, useCurrentFrame } from 'remotion';
import { Fontes } from '../src/comp/Base';
import { alfa, aplicarCanal, cor, ease, fonte, rng } from '../src/comp/tokens';

/**
 * FX dos Shorts (pipeline/fx.py): peças de fundo TRANSPARENTE (ProRes 4444) que o FFmpeg sobrepõe à base 9:16.
 *
 *  gancho   título-gancho cinético do começo: placas que varrem, palavras que "batem", faíscas, sublinhado
 *  cortina  faixa diagonal nas cores do canal que atravessa a tela    ┐
 *  fatias   seis tiras horizontais que fecham de lados alternados     │ COBREM o quadro no meio (q = frames/2):
 *  rasgo    folha de papel rasgado em duas camadas que desce          │ o corte acontece escondido atrás delas
 *  iris     círculo que fecha e reabre                                ┘
 *  raio     riscos de luz + clarão curto (acompanha o whip-pan feito no shorts.pos_edicao) — não cobre
 *  impacto  linhas de velocidade + anel na palavra de ênfase — não cobre
 *
 * Unidade "u": 1 u = 1 px a 1080 de largura (`escala` converte). Tudo é movido pela edição (corte, gancho,
 * ênfase): nada fica pulsando para preencher tempo.
 */
export type PropsShortFx = {
  id: string;
  tipo: 'gancho' | 'cortina' | 'fatias' | 'rasgo' | 'iris' | 'raio' | 'impacto';
  largura: number;
  altura: number;
  fps: number;
  frames: number;
  escala: number;
  seed: number;
  dir?: 1 | -1;
  texto?: string;
  /** gancho: centro x, topo y (u) e largura máxima do texto (u) */
  cx?: number;
  topo?: number;
  larguraTexto?: number;
  idioma?: string;
  tokens?: Record<string, any>;
};

const CL = { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' } as const;
const c01 = (x: number) => Math.max(0, Math.min(1, x));
const eOut = Easing.out(Easing.cubic);
const eIn = Easing.in(Easing.cubic);

/**
 * Posição de uma peça que cobre: −1 (fora, antes) → +1 (fora, depois), num movimento SÓ (lento nas pontas,
 * rápido no meio). Cruza o zero entre os quadros m−1 e m: o corpo da peça tem folga (FOLGA × a tela) para
 * cobrir os dois — o corte fica escondido, mas a tela cheia dura só ~2–3 quadros.
 */
const FOLGA = 1.4;
const inOutQuad = Easing.inOut(Easing.quad);
const travessia = (f: number, N: number) => {
  const m = Math.floor(N / 2);
  return 2 * inOutQuad(c01(0.5 + (f - (m - 0.5)) / (N - 1))) - 1;
};

// ---------------------------------------------------------------- transições que cobrem
const Cortina: React.FC<{ p: PropsShortFx }> = ({ p }) => {
  const f = useCurrentFrame();
  const u = p.escala;
  const D = Math.hypot(p.largura, p.altura) * 1.2;
  const ANG = 14;
  const rad = (ANG * Math.PI) / 180;
  // só o necessário para cobrir a tela inclinada: a cobertura total dura ~3 quadros, não meio segundo
  const tela = p.largura * Math.cos(rad) + p.altura * Math.sin(rad);
  const corpo = tela * FOLGA;
  const s1 = 90 * u;
  const s2 = 150 * u;
  const L = (corpo + tela) / 2 + (s1 + s2);
  const x = travessia(f, p.frames) * L;
  const faixa = (larg: number, fundo: string): React.CSSProperties => ({ width: larg, height: '100%', background: fundo, flex: 'none' });
  return (
    <AbsoluteFill style={{ overflow: 'hidden' }}>
      <div
        style={{
          position: 'absolute',
          left: p.largura / 2 - D / 2,
          top: p.altura / 2 - D / 2,
          width: D,
          height: D,
          transform: `scaleX(${p.dir ?? 1}) rotate(${ANG}deg)`,
        }}
      >
        <div
          style={{
            position: 'absolute',
            left: D / 2 - corpo / 2 - (s1 + s2),
            top: -D * 0.2,
            height: D * 1.4,
            display: 'flex',
            transform: `translateX(${x}px)`,
          }}
        >
          <div style={faixa(s2, cor.tinta)} />
          <div style={faixa(s1, cor.secundaria)} />
          <div style={faixa(corpo, cor.destaque)} />
          <div style={faixa(s1, cor.secundaria)} />
          <div style={faixa(s2, cor.tinta)} />
        </div>
      </div>
    </AbsoluteFill>
  );
};

const Fatias: React.FC<{ p: PropsShortFx }> = ({ p }) => {
  const f = useCurrentFrame();
  const u = p.escala;
  const n = 6;
  const ah = Math.ceil(p.altura / n) + 1;
  const borda = 20 * u;
  const larg = p.largura * FOLGA + borda * 2;
  const L = (p.largura * FOLGA + p.largura) / 2 + borda;
  return (
    <AbsoluteFill style={{ overflow: 'hidden' }}>
      {Array.from({ length: n }, (_, i) => {
        const d = (i % 2 ? -1 : 1) * (p.dir ?? 1);
        const x = travessia(f, p.frames) * L * d;
        const fundo = i % 3 === 1 ? cor.destaque : cor.tinta;
        return (
          <div
            key={i}
            style={{
              position: 'absolute',
              left: (p.largura - larg) / 2,
              top: i * (p.altura / n),
              width: larg,
              height: ah,
              background: fundo,
              borderLeft: `${borda}px solid ${cor.secundaria}`,
              borderRight: `${borda}px solid ${cor.secundaria}`,
              boxSizing: 'border-box',
              transform: `translateX(${x}px)`,
            }}
          />
        );
      })}
    </AbsoluteFill>
  );
};

const Rasgo: React.FC<{ p: PropsShortFx }> = ({ p }) => {
  const f = useCurrentFrame();
  const u = p.escala;
  const w = p.largura;
  const h = p.altura;
  const dente = 70 * u;
  const corpo = h * FOLGA;
  const L = (corpo + h) / 2 + dente + 50 * u;
  const y = travessia(f, p.frames) * L * (p.dir ?? 1);
  const borda = (seed: number, y0: number, sentido: 1 | -1) => {
    const r = rng(seed);
    const pts: string[] = [];
    const k = 26;
    for (let i = 0; i <= k; i++) {
      const xx = (i / k) * w;
      const yy = y0 + sentido * (0.25 + 0.75 * r()) * dente * (i % 2 ? 1 : 0.35);
      pts.push(`${xx.toFixed(1)},${yy.toFixed(1)}`);
    }
    return pts;
  };
  const folha = (seed: number, folga: number) => {
    const y0 = -(corpo - h) / 2 - folga;
    const y1 = h + (corpo - h) / 2 + folga;
    const cima = borda(seed, y0, -1);
    const baixo = borda(seed + 17, y1, 1).reverse();
    return [...cima, ...baixo].join(' ');
  };
  return (
    <AbsoluteFill style={{ overflow: 'hidden' }}>
      <svg width={w} height={h} style={{ overflow: 'visible', transform: `translateY(${y}px)` }}>
        <polygon points={folha(p.seed + 5, 34 * u)} fill={cor.destaque} />
        <polygon points={folha(p.seed, 0)} fill={cor.papel ?? '#EFE6D2'} />
      </svg>
    </AbsoluteFill>
  );
};

const Iris: React.FC<{ p: PropsShortFx }> = ({ p }) => {
  const f = useCurrentFrame();
  const u = p.escala;
  const w = p.largura;
  const h = p.altura;
  const cx = w / 2;
  const cy = h * 0.42;
  const R = Math.hypot(w, h) * 0.75;
  const r = (Math.max(0, Math.abs(travessia(f, p.frames)) - 0.16) / 0.84) * R;
  const furo = r > 0.5 ? `M ${cx - r} ${cy} a ${r} ${r} 0 1 0 ${2 * r} 0 a ${r} ${r} 0 1 0 ${-2 * r} 0 Z` : '';
  return (
    <AbsoluteFill>
      <svg width={w} height={h}>
        <path d={`M 0 0 H ${w} V ${h} H 0 Z ${furo}`} fill={cor.tinta} fillRule="evenodd" />
        {r > 0.5 && (
          <>
            <circle cx={cx} cy={cy} r={r + 16 * u} fill="none" stroke={cor.destaque} strokeWidth={32 * u} />
            <circle cx={cx} cy={cy} r={r + 42 * u} fill="none" stroke={cor.secundaria} strokeWidth={8 * u} />
          </>
        )}
      </svg>
    </AbsoluteFill>
  );
};

// ---------------------------------------------------------------- peças que não cobrem
const Raio: React.FC<{ p: PropsShortFx }> = ({ p }) => {
  const f = useCurrentFrame();
  const u = p.escala;
  const N = p.frames;
  const m = Math.floor(N / 2);
  const r = rng(p.seed);
  const d = p.dir ?? 1;
  const clarao = 0.26 * Math.max(0, 1 - Math.abs(f - m) / 2.2);
  return (
    <AbsoluteFill style={{ overflow: 'hidden' }}>
      <AbsoluteFill style={{ background: cor.texto, opacity: clarao }} />
      {Array.from({ length: 7 }, (_, i) => {
        const y = (0.08 + 0.84 * r()) * p.altura;
        const esp = (5 + 14 * r()) * u;
        const larg = (0.55 + 0.6 * r()) * p.largura;
        const atraso = Math.floor(r() * 3);
        const x = interpolate(f, [atraso, N - 1], [-larg, p.largura], CL) * d + (d < 0 ? p.largura - larg : 0);
        const op = interpolate(f, [atraso, m, N - 1], [0, 0.95, 0], CL);
        const tom = i % 3 === 0 ? cor.secundaria : cor.texto;
        return (
          <div
            key={i}
            style={{
              position: 'absolute',
              left: 0,
              top: y,
              width: larg,
              height: esp,
              borderRadius: esp,
              background: `linear-gradient(90deg, ${alfa(tom, 0)}, ${tom} 50%, ${alfa(tom, 0)})`,
              opacity: op,
              transform: `translateX(${x}px)`,
            }}
          />
        );
      })}
    </AbsoluteFill>
  );
};

const Impacto: React.FC<{ p: PropsShortFx }> = ({ p }) => {
  const f = useCurrentFrame();
  const u = p.escala;
  const w = p.largura;
  const h = p.altura;
  const N = p.frames;
  const r = rng(p.seed);
  const cx = w / 2;
  const cy = h * 0.42;
  const prog = eOut(c01(f / (N - 1)));
  const op = interpolate(f, [0, 2, N - 1], [0, 1, 0], CL);
  const R = Math.hypot(w, h) * 0.62;
  return (
    <AbsoluteFill>
      <svg width={w} height={h}>
        <g opacity={op}>
          {Array.from({ length: 34 }, (_, i) => {
            const a = (i / 34) * Math.PI * 2 + r() * 0.12;
            const comp = (0.1 + 0.16 * r()) * R;
            const r0 = R * (1.02 - 0.2 * prog) - comp * prog;
            const r1 = r0 + comp;
            const esp = (9 + 14 * r()) * u;
            const tom = i % 4 === 0 ? cor.secundaria : cor.texto;
            return (
              <line
                key={i}
                x1={cx + Math.cos(a) * r0}
                y1={cy + Math.sin(a) * r0}
                x2={cx + Math.cos(a) * r1}
                y2={cy + Math.sin(a) * r1}
                stroke={tom}
                strokeWidth={esp}
                strokeLinecap="round"
                opacity={0.9}
              />
            );
          })}
          <circle cx={cx} cy={cy} r={(140 + 620 * prog) * u} fill="none" stroke={cor.destaque} strokeWidth={(38 * (1 - prog) + 3) * u} opacity={0.95} />
          <circle cx={cx} cy={cy} r={(90 + 520 * prog) * u} fill="none" stroke={cor.texto} strokeWidth={(14 * (1 - prog) + 2) * u} opacity={0.85} />
        </g>
      </svg>
    </AbsoluteFill>
  );
};

// ---------------------------------------------------------------- gancho cinético
const quebrar = (texto: string, max: number): string[][] => {
  const linhas: string[][] = [[]];
  let n = 0;
  for (const pal of texto.split(/\s+/).filter(Boolean)) {
    if (n && n + 1 + pal.length > max) {
      linhas.push([]);
      n = 0;
    }
    linhas[linhas.length - 1].push(pal);
    n += (n ? 1 : 0) + pal.length;
  }
  return linhas;
};

const Gancho: React.FC<{ p: PropsShortFx }> = ({ p }) => {
  const f = useCurrentFrame();
  const u = p.escala;
  const N = p.frames;
  const texto = (p.texto ?? '').trim();
  const longo = texto.length > 44;
  const tam = (longo ? 72 : 84) * u;
  const linhas = quebrar(texto, longo ? 19 : 16);
  const cx = (p.cx ?? 489) * u;
  const topo = (p.topo ?? 330) * u;
  const r = rng(p.seed);
  const saiIni = N - 9;
  let ordem = 0;
  const fimEntrada = 2 + (linhas.length - 1) * 3 + 2 + linhas.reduce((a, l) => a + l.length, 0) * 2 + 4;
  return (
    <AbsoluteFill>
      <div
        style={{
          position: 'absolute',
          left: cx - (p.larguraTexto ?? 800) * u / 2,
          top: topo,
          width: (p.larguraTexto ?? 800) * u,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          gap: 10 * u,
        }}
      >
        {linhas.map((linha, i) => {
          const ini = 2 + i * 3;
          const placa = eOut(c01((f - ini) / 6));
          const brasa = interpolate(f, [ini, ini + 9], [1, 0], CL);
          const sai = eIn(c01((f - saiIni - i) / 7));
          const giro = (i % 2 ? 1 : -1) * (0.7 + 0.6 * r());
          return (
            <div
              key={i}
              style={{
                position: 'relative',
                padding: `${10 * u}px ${28 * u}px ${14 * u}px`,
                transform: `rotate(${giro}deg) translateX(${-sai * 140 * u}px)`,
                opacity: 1 - sai,
              }}
            >
              <div
                style={{
                  position: 'absolute',
                  inset: 0,
                  background: cor.tinta,
                  transformOrigin: i % 2 ? 'right center' : 'left center',
                  transform: `scaleX(${placa})`,
                  boxShadow: `${8 * u}px ${8 * u}px 0 ${alfa(cor.destaque, 0.95)}`,
                }}
              />
              <div
                style={{
                  position: 'absolute',
                  inset: 0,
                  background: cor.destaque,
                  opacity: brasa * placa,
                  transformOrigin: i % 2 ? 'right center' : 'left center',
                  transform: `scaleX(${placa})`,
                }}
              />
              <div style={{ position: 'relative', display: 'flex', gap: tam * 0.26, whiteSpace: 'nowrap' }}>
                {linha.map((pal, j) => {
                  const k = ini + 2 + ordem * 2;
                  ordem += 1;
                  const x = c01((f - k) / 7);
                  const esc = 1 + 0.5 * (1 - ease.trava(x));
                  const numero = /\d/.test(pal);
                  return (
                    <span
                      key={j}
                      style={{
                        display: 'inline-block',
                        fontFamily: fonte.titulo,
                        fontWeight: 800,
                        fontSize: tam,
                        lineHeight: 1.12,
                        color: numero ? cor.secundaria : cor.texto,
                        opacity: c01((f - k) / 2),
                        transform: `translateY(${(1 - eOut(x)) * 26 * u}px) scale(${esc})`,
                      }}
                    >
                      {pal}
                    </span>
                  );
                })}
              </div>
            </div>
          );
        })}
        {/* sublinhado que risca depois que a última palavra bate */}
        <div
          style={{
            width: '62%',
            height: 12 * u,
            marginTop: 6 * u,
            background: cor.secundaria,
            transformOrigin: 'left center',
            transform: `scaleX(${eOut(c01((f - fimEntrada) / 8)) * (1 - eIn(c01((f - saiIni) / 6)))})`,
          }}
        />
      </div>
      {/* faíscas no instante em que a última palavra bate */}
      <svg width={p.largura} height={p.altura} style={{ position: 'absolute', inset: 0 }}>
        {Array.from({ length: 16 }, (_, i) => {
          const a = r() * Math.PI * 2;
          const dist = (120 + 380 * r()) * u;
          const x = eOut(c01((f - fimEntrada + 4) / 12));
          const px = cx + Math.cos(a) * (120 * u + dist * x);
          const py = topo + linhas.length * tam * 0.62 + Math.sin(a) * (60 * u + dist * 0.55 * x);
          const op = f < fimEntrada - 4 ? 0 : interpolate(x, [0, 0.15, 1], [0, 1, 0], CL);
          return <circle key={i} cx={px} cy={py} r={(4 + 7 * r()) * u * (1 - 0.6 * x)} fill={i % 3 ? cor.secundaria : cor.destaque} opacity={op} />;
        })}
      </svg>
    </AbsoluteFill>
  );
};

const PECAS: Record<PropsShortFx['tipo'], React.FC<{ p: PropsShortFx }>> = {
  gancho: Gancho,
  cortina: Cortina,
  fatias: Fatias,
  rasgo: Rasgo,
  iris: Iris,
  raio: Raio,
  impacto: Impacto,
};

export const ShortFx: React.FC<PropsShortFx> = (p) => {
  aplicarCanal(p.tokens as never, p.idioma);
  const Peca = PECAS[p.tipo] ?? Raio;
  return (
    <AbsoluteFill>
      <Fontes />
      <Peca p={p} />
    </AbsoluteFill>
  );
};
