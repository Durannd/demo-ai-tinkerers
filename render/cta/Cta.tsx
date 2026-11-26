import React from 'react';
import { AbsoluteFill, Easing, interpolate, interpolateColors, spring, useCurrentFrame } from 'remotion';
import { Fontes } from '../src/comp/Base';
import { num } from '../src/comp/i18n';
import { alfa, aplicarCanal, fonte, rng, T } from '../src/comp/tokens';

/**
 * CTAs animados (pipeline/cta.py): inscrever, like, comentar e combo — fundo TRANSPARENTE (ProRes 4444),
 * só a área do cartão; o FFmpeg sobrepõe por cima do acabamento.
 *
 * Unidades "u": 1 u = 1 px a 1080 de altura (16:9) — `escala` converte. Os TEMPOS vêm do Python
 * (cta.tempos): são os mesmos que o som.py usa para o clique, o pop e o sininho caírem no quadro certo.
 * Ícones desenhados aqui (SVG próprio): nada de logo do YouTube nem marca registrada.
 * Paleta: tokens.cta (opcional) > tokens.domino (fundo, marfim, tijolo, ouro) do canal.
 */
export type PropsCta = {
  id: string;
  tipo: 'inscrever' | 'like' | 'comentar' | 'combo';
  largura: number;
  altura: number;
  fps: number;
  frames: number;
  escala: number;
  lado: 'dir' | 'esq' | 'centro';
  ancora: 'baixo' | 'cima';
  compacto?: boolean;
  tempos: Record<string, number | null | undefined>;
  texto?: string;
  textos: { inscrever: string; inscrito: string; like: string; comentar: string };
  seed: number;
  contador: number;
  canal?: string;
  idioma?: string;
  tokens?: Record<string, any>;
};

