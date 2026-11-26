import React from 'react';
import { AbsoluteFill, Img, staticFile, useCurrentFrame } from 'remotion';
import { Fontes } from '../src/comp/Base';
import { Icone } from '../src/comp/Elementos';
import { alfa, aplicarCanal, cor, ease, fonte, rng } from '../src/comp/tokens';

/**
 * OBJETO DA HISTÓRIA (pipeline/objetos.py): a coisa de que a narração está falando aparece na tela na palavra
 * em que é dita e SE TRANSFORMA nas palavras seguintes — fundo transparente (ProRes 4444), sobreposto pelo FFmpeg
 * à cena (longo) e ao Short (9:16). É animação de RECORTES (colagem): tudo está sempre em movimento.
 *
 * Objeto: recorte RGBA (foto real ou imagem gerada, recortada por ISNet) com contorno de "adesivo", ou um ícone.
 * Personagem (opcional): figura genérica recortada (um cientista, um soldado, um operário…) que entra ANDANDO de
 * um lado e faz coisas com o objeto: a mão dele (ponto `mao`, medido no recorte) é onde o objeto fica preso.
 *
 * Ações (cada uma numa palavra da narração):
 *   com o corpo do objeto   cor · enche · esvazia · multiplica · quebra · cresce · encolhe · gira · treme · acende · risca · some
 *   de manuseio             pega (vai para a mão do personagem) · agita · ergue · despeja (vira e o líquido cai) · joga (arremessa)
 *                           · olha (o personagem se inclina) — agita/ergue/despeja funcionam também sem personagem
 * Movimento de fundo: flutuação leve, líquido que balança com bolhas, respingos ao encher, poeira ao pousar,
 * raios girando no `acende`, cópias em órbita no `multiplica`, estilhaços no `quebra`.
 */
type Acao = { tipo: string; t: number; cor?: string; n?: number };
type Personagem = { src: string; mao: [number, number]; lado: 'esq' | 'dir'; t: number; aspecto: number };
export type PropsObjeto = {
  id: string;
  largura: number;
  altura: number;
  fps: number;
  frames: number;
  /** lado da caixa do objeto, em px */
  lado: number;
  escala: number;
  seed: number;
  src?: string | null;
  icone?: string | null;
  entrada: 'cai' | 'surge' | 'desliza' | 'gira';
  acoes: Acao[];
  personagem?: Personagem | null;
  rotulo?: string;
  /** s (relativo ao clipe) em que o objeto começa a entrar e em que tudo começa a sair */
  entra?: number;
  sai: number;
  idioma?: string;
  tokens?: Record<string, any>;
};

const c01 = (x: number) => Math.max(0, Math.min(1, x));
const mix = (a: number, b: number, k: number) => a + (b - a) * k;
const PECAS = [
  'polygon(0% 0%, 58% 0%, 44% 46%, 0% 60%)',
  'polygon(58% 0%, 100% 0%, 100% 70%, 62% 56%, 44% 46%)',
  'polygon(0% 60%, 44% 46%, 62% 56%, 100% 70%, 100% 100%, 0% 100%)',
];
const VOO = [
  { x: -0.34, y: 0.5, r: -38 },
  { x: 0.4, y: 0.42, r: 31 },
  { x: 0.05, y: 0.75, r: 12 },
];
const RAD = Math.PI / 180;

