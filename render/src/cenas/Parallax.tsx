import React from 'react';
import { AbsoluteFill, interpolate, staticFile, useCurrentFrame } from 'remotion';
import { clamp, ease } from '../comp/tokens';
import type { PropsCena } from '../tipos';

/**
 * Foto em parallax 2.5D. imagens = [foto (já com o tratamento de cor do canal), mapa de deslocamento].
 * O mapa (gerado em pipeline/profundidade.py + montar.py) codifica profundidade relativa ao plano focal
 * nos canais R (x) e G (y) na direção escolhida. feDisplacementMap desloca cada pixel proporcionalmente:
 * o plano focal fica parado, o que está à frente e atrás desliza em sentidos opostos. Sem recortes, sem buracos.
 * amplitude = metade do curso total (curso 2,5–4% da largura; acima disso aparecem "fantasmas" nas bordas).
 */
export const Parallax: React.FC<{ p: PropsCena }> = ({ p }) => {
  const f = useCurrentFrame();
  const W = p.largura;
  const H = p.altura;
  const d = p.dados;
  const [foto, mapa] = p.imagens ?? [];
  const asp = p.aspectos?.[0] ?? W / H;
  const k = interpolate(f, [0, p.frames - 1], [0, 1], { ...clamp, easing: ease.padrao });
  const amp: number = (d.amplitude ?? 0.03) * W;
  const desloc = amp * (k * 2 - 1); // de -amp a +amp
  const dolly: number = d.dolly ?? 0.05;
  const z = d.sentido_dolly === 'sai' ? 1 + dolly * (1 - k) : 1 + dolly * k;
  // a foto cobre o quadro com folga (overscan) para o deslocamento nunca mostrar borda
  const over = 1.08;
  const iw = asp > W / H ? H * asp * over : W * over;
  const ih = iw / asp;
  const fx: number = d.foco_x ?? 0.5;
  const fy: number = d.foco_y ?? 0.5;
  const x = W / 2 - iw * fx;
  const y = H / 2 - ih * fy;
  const ox = Math.max(Math.min(x, 0), W - iw);
  const oy = Math.max(Math.min(y, 0), H - ih);
  return (
    <AbsoluteFill style={{ background: '#000', overflow: 'hidden' }}>
      <AbsoluteFill style={{ transform: `scale(${z})`, transformOrigin: `${fx * 100}% ${fy * 100}%` }}>
        <svg width={W} height={H}>
          <defs>
            <filter id="px" x={ox} y={oy} width={iw} height={ih} filterUnits="userSpaceOnUse" colorInterpolationFilters="sRGB">
              <feImage href={staticFile(mapa)} x={ox} y={oy} width={iw} height={ih} preserveAspectRatio="none" result="mapa" />
              <feDisplacementMap in="SourceGraphic" in2="mapa" scale={desloc} xChannelSelector="R" yChannelSelector="G" />
            </filter>
          </defs>
          <g filter="url(#px)">
            <image href={staticFile(foto)} x={ox} y={oy} width={iw} height={ih} preserveAspectRatio="none" />
          </g>
        </svg>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