const CL = { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' } as const;
const MARGEM = 40;
const inOut = Easing.inOut(Easing.cubic);
const saida = Easing.bezier(0.16, 1, 0.3, 1);

type Pal = { fundo: string; creme: string; tijolo: string; ouro: string; ouroEscuro: string };
const paleta = (): Pal => {
  const d = ((T as Record<string, any>).domino ?? {}) as Record<string, string>;
  const c = ((T as Record<string, any>).cta ?? {}) as Record<string, string>;
  return {
    fundo: c.fundo ?? d.fundo ?? '#0E0E10',
    creme: c.creme ?? d.marfim ?? '#F2E8D5',
    tijolo: c.tijolo ?? d.tijolo ?? '#C8432B',
    ouro: c.ouro ?? d.ouro ?? '#C9A55C',
    ouroEscuro: c.ouro_escuro ?? d.ouro_escuro ?? '#8A6A2E',
  };
};

/** Triângulo 0→1→0 entre a e b (pico no meio). */
const bump = (t: number, a: number, b: number) => (t <= a || t >= b ? 0 : 1 - Math.abs((t - a) / (b - a) * 2 - 1));

/** Escala de "aperto" de um botão clicado em c: afunda até 0,9 e volta com um quique curto (~4%). */
const aperto = (t: number, c: number | null | undefined, fundo = 0.9) => {
  if (c == null || t < c - 0.07) return 1;
  if (t < c) return 1 - (1 - fundo) * inOut((t - (c - 0.07)) / 0.07);
  const x = t - c;
  return 1 - (1 - fundo) * Math.exp(-8 * x) * Math.cos(2 * Math.PI * 2.1 * x);
};

// ---------------------------------------------------------------- ícones (SVG próprios, viewBox 24)
const Polegar: React.FC<{ tam: number; cor: string; preenchido: number; contorno: string }> = ({ tam, cor, preenchido, contorno }) => (
  <svg width={tam} height={tam} viewBox="0 0 24 24" style={{ overflow: 'visible' }}>
    <g fill={alfaDe(cor, preenchido)} stroke={contorno} strokeWidth={1.7} strokeLinejoin="round" strokeLinecap="round">
      <rect x={2.4} y={10.4} width={4.1} height={10.4} rx={1.1} />
      <path d="M8.6 20.8V10.7l3.9-6.9c.45-.8 1.45-1.1 2.25-.65.8.45 1.15 1.4.9 2.25L14.5 9.4h5c1.45 0 2.5 1.35 2.15 2.75l-1.55 6.6c-.3 1.2-1.35 2.05-2.6 2.05z" />
    </g>
  </svg>
);

/** Cor do token com alfa (aceita #RRGGBB). */
const alfaDe = (hexa: string, a: number) => (a >= 0.999 ? hexa : alfa(hexa, Math.max(0, a)));

const Sino: React.FC<{ tam: number; t: number; toque: number | null | undefined; pal: Pal; ativo: number }> = ({ tam, t, toque, pal, ativo }) => {
  const x = toque == null ? -1 : t - toque;
  const ang = x < 0 ? 0 : 24 * Math.exp(-3.2 * x) * Math.sin(2 * Math.PI * 4.2 * x);
  const xb = x - 0.06;
  const badalo = xb < 0 ? 0 : 1.6 * Math.exp(-3.2 * xb) * Math.sin(2 * Math.PI * 4.2 * xb);
  const ondas = x < 0 || x > 1.4 ? 0 : Math.exp(-1.6 * x) * (0.55 + 0.45 * Math.sin(2 * Math.PI * 4.2 * x - 1));
  const corpo = interpolateColors(ativo, [0, 1], [alfa(pal.creme, 0), pal.ouro]);
  const traco = interpolateColors(ativo, [0, 1], [pal.creme, pal.ouro]);
  return (
    <svg width={tam} height={tam} viewBox="0 0 24 24" style={{ overflow: 'visible' }}>
      {/* ondas do toque, dos dois lados */}
      {[-1, 1].map((lado) => (
        <g key={lado} opacity={ondas} stroke={pal.ouro} strokeWidth={1.6} fill="none" strokeLinecap="round">
          <path d={lado < 0 ? 'M3.2 7.2 Q1.4 10.4 3.2 13.6' : 'M20.8 7.2 Q22.6 10.4 20.8 13.6'} />
          <path d={lado < 0 ? 'M0.6 5.6 Q-2 10.4 0.6 15.2' : 'M23.4 5.6 Q26 10.4 23.4 15.2'} opacity={0.6} />
        </g>
      ))}
      <g transform={`rotate(${ang} 12 2.8)`}>
        <path
          d="M12 3.4c-3.2 0-5.4 2.5-5.4 5.7v3.8c0 .9-.35 1.75-.95 2.4l-1.15 1.25c-.45.5-.1 1.3.6 1.3h13.8c.7 0 1.05-.8.6-1.3l-1.15-1.25c-.6-.65-.95-1.5-.95-2.4V9.1c0-3.2-2.2-5.7-5.4-5.7z"
          fill={corpo}
          stroke={traco}
          strokeWidth={1.7}
          strokeLinejoin="round"
        />
        <circle cx={12} cy={2.6} r={1.25} fill={traco} />
        <path d={`M${9.7 + badalo} 18.9a2.3 2.3 0 0 0 4.6 0z`} fill={traco} />
      </g>
    </svg>
  );
};

const IconeComentario: React.FC<{ tam: number; cor: string; fundo: string }> = ({ tam, cor, fundo }) => (
  <svg width={tam} height={tam} viewBox="0 0 24 24">
    <path d="M3.6 5.6C3.6 4.2 4.7 3.1 6.1 3.1h11.8c1.4 0 2.5 1.1 2.5 2.5v8.3c0 1.4-1.1 2.5-2.5 2.5h-6.6l-4.5 3.7c-.45.35-1.05.05-1.05-.5v-3.2h-.2c-1.4 0-2.5-1.1-2.5-2.5z" fill={cor} />
    {[8.2, 12, 15.8].map((x) => (
      <circle key={x} cx={x} cy={9.8} r={1.25} fill={fundo} />
    ))}
  </svg>
);

/** Ponteiro do mouse: a PONTA fica em (x, y). */
const Cursor: React.FC<{ x: number; y: number; u: number; aperto: number; opacidade: number; pal: Pal }> = ({ x, y, u, aperto: ap, opacidade, pal }) => {
  const w = 30 * u;
  const h = 39 * u;
  return (
    <svg
      width={w}
      height={h}
      viewBox="0 0 24 31"
      style={{
        position: 'absolute',
        left: x - (2 / 24) * w,
        top: y - (1.5 / 31) * h,
        opacity: opacidade,
        transform: `scale(${ap})`,
        transformOrigin: `${(2 / 24) * 100}% ${(1.5 / 31) * 100}%`,
        filter: `drop-shadow(0 ${3 * u}px ${4 * u}px rgba(0,0,0,0.55))`,
        overflow: 'visible',
      }}
    >
      <path d="M2 1.5 L2 24.2 L7.5 19.3 L11.2 27.7 L15.1 26 L11.5 17.8 L19.2 17.8 Z" fill={pal.creme} stroke={pal.fundo} strokeWidth={1.7} strokeLinejoin="round" />
    </svg>
  );
};

/** Onda do clique (anel que abre e some). */
const Onda: React.FC<{ x: number; y: number; t: number; c: number | null | undefined; u: number; cor: string; raio?: number }> = ({ x, y, t, c, u, cor, raio = 44 }) => {
  if (c == null || t < c || t > c + 0.45) return null;
  const k = (t - c) / 0.45;
  const r = (8 + raio * saida(k)) * u;
  return (
    <div
      style={{
        position: 'absolute',
        left: x - r,
        top: y - r,
        width: 2 * r,
        height: 2 * r,
        borderRadius: '50%',
        border: `${Math.max(1, 4 * (1 - k)) * u}px solid ${cor}`,
        opacity: 0.75 * (1 - k),
      }}
    />
  );
};

// ---------------------------------------------------------------- partes
/** Partículas + anel de choque em volta de (cx, cy), disparadas em t0. */
const Estouro: React.FC<{ cx: number; cy: number; r: number; t: number; t0: number | null | undefined; u: number; pal: Pal; seed: number }> = ({ cx, cy, r, t, t0, u, pal, seed }) => {
  if (t0 == null || t < t0 || t > t0 + 0.8) return null;
  const x = t - t0;
  const rnd = rng(seed);
  const n = 12;
  const cores = [pal.ouro, pal.tijolo, pal.creme];
  const k = x / 0.45;
  return (
    <>
      {k < 1 && (
        <div
          style={{
            position: 'absolute',
            left: cx - r * (1 + 1.2 * saida(k)),
            top: cy - r * (1 + 1.2 * saida(k)),
            width: 2 * r * (1 + 1.2 * saida(k)),
            height: 2 * r * (1 + 1.2 * saida(k)),
            borderRadius: '50%',
            border: `${5 * (1 - k) * u}px solid ${pal.ouro}`,
            opacity: 0.85 * (1 - k),
          }}
        />
      )}
      {Array.from({ length: n }, (_, i) => {
        const a = (2 * Math.PI * i) / n + (rnd() - 0.5) * 0.45;
        const dist = r * (1.15 + 0.85 * rnd());
        const vida = 0.5 + 0.25 * rnd();
        const p = Math.min(1, x / vida);
        if (p >= 1) return null;
        const d = r * 0.85 + dist * saida(p);
        const tam = (i % 3 === 0 ? 15 : 9) * u * (1 - p * 0.85);
        const px = cx + Math.cos(a) * d;
        const py = cy + Math.sin(a) * d - 10 * u * p;
        const corP = cores[i % 3];
        return i % 3 === 0 ? (
          <svg key={i} width={tam} height={tam} viewBox="-10 -10 20 20" style={{ position: 'absolute', left: px - tam / 2, top: py - tam / 2, opacity: 1 - p, transform: `rotate(${p * 90}deg)` }}>
            <path d="M0 -10 Q1.6 -1.6 10 0 Q1.6 1.6 0 10 Q-1.6 1.6 -10 0 Q-1.6 -1.6 0 -10z" fill={pal.ouro} />
          </svg>
        ) : (
          <div key={i} style={{ position: 'absolute', left: px - tam / 2, top: py - tam / 2, width: tam, height: tam, borderRadius: '50%', background: corP, opacity: 1 - p }} />
        );
      })}
    </>
  );
};

/** Círculo do polegar (pula, enche de cor, estoura). */
const BotaoLike: React.FC<{ cx: number; cy: number; r: number; t: number; like: number | null | undefined; u: number; pal: Pal; seed: number; fps: number; f: number }> = ({ cx, cy, r, t, like, u, pal, seed, fps, f }) => {
  const x = like == null ? -1 : t - like;
  const k = like == null ? 0 : interpolate(t, [like, like + 0.12], [0, 1], CL);
  const pulo = x > 0 && x < 0.42 ? -18 * u * Math.sin((Math.PI * x) / 0.42) : 0;
  const ant = like == null ? 1 : 1 - 0.12 * bump(t, like - 0.12, like + 0.02);
  const mola = like == null || x < 0 ? 0 : spring({ frame: f - like * fps, fps, config: { damping: 7, stiffness: 240, mass: 0.6 } });
  const esc = ant * (x < 0 ? 1 : 0.86 + 0.14 * mola + 0.22 * bump(x, 0, 0.3));
  const rot = x < 0 ? 0 : -18 * Math.exp(-5 * x) * Math.cos(2 * Math.PI * 1.4 * x);
  const fundoC = interpolateColors(k, [0, 1], [alfa(pal.creme, 0.1), pal.tijolo]);
  return (
    <>
      <Estouro cx={cx} cy={cy} r={r} t={t} t0={like} u={u} pal={pal} seed={seed} />
      <div
        style={{
          position: 'absolute',
          left: cx - r,
          top: cy - r,
          width: 2 * r,
          height: 2 * r,
          borderRadius: '50%',
          background: fundoC,
          border: `${2 * u}px solid ${interpolateColors(k, [0, 1], [alfa(pal.creme, 0.45), pal.tijolo])}`,
          boxSizing: 'border-box',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          transform: `translateY(${pulo}px) scale(${esc}) rotate(${rot}deg)`,
          boxShadow: k > 0 ? `0 0 ${18 * u * k}px ${alfa(pal.tijolo, 0.55 * k)}` : 'none',
        }}
      >
        <div style={{ transform: `translateY(${-1.5 * u}px)` }}>
          <Polegar tam={r * 1.12} cor={pal.creme} preenchido={k} contorno={pal.creme} />
        </div>
      </div>
      {/* +1 que sobe */}
      {x > 0.05 && x < 1.1 && (
        <div
          style={{
            position: 'absolute',
            left: cx + r * 0.35,
            top: cy - r - 30 * u * saida(Math.min(1, (x - 0.05) / 0.6)),
            fontFamily: fonte.rotulo,
            fontWeight: 800,
            fontSize: 24 * u,
            color: pal.ouro,
            opacity: interpolate(x, [0.05, 0.15, 0.8, 1.1], [0, 1, 1, 0], CL),
            textShadow: `0 ${2 * u}px ${6 * u}px rgba(0,0,0,0.6)`,
          }}
        >
          +1
        </div>
      )}
    </>
  );
};

/** Botão INSCREVA-SE → INSCRITO (com brilho passando antes do clique). */
const BotaoInscrever: React.FC<{ x: number; y: number; w: number; h: number; t: number; clique: number | null | undefined; u: number; pal: Pal; p: PropsCta; fs: number }> = ({ x, y, w, h, t, clique, u, pal, p, fs }) => {
  const k = clique == null ? 0 : interpolate(t, [clique, clique + 0.14], [0, 1], CL);
  const check = clique == null ? 0 : interpolate(t, [clique + 0.08, clique + 0.34], [0, 1], { ...CL, easing: saida });
  const brilho = clique == null ? -1 : interpolate(t, [clique - 0.75, clique - 0.2], [-0.4, 1.4], CL);
  const fundoB = interpolateColors(k, [0, 1], [pal.tijolo, alfa(pal.creme, 0.1)]);
  const estilo: React.CSSProperties = {
    position: 'absolute',
    inset: 0,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 9 * u,
    fontFamily: fonte.rotulo,
    fontWeight: 800,
    fontSize: fs * u,
    letterSpacing: '0.06em',
    color: pal.creme,
    whiteSpace: 'nowrap',
  };
  return (
    <div
      style={{
        position: 'absolute',
        left: x,
        top: y,
        width: w,
        height: h,
        borderRadius: h / 2,
        background: fundoB,
        border: `${2 * u}px solid ${alfa(pal.creme, 0.38 * k)}`,
        boxSizing: 'border-box',
        overflow: 'hidden',
        transform: `scale(${aperto(t, clique, 0.92)})`,
        boxShadow: k < 1 ? `0 ${4 * u}px ${14 * u}px ${alfa(pal.tijolo, 0.45 * (1 - k))}` : 'none',
      }}
    >
      {brilho > -0.4 && brilho < 1.4 && (
        <div
          style={{
            position: 'absolute',
            top: -h,
            bottom: -h,
            left: `${brilho * 100}%`,
            width: 34 * u,
            transform: 'rotate(22deg)',
            background: `linear-gradient(90deg, ${alfa(pal.creme, 0)}, ${alfa(pal.creme, 0.38)}, ${alfa(pal.creme, 0)})`,
          }}
        />
      )}
      <div style={{ ...estilo, opacity: 1 - k, transform: `translateY(${-10 * u * k}px)` }}>{p.textos.inscrever}</div>
      <div style={{ ...estilo, opacity: k, transform: `translateY(${10 * u * (1 - k)}px)`, color: pal.creme }}>
        <svg width={fs * 0.95 * u} height={fs * 0.95 * u} viewBox="0 0 24 24">
          <path d="M4 12.5l5 5L20 6.5" fill="none" stroke={pal.ouro} strokeWidth={3.4} strokeLinecap="round" strokeLinejoin="round" pathLength={1} strokeDasharray={1} strokeDashoffset={1 - check} />
        </svg>
        {p.textos.inscrito}
      </div>
    </div>
  );
};

/** Contador que sobe (odômetro: só os dígitos que mudam rolam). */
const Contador: React.FC<{ base: number; passos: number; t: number; t0: number | null | undefined; u: number; cor: string; fs: number }> = ({ base, passos, t, t0, u, cor, fs }) => {
  const prog = t0 == null ? 0 : interpolate(t, [t0 + 0.05, t0 + 1.5], [0, 1], { ...CL, easing: Easing.out(Easing.cubic) });
  const v = base + passos * prog;
  const n = Math.floor(v + 1e-6);
  const fr = prog >= 1 ? 0 : v - n;
  const a = num(n);
  const b = num(n + 1);
  const lh = fs * 1.15 * u;
  const e = inOut(Math.min(1, fr * 1.6));
  return (
    <div style={{ display: 'flex', fontFamily: fonte.rotulo, fontWeight: 700, fontSize: fs * u, color: cor, fontVariantNumeric: 'tabular-nums', height: lh, lineHeight: `${lh}px`, overflow: 'hidden' }}>
      {a.length === b.length
        ? a.split('').map((ch, i) =>
            ch === b[i] ? (
              <span key={i}>{ch}</span>
            ) : (
              <span key={i} style={{ position: 'relative', display: 'inline-block', height: lh }}>
                <span style={{ display: 'block', transform: `translateY(${-e * lh}px)` }}>{ch}</span>
                <span style={{ display: 'block', transform: `translateY(${-e * lh}px)` }}>{b[i]}</span>
              </span>
            ),
          )
        : a}
    </div>
  );
};

// ---------------------------------------------------------------- cartões
type Ctx = { p: PropsCta; t: number; f: number; u: number; pal: Pal };

/** Trajeto do cursor: [(t, x, y)] → posição, opacidade e aperto no instante t. */
const usarCursor = (pts: [number, number, number][], cliques: (number | null | undefined)[], t: number, sai: number) => {
  const ts = pts.map((q) => q[0]);
  const x = interpolate(t, ts, pts.map((q) => q[1]), { ...CL, easing: inOut });
  const y = interpolate(t, ts, pts.map((q) => q[2]), { ...CL, easing: inOut });
  const op = interpolate(t, [ts[0], ts[0] + 0.18, sai - 0.25, sai], [0, 1, 1, 0], CL);
  const ap = cliques.reduce<number>((acc, c) => acc * (c == null ? 1 : 1 - 0.16 * bump(t, c - 0.08, c + 0.1)), 1);
  return { x, y, op, ap };
};

const Fundo: React.FC<{ w: number | string; h: number; u: number; pal: Pal; raio?: number }> = ({ w, h, u, pal, raio }) => (
  <div
    style={{
      position: 'absolute',
      left: 0,
      top: 0,
      width: w,
      height: h,
      borderRadius: raio ?? h / 2,
      background: alfa(pal.fundo, 0.93),
      border: `${2 * u}px solid ${alfa(pal.ouro, 0.55)}`,
      boxSizing: 'border-box',
      boxShadow: `0 ${10 * u}px ${28 * u}px rgba(0,0,0,0.5), inset 0 ${1.5 * u}px 0 ${alfa(pal.creme, 0.08)}`,
    }}
  />
);

const CartaoInscrever: React.FC<Ctx> = ({ p, t, u, pal }) => {
  const tp = p.tempos;
  const W = 392 * u;
  const H = 96 * u;
  const bx = 15 * u;
  const by = 15 * u;
  const bw = 290 * u;
  const bh = 66 * u;
  const sx = (15 + 290 + 16 + 28) * u;
  const sy = 48 * u;
  const alvoB: [number, number] = [bx + bw * 0.62, by + bh * 0.62];
  const alvoS: [number, number] = [sx + 4 * u, sy + 8 * u];
  const pts: [number, number, number][] = [[tp.cursor ?? 0.3, W + 24 * u, H + 34 * u], [(tp.clique ?? 1) - 0.12, ...alvoB], [(tp.clique ?? 1) + 0.1, ...alvoB]];
  if (tp.clique_sino != null) pts.push([tp.clique_sino - 0.12, ...alvoS], [tp.clique_sino + 0.12, ...alvoS]);
  pts.push([(tp.sai ?? 3.5) - 0.05, W + 24 * u, H + 30 * u]);
  const cur = usarCursor(pts, [tp.clique, tp.clique_sino], t, tp.sai ?? 3.5);
  const ativo = tp.sino == null ? 0 : interpolate(t, [tp.sino, tp.sino + 0.12], [0, 1], CL);
  return (
    <div style={{ position: 'relative', width: W, height: H }}>
      <Fundo w={W} h={H} u={u} pal={pal} />
      <BotaoInscrever x={bx} y={by} w={bw} h={bh} t={t} clique={tp.clique} u={u} pal={pal} p={p} fs={27} />
      <div style={{ position: 'absolute', left: sx - 28 * u, top: sy - 28 * u, width: 56 * u, height: 56 * u, display: 'flex', alignItems: 'center', justifyContent: 'center', transform: `scale(${aperto(t, tp.clique_sino, 0.88)})` }}>
        <Sino tam={40 * u} t={t} toque={tp.sino} pal={pal} ativo={ativo} />
      </div>
      <Onda x={alvoB[0]} y={alvoB[1]} t={t} c={tp.clique} u={u} cor={pal.creme} />
      <Onda x={alvoS[0]} y={alvoS[1]} t={t} c={tp.clique_sino} u={u} cor={pal.ouro} raio={34} />
      <Cursor x={cur.x} y={cur.y} u={u} aperto={cur.ap} opacidade={cur.op} pal={pal} />
    </div>
  );
};

const CartaoLike: React.FC<Ctx> = ({ p, t, f, u, pal }) => {
  const tp = p.tempos;
  const H = 96 * u;
  const r = 34 * u;
  const passos = 7 + (p.seed % 9);
  return (
    <div style={{ position: 'relative', height: H, display: 'flex', alignItems: 'center', paddingLeft: 16 * u, paddingRight: 30 * u }}>
      <div style={{ position: 'absolute', inset: 0 }}>
        <Fundo w="100%" h={H} u={u} pal={pal} />
      </div>
      <div style={{ position: 'relative', width: 2 * r, height: 2 * r, flexShrink: 0 }}>
        <BotaoLike cx={r} cy={r} r={r} t={t} like={tp.like} u={u} pal={pal} seed={p.seed} fps={p.fps} f={f} />
      </div>
      <div style={{ position: 'relative', marginLeft: 16 * u, display: 'flex', flexDirection: 'column', gap: 2 * u }}>
        <div style={{ fontFamily: fonte.titulo, fontWeight: 700, fontSize: 30 * u, color: pal.creme, whiteSpace: 'nowrap', lineHeight: 1.05 }}>{p.textos.like}</div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 7 * u }}>
          <Polegar tam={17 * u} cor={pal.ouro} preenchido={1} contorno={pal.ouro} />
          <Contador base={p.contador} passos={passos} t={t} t0={tp.like} u={u} cor={pal.ouro} fs={22} />
        </div>
      </div>
    </div>
  );
};

