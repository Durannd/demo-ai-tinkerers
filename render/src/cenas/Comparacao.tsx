import React from 'react';
import { AbsoluteFill, Img, interpolate, staticFile, useCurrentFrame } from 'remotion';
import { Fundo, quadro, tempoDe, Textura } from '../comp/Base';
import { Coreografia } from '../comp/Movimento';
import { num } from '../comp/i18n';
import { alfa, clamp, cor, ease, escolher, fonte, q, rng, TEMPO } from '../comp/tokens';
import type { PropsCena } from '../tipos';

type Lado = { rotulo?: string; valor?: number; unidade?: string; ancora?: string };

/**
 * Comparação. O modo sai do conteúdo:
 *  2 imagens → "lado_a_lado" (split com fio, B entra com wipe) ou "antes_depois" (cortina que varre);
 *  sem imagens → "numeros" (duas cifras com barras proporcionais aos valores reais).
 */
export const Comparacao: React.FC<{ p: PropsCena }> = ({ p }) => {
  const f = useCurrentFrame();
  const r = rng(p.seed);
  const d = p.dados;
  const W = p.largura;
  const H = p.altura;
  const u = H / 1080;
  const a: Lado = d.a ?? {};
  const b: Lado = d.b ?? {};
  const imgs = p.imagens ?? [];
  const modo: string = d.modo ?? (imgs.length >= 2 ? escolher(r, ['lado_a_lado', 'antes_depois']) : 'numeros');
  // v4: cada lado entra quando é DITO (âncora explícita → rótulo → valor); A nunca antes do atraso inicial
  const tA = Math.max(p.alca_antes + q(TEMPO.atrasoInicial, p.fps), quadro(p, tempoDe(p.palavras, [a.ancora, a.rotulo, a.valor != null ? String(a.valor) : null], 0.1)));
  const tBdito = tempoDe(p.palavras, [b.ancora, b.rotulo, b.valor != null ? String(b.valor) : null], -1, (tA - p.alca_antes) / p.fps);
  const tB = Math.max(tA + q(TEMPO.entradaLonga, p.fps), quadro(p, tBdito >= 0 ? tBdito : Math.max(0.8, (p.corpo / p.fps) * 0.45)));
  const kB = interpolate(f, [tB - q(TEMPO.antecipacao, p.fps), tB + q(TEMPO.entrada, p.fps)], [0, 1], { ...clamp, easing: ease.padrao });
  const deriva = 1.04 + f * 0.0002;

  const rotulo = (txt: string | undefined, x: number, alinhar: 'left' | 'right', t: number, some?: number) =>
    txt ? (() => {
      const k = interpolate(f, [t, t + q(TEMPO.entradaCurta, p.fps)], [0, 1], { ...clamp, easing: ease.saida });
      const sai = some !== undefined ? 1 - interpolate(f, [some, some + q(TEMPO.saida, p.fps)], [0, 1], clamp) : 1;
      return (
        <div
          style={{
            position: 'absolute', bottom: H * 0.08, [alinhar]: x, display: 'flex', alignItems: 'stretch',
            flexDirection: alinhar === 'right' ? 'row-reverse' : 'row', opacity: Math.min(1, k * 1.5) * sai,
            transform: `translateY(${(1 - k) * 16 * u}px)`, boxShadow: '0 10px 30px rgba(0,0,0,0.35)',
          }}
        >
          <div style={{ width: 6 * u, background: alinhar === 'left' ? cor.neutro : cor.destaque }} />
          <div
            style={{
              fontFamily: fonte.rotulo, fontWeight: 600, fontSize: 28 * u, letterSpacing: '0.22em', textTransform: 'uppercase',
              color: cor.texto, padding: `${12 * u}px ${22 * u}px`, background: alfa(cor.tinta, 0.82), whiteSpace: 'nowrap',
              clipPath: `inset(0 ${alinhar === 'left' ? (1 - k) * 100 : 0}% 0 ${alinhar === 'right' ? (1 - k) * 100 : 0}%)`,
            }}
          >
            {txt}
          </div>
        </div>
      );
    })() : null;

  if (modo === 'lado_a_lado' && imgs.length >= 2) {
    const meio = W / 2;
    return (
      <AbsoluteFill style={{ background: cor.tinta }}>
        <Coreografia p={p} cx={meio} cy={H * 0.5} intensidade={0.7}>
          <div style={{ position: 'absolute', left: 0, top: 0, width: meio, height: H, overflow: 'hidden' }}>
            <Img src={staticFile(imgs[0])} style={{ width: '100%', height: '100%', objectFit: 'cover', transform: `scale(${deriva})` }} />
          </div>
          <div style={{ position: 'absolute', left: meio, top: 0, width: meio, height: H, overflow: 'hidden', clipPath: `inset(0 0 0 ${(1 - kB) * 100}%)` }}>
            <Img src={staticFile(imgs[1])} style={{ width: '100%', height: '100%', objectFit: 'cover', transform: `scale(${deriva})` }} />
          </div>
          <div style={{ position: 'absolute', left: meio - 2 * u, top: 0, width: 4 * u, height: H * kB, background: cor.destaque }} />
          {rotulo(a.rotulo, W * 0.04, 'left', tA)}
          {rotulo(b.rotulo, W * 0.04, 'right', tB + q(TEMPO.atrasoInicial, p.fps))}
        </Coreografia>
      </AbsoluteFill>
    );
  }
  if (modo === 'antes_depois' && imgs.length >= 2) {
    const x = W * (1 - kB);
    return (
      <AbsoluteFill style={{ background: cor.tinta }}>
        <Coreografia p={p} cx={W / 2} cy={H * 0.5} intensidade={0.7}>
          <Img src={staticFile(imgs[0])} style={{ position: 'absolute', width: '100%', height: '100%', objectFit: 'cover', transform: `scale(${deriva})` }} />
          <AbsoluteFill style={{ clipPath: `inset(0 0 0 ${x}px)` }}>
            <Img src={staticFile(imgs[1])} style={{ width: '100%', height: '100%', objectFit: 'cover', transform: `scale(${deriva})` }} />
          </AbsoluteFill>
          {kB > 0 && kB < 1 ? <div style={{ position: 'absolute', left: x - 2 * u, top: 0, width: 4 * u, height: H, background: cor.texto, boxShadow: '0 0 20px rgba(0,0,0,0.6)' }} /> : null}
          {rotulo(a.rotulo, W * 0.04, 'left', tA, tB)}
          {rotulo(b.rotulo, W * 0.04, 'right', tB + q(TEMPO.atrasoInicial, p.fps))}
        </Coreografia>
      </AbsoluteFill>
    );
  }
  // números
  const va = Number(a.valor ?? 0);
  const vb = Number(b.valor ?? 0);
  const maior = Math.max(Math.abs(va), Math.abs(vb), 1);
  // v3: duas colunas que crescem de uma linha de base comum (escala honesta: altura ∝ valor real);
  // a cifra viaja no topo da coluna contando em algarismos tabulares; rótulo abaixo da base;
  // ao fim, um colchete entre as colunas mostra a razão (≈ N×).
  const kA = interpolate(f, [tA, tA + q(TEMPO.entradaLonga, p.fps)], [0, 1], { ...clamp, easing: ease.padrao });
  const kB2 = interpolate(f, [tB, tB + q(TEMPO.entradaLonga, p.fps)], [0, 1], { ...clamp, easing: ease.padrao });
  const base = H * 0.78;
  const hMax = H * 0.46;
  const larg = W * 0.15;
  const kBase = interpolate(f, [tA - q(TEMPO.entrada, p.fps), tA], [0, 1], { ...clamp, easing: ease.padrao });
  const coluna = (l: Lado, v: number, k: number, cx: number, c: string, i: number) => {
    const h = Math.max(4 * u, hMax * (Math.abs(v) / maior)) * k;
    const kr = interpolate(f, [(i ? tB : tA) - q(TEMPO.antecipacao, p.fps), (i ? tB : tA) + q(TEMPO.entradaCurta, p.fps)], [0, 1], { ...clamp, easing: ease.saida });
    return (
      <React.Fragment key={i}>
        <div
          style={{
            position: 'absolute', left: cx - larg / 2, top: base - h, width: larg, height: h,
            background: `linear-gradient(180deg, ${c} 0%, ${c} 70%, ${alfa(i ? cor.destaque_sombra : cor.neutro_sombra, 1)} 100%)`,
            
          }}
        >
          <div style={{ position: 'absolute', left: 0, right: 0, top: 0, height: Math.max(2, 2 * u), background: 'rgba(255,255,255,0.35)' }} />
        </div>
        <div
          style={{
            position: 'absolute', left: cx - W * 0.2, width: W * 0.4, top: base - h - 150 * u, textAlign: 'center',
            fontFamily: fonte.titulo, fontWeight: 700, fontSize: 140 * u, lineHeight: 1, letterSpacing: '-0.03em',
            color: i ? cor.texto : cor.texto_suave, fontVariantNumeric: 'tabular-nums lining-nums', opacity: kr,
          }}
        >
          {num(Math.round(v * k))}
          {l.unidade ? <span style={{ fontStyle: 'italic', fontWeight: 400, fontSize: 48 * u, marginLeft: '0.2em', letterSpacing: 0 }}>{l.unidade}</span> : null}
        </div>
        <div
          style={{
            position: 'absolute', left: cx - W * 0.2, width: W * 0.4, top: base + 28 * u, textAlign: 'center', fontFamily: fonte.rotulo,
            fontWeight: 600, fontSize: 28 * u, letterSpacing: '0.28em', marginRight: '-0.28em', textTransform: 'uppercase',
            color: i ? cor.texto : cor.texto_suave, opacity: kr, transform: `translateY(${(1 - kr) * 10 * u}px)`,
          }}
        >
          {l.rotulo}
        </div>
      </React.Fragment>
    );
  };
  const xa = W * 0.33;
  const xb = W * 0.67;
  const razao = va && vb ? Math.max(Math.abs(va), Math.abs(vb)) / Math.min(Math.abs(va), Math.abs(vb)) : 0;
  const tR = tB + q(TEMPO.entradaLonga, p.fps) + q(TEMPO.pausaClimax, p.fps);
  const kR = interpolate(f, [tR, tR + q(TEMPO.entrada, p.fps)], [0, 1], { ...clamp, easing: ease.saida });
  return (
    <AbsoluteFill>
      <Fundo imagem={p.fundo} escurecer={0.86} />
      {/* linhas de grade horizontais muito discretas */}
      {[0.25, 0.5, 0.75, 1].map((g) => (
        <div key={g} style={{ position: 'absolute', left: W * 0.14, width: W * 0.72 * kBase, top: base - hMax * g, height: 1, background: alfa(cor.texto, 0.06) }} />
      ))}
      <Coreografia p={p} cx={W / 2} cy={base} intensidade={0.85}>
      {coluna(a, va, kA, xa, cor.neutro, 0)}
      {coluna(b, vb, kB2, xb, cor.destaque, 1)}
      <div style={{ position: 'absolute', left: W * 0.12, top: base, width: W * 0.76 * kBase, height: Math.max(2, 2 * u), background: alfa(cor.texto, 0.45) }} />
      {razao >= 1.2 ? (
        <div style={{ position: 'absolute', left: W / 2 - W * 0.1, width: W * 0.2, top: base - hMax * 0.62, textAlign: 'center', opacity: kR, transform: `translateY(${(1 - kR) * 14 * u}px)` }}>
          <div style={{ fontFamily: fonte.titulo, fontWeight: 700, fontStyle: 'italic', fontSize: 84 * u, color: cor.secundaria, lineHeight: 1, fontVariantNumeric: 'lining-nums' }}>
            ≈{num(razao, { maximumFractionDigits: razao < 10 ? 1 : 0 })}×
          </div>
          <div style={{ margin: `${12 * u}px auto 0`, width: W * 0.12 * kR, height: Math.max(2, 2 * u), background: cor.secundaria }} />
        </div>
      ) : null}
      </Coreografia>
      <Textura />
    </AbsoluteFill>
  );
};