export const Objeto: React.FC<PropsObjeto> = (p) => {
  aplicarCanal(p.tokens as never, p.idioma);
  const f = useCurrentFrame();
  const t = f / p.fps;
  const u = p.escala;
  const S = p.lado;
  const r = rng(p.seed);
  const papel = (cor as Record<string, string>).papel ?? '#EFE6D2';
  const da = (tipo: string) => p.acoes.filter((a) => a.tipo === tipo);
  /** progresso 0–1 de uma ação que dura `dur` s */
  const k = (a: Acao | undefined, dur: number, e: (x: number) => number = ease.saida, atraso = 0) => (a ? e(c01((t - a.t - atraso) / dur)) : 0);
  const per = p.personagem ?? null;
  const tObj = p.entra ?? 0;
  const to = t - tObj; // relógio do objeto

  // ---------------------------------------------------------------- geometria
  const W = p.largura;
  const H = p.altura - (p.rotulo ? 80 * u : 0);
  const sinal = per ? (per.lado === 'esq' ? 1 : -1) : 1; // para onde o personagem olha (+1 = direita)
  const Hc = per ? Math.min(H * 0.92, S * 2.0) : 0;
  const Wc = per ? Hc * per.aspecto : 0;
  const peX = per ? (per.lado === 'esq' ? W * 0.3 : W * 0.7) : 0;
  const peY = H / 2 + Hc / 2;
  const repX = per ? (per.lado === 'esq' ? W * 0.72 : W * 0.28) : W / 2;
  const repY = per ? H / 2 + S * 0.25 : H / 2;

  // ---------------------------------------------------------------- personagem (boneco de recorte)
  const aPega = da('pega')[0];
  const aAgita = da('agita')[0];
  const aErgue = da('ergue')[0];
  const aDespeja = da('despeja')[0];
  const aJoga = da('joga')[0];
  const aOlha = da('olha')[0];
  const xa = aAgita ? t - aAgita.t : -1;
  const agitando = xa >= 0 && xa < 1.1 ? Math.exp(-2.6 * xa) : 0;
  let rotP = 0;
  let pdx = 0;
  let pdy = 0;
  if (per) {
    const kIn = c01((t - per.t) / 0.8);
    pdx = -sinal * (1 - ease.saida(kIn)) * (W * 0.75);
    // anda: quatro passos (sobe e desce + gingado) e depois respira
    pdy = -Math.abs(Math.sin(Math.PI * 4 * kIn)) * 22 * u * (1 - kIn * kIn);
    rotP = Math.sin(Math.PI * 4 * kIn) * 3.5 * (1 - kIn) + Math.sin((2 * Math.PI * t) / 3.1) * 0.9;
    rotP += sinal * 7 * k(aOlha, 0.4, ease.trava) * (1 - k(aOlha, 0.5, ease.saida, 1.4));
    rotP += sinal * 5 * k(aPega, 0.25) * (1 - k(aPega, 0.35, ease.saida, 0.3));
    rotP += agitando * 4 * Math.sin(2 * Math.PI * 7 * xa);
    rotP -= sinal * 5 * k(aErgue, 0.4, ease.trava);
    rotP += sinal * 6 * k(aDespeja, 0.4);
    if (aJoga) {
      const xj = t - aJoga.t;
      rotP += sinal * (xj < 0 ? -9 * c01((xj + 0.25) / 0.25) : -9 + 20 * ease.saida(c01(xj / 0.18)) - 11 * ease.suave(c01((xj - 0.3) / 0.5)));
    }
  }
  /** ponto da mão no canvas, já com o corpo inclinado */
  const mao = () => {
    if (!per) return { x: repX, y: repY };
    const vx = (per.mao[0] - 0.5) * Wc * sinal;
    const vy = (per.mao[1] - 1) * Hc;
    const a = rotP * RAD;
    return { x: peX + pdx + vx * Math.cos(a) - vy * Math.sin(a), y: peY + pdy + vx * Math.sin(a) + vy * Math.cos(a) };
  };

  // ---------------------------------------------------------------- objeto: posição, giro, escala
  const kE = c01(to / 0.42);
  const eE = ease.trava(kE);
  const some = da('some')[0];
  const tSai = Math.min(p.sai, some ? some.t : 1e9);
  const kS = ease.entrada(c01((t - tSai) / 0.22));
  let ox = repX;
  let oy = repY;
  let esc = 1;
  let escY = 1;
  let rot = (r() - 0.5) * 5;
  if (p.entrada === 'cai') {
    oy -= (1 - eE) * S * 1.3;
    // amassa ao pousar e volta
    const xp = to - 0.4;
    if (xp >= 0 && xp < 0.5) escY = 1 - 0.12 * Math.exp(-9 * xp) * Math.cos(2 * Math.PI * 3.2 * xp);
  } else if (p.entrada === 'desliza') {
    ox += (1 - eE) * S * 1.1 * (p.seed % 2 ? 1 : -1);
    rot += (1 - eE) * 14 * (p.seed % 2 ? 1 : -1);
  } else if (p.entrada === 'gira') {
    esc = 0.25 + 0.75 * eE;
    rot += (1 - eE) * -200;
  } else esc = 0.5 + 0.5 * eE;
  // flutua sempre (recorte de colagem nunca fica parado)
  const preso = aPega && per ? k(aPega, 0.45, ease.camera) : 0;
  const flut = 1 - preso * 0.8;
  oy += Math.sin((2 * Math.PI * t) / 2.6 + p.seed) * 8 * u * flut;
  ox += Math.sin((2 * Math.PI * t) / 4.1 + p.seed * 2) * 4 * u * flut;
  rot += Math.sin((2 * Math.PI * t) / 3.4 + p.seed) * 1.6 * flut;

  // pega: voa em arco até a mão e fica preso nela
  if (preso > 0) {
    const m = mao();
    ox = mix(ox, m.x, preso);
    oy = mix(oy, m.y, preso) - Math.sin(Math.PI * preso) * S * 0.3;
    rot += rotP * preso;
  }
  for (const a of da('cresce')) esc *= 1 + 0.38 * k(a, 0.4, ease.trava);
  for (const a of da('encolhe')) esc *= 1 - 0.42 * k(a, 0.4, ease.trava);
  for (const a of da('gira')) rot += 360 * k(a, 0.6, ease.camera);
  for (const a of da('treme')) {
    const x = t - a.t;
    if (x >= 0 && x < 0.7) {
      ox += 16 * u * Math.exp(-4.5 * x) * Math.sin(2 * Math.PI * 13 * x);
      rot += 3.5 * Math.exp(-4.5 * x) * Math.sin(2 * Math.PI * 11 * x + 1);
    }
  }
  if (agitando > 0) {
    rot += 24 * agitando * Math.sin(2 * Math.PI * 7 * xa);
    oy += 20 * u * agitando * Math.sin(2 * Math.PI * 7 * xa + 1.2);
  }
  oy -= S * 0.5 * k(aErgue, 0.45, ease.trava);
  const kD = k(aDespeja, 0.45, ease.camera) - k(aDespeja, 0.4, ease.camera, 1.5);
  rot += sinal * 118 * kD;
  let opO = c01(to / 0.1) * (1 - kS);
  if (aJoga && t >= aJoga.t) {
    const x = t - aJoga.t;
    ox += sinal * S * 2.4 * x;
    oy += -S * 2.2 * x + S * 3.4 * x * x;
    rot += sinal * 520 * x;
    opO *= 1 - c01((x - 0.55) / 0.3);
  }
  const multi = da('multiplica')[0];
  if (multi) esc *= 1 - 0.3 * k(multi, 0.35);
  const quebra = da('quebra')[0];
  const kQ = quebra ? c01((t - quebra.t) / 0.9) : 0;
  const acende = da('acende')[0];
  const kA = k(acende, 0.35);
  const halo = acende?.cor ?? cor.secundaria;

  // ---------------------------------------------------------------- corpo (imagem + tinturas + líquido)
  const src = p.src ? staticFile(p.src) : null;
  const mascara: React.CSSProperties = src
    ? {
        WebkitMaskImage: `url(${src})`,
        maskImage: `url(${src})`,
        WebkitMaskSize: 'contain',
        maskSize: 'contain',
        WebkitMaskRepeat: 'no-repeat',
        maskRepeat: 'no-repeat',
        WebkitMaskPosition: 'center',
        maskPosition: 'center',
      }
    : {};
  const contorno = Math.max(2, 5 * u);
  const adesivoBase =
    `drop-shadow(${contorno}px 0 0 ${papel}) drop-shadow(-${contorno}px 0 0 ${papel}) drop-shadow(0 ${contorno}px 0 ${papel}) ` +
    `drop-shadow(0 -${contorno}px 0 ${papel}) drop-shadow(0 ${16 * u}px ${20 * u}px rgba(0,0,0,0.5))`;
  const pulso = 0.85 + 0.15 * Math.sin(2 * Math.PI * 1.4 * t);
  const adesivo =
    adesivoBase +
    (kA > 0.01 ? ` drop-shadow(0 0 ${46 * u * kA * pulso}px ${alfa(halo, 0.95 * kA)}) drop-shadow(0 0 ${18 * u * kA}px ${alfa(halo, 0.9 * kA)})` : '');

  // nível do líquido: enche sobe, esvazia/despeja desce
  let nivel = 0;
  let corLiquido = cor.destaque;
  for (const a of p.acoes) {
    if (a.tipo === 'enche') {
      nivel += (0.86 - nivel) * k(a, 0.9, ease.suave);
      if (t >= a.t) corLiquido = a.cor ?? corLiquido;
    } else if (a.tipo === 'esvazia') nivel -= nivel * k(a, 0.8, ease.suave);
    else if (a.tipo === 'despeja') nivel -= nivel * k(a, 1.1, ease.suave, 0.3);
  }
  // o líquido balança mais logo depois de qualquer ação
  let agito = 1.4;
  for (const a of p.acoes) {
    const x = t - a.t;
    if (x >= 0) agito += (a.tipo === 'agita' ? 9 : 4) * Math.exp(-1.8 * x);
  }
  const onda = (y0: number) => {
    const pts: string[] = [];
    for (let i = 0; i <= 14; i++) {
      const x = i / 14;
      const y = y0 + agito * Math.sin(x * Math.PI * 3 + t * 8) + agito * 0.4 * Math.sin(x * Math.PI * 7 - t * 11);
      pts.push(`${(x * 100).toFixed(1)}% ${y.toFixed(2)}%`);
    }
    return `polygon(${pts.join(', ')}, 100% 100%, 0% 100%)`;
  };
  const bolhas = Array.from({ length: 7 }, () => ({ x: 0.25 + 0.5 * r(), v: 0.25 + 0.35 * r(), f: r(), d: 0.03 + 0.035 * r() }));

  const corpo = (lado: number) => (
    <div style={{ position: 'relative', width: lado, height: lado, isolation: 'isolate' }}>
      {src ? (
        <Img src={src} style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'contain' }} />
      ) : (
        <Icone nome={p.icone ?? 'estrela'} x={lado / 2} y={lado / 2} tam={lado * 0.62} inicio={0} seed={p.seed} termico={false} cor={da('cor').reduce((c, a) => (t >= a.t + 0.15 ? a.cor ?? c : c), cor.texto)} moldura={null} u={u} />
      )}
      {src &&
        da('cor').map((a, i) => {
          const kk = k(a, 0.5, ease.suave);
          const brilho = c01((t - a.t - 0.2) / 0.6);
          return (
            <React.Fragment key={`c${i}`}>
              <div style={{ position: 'absolute', inset: 0, background: a.cor ?? cor.destaque, mixBlendMode: 'color', opacity: 0.92, clipPath: `inset(${(1 - kk) * 100}% 0 0 0)`, ...mascara }} />
              {brilho > 0 && brilho < 1 ? (
                <div style={{ position: 'absolute', inset: 0, background: `linear-gradient(115deg, transparent ${brilho * 130 - 30}%, rgba(255,255,255,0.75) ${brilho * 130 - 15}%, transparent ${brilho * 130}%)`, ...mascara }} />
              ) : null}
            </React.Fragment>
          );
        })}
      {src && nivel > 0.01 && (
        <>
          <div style={{ position: 'absolute', inset: 0, background: corLiquido, mixBlendMode: 'multiply', opacity: 0.78, clipPath: onda(100 - nivel * 100), ...mascara }} />
          <div style={{ position: 'absolute', inset: 0, clipPath: onda(100 - nivel * 100), ...mascara }}>
            {bolhas.map((b, i) => {
              const y = ((t * b.v + b.f) % 1) * nivel;
              return <div key={i} style={{ position: 'absolute', left: `${b.x * 100}%`, bottom: `${y * 100}%`, width: lado * b.d, height: lado * b.d, borderRadius: '50%', background: 'rgba(255,255,255,0.55)', transform: `translateX(${Math.sin(t * 5 + i) * lado * 0.012}px)` }} />;
            })}
          </div>
        </>
      )}
    </div>
  );

  // ---------------------------------------------------------------- partículas
  const particulas: React.ReactNode[] = [];
  const jorro = (chave: string, t0: number, n: number, x0: number, y0: number, tom: string, cone: [number, number], forca: number, grav: number, dur: number, tam: number) => {
    const x = t - t0;
    for (let i = 0; i < n; i++) {
      // sorteia sempre (mesmo fora da janela) para o rng não mudar as outras peças de quadro para quadro
      const ang = (cone[0] + (cone[1] - cone[0]) * r()) * RAD;
      const v = forca * (0.45 + 0.55 * r());
      const atraso = r() * dur * 0.35;
      const raio = tam * (0.5 + 0.8 * r());
      const xx = x - atraso;
      if (x < 0 || x > dur || xx < 0) continue;
      particulas.push(
        <div key={`${chave}${i}`} style={{ position: 'absolute', left: x0 + Math.cos(ang) * v * xx - raio, top: y0 + Math.sin(ang) * v * xx + grav * xx * xx - raio, width: raio * 2, height: raio * 2, borderRadius: '50%', background: tom, opacity: 1 - c01(xx / (dur - atraso)) ** 2 }} />,
      );
    }
  };
  // poeira ao pousar
  if (p.entrada === 'cai') jorro('po', tObj + 0.38, 12, repX, repY + S * 0.42, alfa(papel, 0.85), [150, 390], S * 1.1, S * 0.2, 0.6, 9 * u);
  // respingos ao encher
  for (const [i, a] of da('enche').entries()) jorro(`re${i}`, a.t, 12, ox, oy - S * 0.3, a.cor ?? cor.destaque, [215, 325], S * 1.5, S * 2.6, 0.75, 9 * u);
  // fio de líquido que cai no despeja
  if (aDespeja) jorro('de', aDespeja.t + 0.3, 46, ox + sinal * S * 0.42, oy - S * 0.02, corLiquido, [80, 100], S * 0.5, S * 2.4, 1.3, 11 * u);
  // gotas que escapam ao agitar
  if (aAgita && nivel > 0.05) jorro('ag', aAgita.t + 0.05, 14, ox, oy - S * 0.4, corLiquido, [200, 340], S * 1.7, S * 2.8, 0.8, 8 * u);
  // estilhaços
  if (quebra) jorro('es', quebra.t, 18, ox, oy, alfa(papel, 0.95), [0, 360], S * 1.6, S * 1.8, 0.8, 8 * u);
  // rastro do arremesso
  if (aJoga) jorro('jo', aJoga.t, 10, ox, oy, alfa(papel, 0.8), [0, 360], S * 0.5, 0, 0.5, 7 * u);

  const risca = da('risca')[0];
  const kR = k(risca, 0.35);
  const nCopias = multi ? Math.max(2, Math.min(10, multi.n ?? 6)) : 0;
  const base: React.CSSProperties = { position: 'absolute', left: ox - S / 2, top: oy - S / 2, width: S, height: S };

  return (
    <AbsoluteFill style={{ opacity: c01(f / 3) * (1 - kS) }}>
      <Fontes />
      {/* raios girando atrás do objeto aceso */}
      {kA > 0.01 && (
        <svg width={p.largura} height={p.altura} style={{ position: 'absolute', inset: 0, opacity: 0.85 * kA * opO }}>
          <g transform={`rotate(${t * 38} ${ox} ${oy})`}>
            {Array.from({ length: 14 }, (_, i) => {
              const a = (i / 14) * Math.PI * 2;
              const r0 = S * (0.5 + 0.05 * Math.sin(t * 6 + i));
              const r1 = S * (0.72 + 0.12 * (i % 2) + 0.05 * Math.sin(t * 4 + i * 2));
              return <line key={i} x1={ox + Math.cos(a) * r0} y1={oy + Math.sin(a) * r0} x2={ox + Math.cos(a) * r1} y2={oy + Math.sin(a) * r1} stroke={halo} strokeWidth={(i % 2 ? 7 : 12) * u} strokeLinecap="round" />;
            })}
          </g>
        </svg>
      )}
      {/* personagem: entra andando, respira, se inclina */}
      {per && (
        <div style={{ position: 'absolute', left: peX - Wc / 2, top: peY - Hc, width: Wc, height: Hc, transformOrigin: '50% 100%', transform: `translate(${pdx}px, ${pdy}px) rotate(${rotP}deg) scaleX(${sinal})`, filter: adesivoBase, opacity: c01((t - per.t) / 0.12) }}>
          <Img src={staticFile(per.src)} style={{ width: '100%', height: '100%', objectFit: 'contain' }} />
        </div>
      )}
      {/* cópias (multiplica): saltam do objeto e ficam em órbita lenta */}
      {multi &&
        Array.from({ length: nCopias }, (_, i) => {
          const kk = ease.trava(c01((f - multi.t * p.fps - i * 2) / (0.3 * p.fps)));
          const des = (r() - 0.5) * 0.3;
          const rr = 0.62 + 0.1 * r();
          const lado = S * (0.3 + 0.08 * r());
          const giro = (r() - 0.5) * 30;
          if (kk <= 0) return null;
          const ang = (i / nCopias) * Math.PI * 2 - Math.PI / 2 + des + (t - multi.t) * 0.32;
          const raio = S * rr * (1 + 0.04 * Math.sin(t * 2.2 + i));
          return (
            <div key={`m${i}`} style={{ position: 'absolute', left: ox + Math.cos(ang) * raio * kk - lado / 2, top: oy + Math.sin(ang) * raio * 0.82 * kk - lado / 2, width: lado, height: lado, transform: `scale(${0.3 + 0.7 * kk}) rotate(${giro + Math.sin(t * 2 + i) * 8}deg)`, opacity: c01(kk * 3) * opO, filter: src ? adesivo : undefined }}>
              {corpo(lado)}
            </div>
          );
        })}
      <div style={{ ...base, opacity: opO, transform: `rotate(${rot}deg) scale(${esc}, ${esc * escY})`, transformOrigin: escY !== 1 ? '50% 100%' : '50% 50%', filter: src ? adesivo : undefined }}>
        {kQ <= 0
          ? corpo(S)
          : PECAS.map((clip, i) => {
              const kk = ease.entrada(kQ);
              return (
                <div key={`q${i}`} style={{ position: 'absolute', inset: 0, clipPath: clip, transform: `translate(${VOO[i].x * S * kk}px, ${VOO[i].y * S * kk * (0.6 + kk)}px) rotate(${VOO[i].r * kk}deg)`, opacity: 1 - c01((kQ - 0.6) / 0.4) }}>
                  {corpo(S)}
                </div>
              );
            })}
        {risca && (
          <svg width={S} height={S} viewBox="0 0 100 100" style={{ position: 'absolute', inset: 0, overflow: 'visible' }}>
            {[
              ['M 14 16 Q 48 44 86 88', 0],
              ['M 88 14 Q 52 50 12 86', 0.45],
            ].map(([d, a], i) => (
              <path key={i} d={d as string} fill="none" stroke={cor.destaque} strokeWidth={9} strokeLinecap="round" pathLength={1} strokeDasharray={1} strokeDashoffset={1 - c01((kR - (a as number)) / 0.55)} />
            ))}
          </svg>
        )}
      </div>
      {particulas}
      {p.rotulo ? (
        <div style={{ position: 'absolute', left: 0, width: p.largura, top: H + 6 * u, display: 'flex', justifyContent: 'center' }}>
          <div style={{ fontFamily: fonte.rotulo, fontWeight: 800, fontSize: 34 * u, letterSpacing: '0.04em', textTransform: 'uppercase', color: cor.texto, background: cor.tinta, padding: `${8 * u}px ${18 * u}px`, boxShadow: `${5 * u}px ${5 * u}px 0 ${cor.destaque}`, transformOrigin: 'left center', transform: `scaleX(${ease.saida(c01((to - 0.25) / 0.3))})`, whiteSpace: 'nowrap' }}>
            {p.rotulo}
          </div>
        </div>
      ) : null}
    </AbsoluteFill>
  );
};