const CartaoCombo: React.FC<Ctx> = ({ p, t, f, u, pal }) => {
  const tp = p.tempos;
  const W = 430 * u;
  const H = 96 * u;
  const r = 34 * u;
  const lx = 48 * u;
  const ly = 48 * u;
  const bx = 96 * u;
  const by = 17 * u;
  const bw = 250 * u;
  const bh = 62 * u;
  const sx = (96 + 250 + 14 + 28) * u;
  const sy = 48 * u;
  const alvoL: [number, number] = [lx + 6 * u, ly + 10 * u];
  const alvoB: [number, number] = [bx + bw * 0.6, by + bh * 0.62];
  const alvoS: [number, number] = [sx + 4 * u, sy + 8 * u];
  const like = tp.like ?? 0.8;
  const clique = tp.clique ?? 1.5;
  const pts: [number, number, number][] = [
    [tp.cursor ?? 0.25, W + 24 * u, H + 34 * u],
    [like - 0.12, ...alvoL],
    [like + 0.08, ...alvoL],
    [clique - 0.12, ...alvoB],
    [clique + 0.08, ...alvoB],
  ];
  if (tp.clique_sino != null) pts.push([tp.clique_sino - 0.12, ...alvoS], [tp.clique_sino + 0.1, ...alvoS]);
  pts.push([(tp.sai ?? 3.9) - 0.05, W + 24 * u, H + 30 * u]);
  const cur = usarCursor(pts, [tp.like, tp.clique, tp.clique_sino], t, tp.sai ?? 3.9);
  const ativo = tp.sino == null ? 0 : interpolate(t, [tp.sino, tp.sino + 0.12], [0, 1], CL);
  return (
    <div style={{ position: 'relative', width: W, height: H }}>
      <Fundo w={W} h={H} u={u} pal={pal} />
      <BotaoLike cx={lx} cy={ly} r={r} t={t} like={tp.like} u={u} pal={pal} seed={p.seed} fps={p.fps} f={f} />
      <BotaoInscrever x={bx} y={by} w={bw} h={bh} t={t} clique={tp.clique} u={u} pal={pal} p={p} fs={25} />
      <div style={{ position: 'absolute', left: sx - 28 * u, top: sy - 28 * u, width: 56 * u, height: 56 * u, display: 'flex', alignItems: 'center', justifyContent: 'center', transform: `scale(${aperto(t, tp.clique_sino, 0.88)})` }}>
        <Sino tam={38 * u} t={t} toque={tp.sino} pal={pal} ativo={ativo} />
      </div>
      <Onda x={alvoB[0]} y={alvoB[1]} t={t} c={tp.clique} u={u} cor={pal.creme} />
      <Onda x={alvoS[0]} y={alvoS[1]} t={t} c={tp.clique_sino} u={u} cor={pal.ouro} raio={34} />
      <Cursor x={cur.x} y={cur.y} u={u} aperto={cur.ap} opacidade={cur.op} pal={pal} />
    </div>
  );
};

const CartaoComentar: React.FC<Ctx> = ({ p, t, f, u, pal }) => {
  const tp = p.tempos;
  const texto = p.texto ?? '';
  const bolha = spring({ frame: f - (tp.bolha ?? 0.12) * p.fps, fps: p.fps, config: { damping: 14, stiffness: 190, mass: 0.7 } });
  const ini = tp.tipo ?? 0.95;
  const n = Math.max(0, Math.min(texto.length, Math.floor((t - ini) * (tp.cps ?? 22))));
  const digitando = t >= ini && n < texto.length;
  const caret = digitando || (t >= ini && Math.floor((t - ini) * 2.4) % 2 === 0);
  const pontos = t < ini;
  const fs = 30 * u;
  return (
    <div style={{ position: 'relative', display: 'flex', flexDirection: 'column', alignItems: 'flex-start', gap: 12 * u, width: 520 * u }}>
      {/* etiqueta: ícone + "Comenta aí" */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 9 * u,
          height: 46 * u,
          padding: `0 ${18 * u}px 0 ${12 * u}px`,
          borderRadius: 23 * u,
          background: pal.tijolo,
          boxShadow: `0 ${6 * u}px ${16 * u}px rgba(0,0,0,0.45)`,
        }}
      >
        <IconeComentario tam={28 * u} cor={pal.creme} fundo={pal.tijolo} />
        <span style={{ fontFamily: fonte.titulo, fontWeight: 700, fontSize: 26 * u, color: pal.creme, whiteSpace: 'nowrap' }}>{p.textos.comentar}</span>
      </div>
      {/* balão com a pergunta */}
      <div
        style={{
          position: 'relative',
          width: 520 * u,
          boxSizing: 'border-box',
          padding: `${20 * u}px ${26 * u}px ${22 * u}px`,
          borderRadius: 22 * u,
          background: pal.creme,
          color: pal.fundo,
          fontFamily: fonte.rotulo,
          fontWeight: 600,
          fontSize: fs,
          lineHeight: 1.28,
          boxShadow: `0 ${10 * u}px ${28 * u}px rgba(0,0,0,0.5)`,
          transform: `scale(${0.4 + 0.6 * bolha})`,
          transformOrigin: `${44 * u}px 100%`,
          opacity: Math.min(1, bolha * 2),
        }}
      >
        <span>{texto.slice(0, n)}</span>
        <span
          style={{
            display: 'inline-block',
            width: 3 * u,
            height: fs * 1.02,
            marginRight: -3 * u,
            verticalAlign: '-0.16em',
            background: pal.tijolo,
            opacity: caret && !pontos ? 1 : 0,
          }}
        />
        <span style={{ color: 'transparent' }}>{texto.slice(n)}</span>
        {pontos && (
          <div style={{ position: 'absolute', left: 26 * u, top: 20 * u + fs * 0.42, display: 'flex', gap: 8 * u }}>
            {[0, 1, 2].map((i) => (
              <div
                key={i}
                style={{
                  width: 10 * u,
                  height: 10 * u,
                  borderRadius: '50%',
                  background: alfa(pal.fundo, 0.55),
                  transform: `translateY(${-6 * u * Math.max(0, Math.sin(2 * Math.PI * 2.2 * t - i * 0.9))}px)`,
                }}
              />
            ))}
          </div>
        )}
        {/* rabinho do balão */}
        <svg width={30 * u} height={18 * u} viewBox="0 0 30 18" style={{ position: 'absolute', left: 30 * u, bottom: -16 * u }}>
          <path d="M0 0 L30 0 L6 18 Z" fill={pal.creme} />
        </svg>
      </div>
    </div>
  );
};

const CARTOES: Record<PropsCta['tipo'], React.FC<Ctx>> = {
  inscrever: CartaoInscrever,
  like: CartaoLike,
  combo: CartaoCombo,
  comentar: CartaoComentar,
};

export const Cta: React.FC<PropsCta> = (p) => {
  aplicarCanal(p.tokens as never, p.idioma);
  const f = useCurrentFrame();
  const t = f / p.fps;
  const u = p.escala;
  const pal = paleta();
  const tp = p.tempos;
  // entra com mola (um quique leve: é um elemento "divertido", não uma cena) e sai encolhendo
  const ent = spring({ frame: f, fps: p.fps, config: { damping: 12, stiffness: 170, mass: 0.75 } });
  const sai = interpolate(t, [tp.sai ?? 3.5, tp.fim ?? 4], [0, 1], { ...CL, easing: Easing.in(Easing.cubic) });
  const esc = (0.55 + 0.45 * ent) * (1 - 0.3 * sai);
  const op = interpolate(ent, [0, 0.3], [0, 1], CL) * (1 - sai);
  const dirY = p.ancora === 'cima' ? -1 : 1;
  const origemX = p.lado === 'esq' ? 'left' : p.lado === 'dir' ? 'right' : 'center';
  const origemY = p.ancora === 'cima' ? 'top' : 'bottom';
  const C = CARTOES[p.tipo];
  return (
    <AbsoluteFill
      style={{
        display: 'flex',
        justifyContent: p.lado === 'esq' ? 'flex-start' : p.lado === 'dir' ? 'flex-end' : 'center',
        alignItems: p.ancora === 'cima' ? 'flex-start' : 'flex-end',
        padding: MARGEM * u,
      }}
    >
      <Fontes />
      <div
        style={{
          transform: `translateY(${dirY * ((1 - ent) * 24 * u + sai * 12 * u)}px) scale(${esc})`,
          transformOrigin: `${origemX} ${origemY}`,
          opacity: op,
        }}
      >
        {C ? <C p={p} t={t} f={f} u={u} pal={pal} /> : null}
      </div>
    </AbsoluteFill>
  );
};
