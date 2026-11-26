import React, { useEffect, useState } from 'react';
import { AbsoluteFill, cancelRender, continueRender, delayRender, Easing, Img, interpolate, staticFile, useCurrentFrame } from 'remotion';
import { alfa, cor, fonte, rgbDe } from './tokens';
import type { Palavra, PropsCena } from '../tipos';

// Padrão adaptado do harness grio-motion (Base.tsx → Fonts): segura o render até as fontes carregarem.
const FACES = [
  ['Source Serif 4', 'source-serif-4-400-normal', 400, 'normal'],
  ['Source Serif 4', 'source-serif-4-600-normal', 600, 'normal'],
  ['Source Serif 4', 'source-serif-4-700-normal', 700, 'normal'],
  ['Source Serif 4', 'source-serif-4-400-italic', 400, 'italic'],
  ['Source Serif 4', 'source-serif-4-600-italic', 600, 'italic'],
  ['Inter', 'inter-400-normal', 400, 'normal'],
  ['Inter', 'inter-600-normal', 600, 'normal'],
  ['Inter', 'inter-800-normal', 800, 'normal'],
  ['Courier Prime', 'courier-prime-400-normal', 400, 'normal'],
  ['Courier Prime', 'courier-prime-700-normal', 700, 'normal'],
  // tokens alternativos do canal
  ['Barlow Condensed', 'barlow-condensed-500-normal', 400, 'normal'],
  ['Barlow Condensed', 'barlow-condensed-600-normal', 600, 'normal'],
  ['Barlow Condensed', 'barlow-condensed-700-normal', 700, 'normal'],
  ['Barlow Condensed', 'barlow-condensed-600-italic', 400, 'italic'],
  ['Barlow Condensed', 'barlow-condensed-600-italic', 600, 'italic'],
  ['IBM Plex Sans', 'ibm-plex-sans-400-normal', 400, 'normal'],
  ['IBM Plex Sans', 'ibm-plex-sans-600-normal', 600, 'normal'],
  ['IBM Plex Sans', 'ibm-plex-sans-700-normal', 800, 'normal'],
  ['IBM Plex Mono', 'ibm-plex-mono-400-normal', 400, 'normal'],
  ['IBM Plex Mono', 'ibm-plex-mono-700-normal', 700, 'normal'],
] as const;

const CSS = FACES.map(
  ([fam, arq, peso, estilo]) =>
    `@font-face{font-family:"${fam}";src:url(${staticFile(`fontes/${arq}.ttf`)}) format("truetype");font-weight:${peso};font-style:${estilo}}`,
).join('\n');

export const Fontes: React.FC = () => {
  const [h] = useState(() => delayRender('fontes'));
  useEffect(() => {
    Promise.all(FACES.map(([fam, , peso, estilo]) => document.fonts.load(`${estilo} ${peso} 40px "${fam}"`, 'Ação 1919')))
      .then(() => continueRender(h))
      .catch((e) => cancelRender(e));
  }, [h]);
  return <style>{CSS}</style>;
};

/** Fundo: imagem vizinha desfocada e escurecida (nunca igual entre cenas) ou tinta com luz que deriva. */
export const Fundo: React.FC<{ imagem?: string | null; escurecer?: number; luzX?: number; luzY?: number; papel?: boolean }> = ({
  imagem,
  escurecer = 0.78,
  luzX = 0.4,
  luzY = 0.45,
  papel = false,
}) => {
  const f = useCurrentFrame();
  // luz que DERIVA num só sentido (como câmera lenta), sem oscilar — nada de "respirar" ocioso
  const gx = (luzX + Math.min(0.06, f * 0.00015)) * 100;
  const gy = luzY * 100;
  const base = papel ? cor.papel : cor.tinta;
  return (
    <AbsoluteFill style={{ background: base }}>
      {imagem ? (
        <AbsoluteFill style={{ transform: `scale(${1.08 + f * 0.0003})` }}>
          <Img
            src={staticFile(imagem)}
            style={{ width: '100%', height: '100%', objectFit: 'cover', filter: 'grayscale(1) blur(28px)', opacity: 1 - escurecer }}
          />
        </AbsoluteFill>
      ) : null}
      <AbsoluteFill
        style={{
          background: papel
            ? `radial-gradient(70% 60% at ${gx}% ${gy}%, rgba(255,250,240,0.55) 0%, rgba(255,250,240,0) 70%)`
            : `radial-gradient(55% 45% at ${gx}% ${gy}%, rgba(70,74,84,0.35) 0%, rgba(70,74,84,0) 70%)`,
        }}
      />
    </AbsoluteFill>
  );
};

/** Movimento de câmera contínuo e sutil (adaptado do Drift do grio-motion): nada fica 100% parado. */
export const Deriva: React.FC<{ children: React.ReactNode; intensidade?: number; direcao?: number }> = ({
  children,
  intensidade = 1,
  direcao = 1,
}) => {
  const f = useCurrentFrame();
  const s = 1 + 0.0004 * intensidade * f;
  const x = direcao * f * 0.08 * intensidade;
  return <AbsoluteFill style={{ transform: `translateX(${x}px) scale(${s})` }}>{children}</AbsoluteFill>;
};

/** Converte segundos (relativos ao corpo da cena) em quadro do render (que inclui a alça de entrada). */
export const quadro = (p: Pick<PropsCena, 'alca_antes' | 'fps'>, seg: number) => Math.round(p.alca_antes + seg * p.fps);

const normPal = (s: string) =>
  s
    .toLowerCase()
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .replace(/[^\w%]/g, '');

/**
 * Onde uma expressão é dita (segundos, relativos ao corpo), ou null. Casa a FRASE inteira em sequência
 * (sem acento/caixa; a última palavra pode ser prefixo: "cavalo" casa "cavalos"); se a frase não aparece,
 * tenta só a primeira palavra. `depois`: só aceita ocorrências a partir desse tempo (eventos em ordem).
 */
export const acharNaFala = (palavras: Palavra[], expr?: string, depois = -Infinity): number | null => {
  if (!expr) return null;
  const alvo = String(expr).split(/[\s\-–—/]+/).map(normPal).filter(Boolean);
  if (!alvo.length) return null;
  const nar = palavras.map((w) => normPal(w.texto));
  const casa = (a: string, b: string, ultimo: boolean) => a === b || (ultimo && b.length >= 3 && a.startsWith(b));
  for (const n of [alvo.length, 1]) {
    for (let i = 0; i + n <= nar.length; i++) {
      if (palavras[i].ini < depois) continue;
      let ok = true;
      for (let k = 0; k < n && ok; k++) ok = casa(nar[i + k], alvo[k], k === n - 1);
      if (ok) return palavras[i].ini;
    }
  }
  return null;
};

/** Quando a palavra-âncora é dita (segundos, relativos ao corpo). Busca sem acento/caixa. */
export const tempoDaAncora = (palavras: Palavra[], ancora?: string, padrao = 0.25, depois = -Infinity): number =>
  acharNaFala(palavras, ancora, depois) ?? padrao;

/** Primeiro candidato que é dito na narração (âncora explícita, depois rótulo, ano...), senão o padrão. */
export const tempoDe = (palavras: Palavra[], candidatos: (string | undefined | null)[], padrao: number, depois = -Infinity): number => {
  for (const c of candidatos) {
    const t = acharNaFala(palavras, c ?? undefined, depois);
    if (t !== null) return t;
  }
  return padrao;
};

// ---------------------------------------------------------------------------------------------
// Acabamento gráfico compartilhado (v3): textura, vinheta e rótulo-chapéu.
// O que é estático vira data URL (rasterizado uma vez pelo Chrome) para não pesar por quadro.

const svgUrl = (s: string) => `data:image/svg+xml;charset=utf-8,${encodeURIComponent(s)}`;

/** Ruído fractal monocromático (grão de filme / fibra de papel). Tile 512px, repetido. */
const ruido = (freq: number, alfa: number, claro: boolean, w = 512, h = 512) =>
  svgUrl(
    `<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}"><filter id="n"><feTurbulence type="fractalNoise" baseFrequency="${freq}" numOctaves="3" stitchTiles="stitch"/><feColorMatrix values="0 0 0 0 ${claro ? 1 : 0} 0 0 0 0 ${claro ? 1 : 0} 0 0 0 0 ${claro ? 1 : 0} 0 0 0 ${alfa} 0"/></filter><rect width="${w}" height="${h}" filter="url(#n)"/></svg>`,
  );
void ruido; // (mantido para usos estáticos; a textura por quadro usa bitmaps abaixo)

/**
 * Ruído como BITMAP gerado uma vez por aba (canvas → PNG). Um SVG com feTurbulence como fundo é
 * re-rasterizado a cada repintura e derrubava a cena para metade da velocidade.
 * w×h = tamanho do bitmap; a fibra é gerada pequena e ampliada com suavização (manchas largas).
 */
const bitmapRuido = (w: number, h: number, claro: boolean, alfa: number, semente: number): string => {
  if (typeof document === 'undefined') return '';
  const c = document.createElement('canvas');
  c.width = w;
  c.height = h;
  const ctx = c.getContext('2d')!;
  const img = ctx.createImageData(w, h);
  let t = semente >>> 0;
  const rnd = () => {
    t += 0x6d2b79f5;
    let r = Math.imul(t ^ (t >>> 15), 1 | t);
    r ^= r + Math.imul(r ^ (r >>> 7), 61 | r);
    return ((r ^ (r >>> 14)) >>> 0) / 4294967296;
  };
  for (let i = 0; i < w * h; i++) {
    const v = rnd();
    img.data[i * 4] = img.data[i * 4 + 1] = img.data[i * 4 + 2] = claro ? 255 : 0;
    img.data[i * 4 + 3] = Math.round(255 * alfa * v * v);
  }
  ctx.putImageData(img, 0, 0);
  return c.toDataURL('image/png');
};
const cacheRuido: Record<string, string> = {};
const textura = (nome: 'escuro' | 'papel' | 'fibra') =>
  (cacheRuido[nome] ??=
    nome === 'escuro' ? bitmapRuido(256, 256, true, 0.9, 11) : nome === 'papel' ? bitmapRuido(256, 256, false, 0.9, 23) : bitmapRuido(64, 36, false, 0.9, 37));

/**
 * Textura por cima da cena: grão que "ferve" (o tile salta de posição a cada quadro — custo ~zero),
 * vinheta e, no papel, manchas de fibra. Intensidade baixa: é para sentir, não para ver.
 */
export const Textura: React.FC<{ papel?: boolean; grao?: number; vinheta?: number }> = ({ papel = false, grao = 0, vinheta = 1 }) => {
  const f = useCurrentFrame();
  // grão fino por quadro torna cada PNG incompressível (render caía à metade) e o acabamento do
  // montar.py JÁ aplica grão de filme no vídeo final (tokens.acabamento.grao). Aqui só se for pedido.
  if (grao <= 0) {
    return (
      <AbsoluteFill style={{ pointerEvents: 'none' }}>
        {papel ? <AbsoluteFill style={{ backgroundImage: `url("${textura('fibra')}")`, backgroundSize: '100% 100%', opacity: 0.09 }} /> : null}
        <AbsoluteFill
          style={{
            background: papel
              ? `radial-gradient(120% 95% at 50% 45%, rgba(70,45,15,0) 55%, rgba(70,45,15,${0.3 * vinheta}) 100%)`
              : `radial-gradient(110% 90% at 50% 45%, rgba(0,0,0,0) 50%, rgba(0,0,0,${0.6 * vinheta}) 100%)`,
          }}
        />
      </AbsoluteFill>
    );
  }
  const ox = (f * 7919) % 256;
  const oy = (f * 104729) % 256;
  return (
    <AbsoluteFill style={{ pointerEvents: 'none' }}>
      {papel ? (
        <AbsoluteFill style={{ backgroundImage: `url("${textura('fibra')}")`, backgroundSize: '100% 100%', opacity: 0.22 }} />
      ) : null}
      <AbsoluteFill
        style={{
          backgroundImage: `url("${textura(papel ? 'papel' : 'escuro')}")`,
          backgroundPosition: `${ox}px ${oy}px`,
          opacity: (papel ? 0.16 : 0.09) * grao,
        }}
      />
      <AbsoluteFill
        style={{
          background: papel
            ? `radial-gradient(120% 95% at 50% 45%, rgba(70,45,15,0) 55%, rgba(70,45,15,${0.3 * vinheta}) 100%)`
            : `radial-gradient(110% 90% at 50% 45%, rgba(0,0,0,0) 50%, rgba(0,0,0,${0.6 * vinheta}) 100%)`,
        }}
      />
    </AbsoluteFill>
  );
};

const saidaEx = Easing.bezier(0.16, 1, 0.3, 1);

/** Rótulo-chapéu ("kicker"): fio curto que desenha + versaletes espaçados que deslizam. */
export const Chapeu: React.FC<{
  texto: string;
  inicio: number;
  u: number;
  cor?: string;
  corFio?: string;
  alinhar?: 'left' | 'center';
  tamanho?: number;
  familia?: string;
}> = ({ texto, inicio, u, cor: c = cor.secundaria, corFio = cor.destaque, alinhar = 'left', tamanho = 26, familia = fonte.rotulo }) => {
  const f = useCurrentFrame();
  const kf = interpolate(f, [inicio, inicio + 16], [0, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: saidaEx });
  const kt = interpolate(f, [inicio + 5, inicio + 22], [0, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: saidaEx });
  const fio = (lado: number) => (
    <div style={{ width: 48 * u, height: Math.max(2, 3 * u), flex: 'none', display: 'flex', justifyContent: lado < 0 ? 'flex-end' : 'flex-start' }}>
      <div style={{ width: `${kf * 100}%`, height: '100%', background: corFio }} />
    </div>
  );
  return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: alinhar === 'center' ? 'center' : 'flex-start', gap: 20 * u }}>
      {fio(-1)}
      <div
        style={{
          fontFamily: familia,
          fontWeight: 600,
          fontSize: tamanho * u,
          letterSpacing: '0.34em',
          marginRight: '-0.34em',
          textTransform: 'uppercase',
          color: c,
          opacity: kt,
          transform: `translateX(${(1 - kt) * -16 * u}px)`,
          whiteSpace: 'nowrap',
        }}
      >
        {texto}
      </div>
      {alinhar === 'center' ? fio(1) : null}
    </div>
  );
};

/** Fio de destaque que se desenha. */
export const Fio: React.FC<{ x: number; y: number; largura: number; inicio: number; cor?: string; espessura?: number; vertical?: boolean }> = ({
  x,
  y,
  largura,
  inicio,
  cor: c = cor.destaque,
  espessura = 4,
  vertical = false,
}) => {
  const f = useCurrentFrame();
  const k = interpolate(f, [inicio, inicio + 16], [0, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: Easing.bezier(0.65, 0, 0.35, 1) });
  return (
    <div
      style={{
        position: 'absolute',
        left: x,
        top: y,
        width: vertical ? espessura : largura * k,
        height: vertical ? largura * k : espessura,
        background: c,
      }}
    />
  );
};

/**
 * Fundo editorial "nunca vazio" (capítulo, citação): uma palavra GIGANTE quase transparente que sangra
 * para fora do quadro, glow radial sutil atrás do bloco de conteúdo e filetes finos de grade.
 * Estático depois da entrada (só uma deriva lateral lenta e monotônica: paralaxe, não balanço).
 */
export const FundoTipo: React.FC<{
  palavra: string;
  W: number;
  H: number;
  /** centro do glow (px) — em cima do bloco de conteúdo */
  glowX: number;
  glowY: number;
  /** de que lado a palavra sangra */
  lado?: 'esq' | 'dir';
  /** posição vertical da linha de base da palavra (0..1 de H) */
  y?: number;
  inicio: number;
  frames: number;
  corGlow?: string;
  italico?: boolean;
}> = ({ palavra, W, H, glowX, glowY, lado = 'dir', y = 0.62, inicio, frames, corGlow = rgbDe(cor.destaque), italico = false }) => {
  const f = useCurrentFrame();
  const u = H / 1080;
  const k = interpolate(f, [inicio, inicio + 25], [0, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: Easing.bezier(0.33, 1, 0.68, 1) });
  const desliza = interpolate(f, [0, frames], [0, lado === 'dir' ? -1 : 1]) * 40 * u;
  const kFio = interpolate(f, [inicio + 4, inicio + 29], [0, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: Easing.bezier(0.65, 0, 0.35, 1) });
  return (
    <AbsoluteFill style={{ pointerEvents: 'none', overflow: 'hidden' }}>
      <AbsoluteFill
        style={{
          background: `radial-gradient(${W * 0.42}px ${H * 0.4}px at ${glowX}px ${glowY}px, rgba(${corGlow},${0.1 * k}) 0%, rgba(${corGlow},0) 100%)`,
        }}
      />
      {palavra ? (
        <div
          style={{
            position: 'absolute',
            top: H * y,
            [lado === 'dir' ? 'left' : 'right']: W * 0.38,
            transform: `translateY(-80%) translateX(${desliza + (1 - k) * (lado === 'dir' ? 30 : -30) * u}px)`,
            fontFamily: fonte.titulo,
            fontWeight: 700,
            fontStyle: italico ? 'italic' : 'normal',
            fontSize: H * 0.62,
            lineHeight: 1,
            letterSpacing: '-0.045em',
            whiteSpace: 'nowrap',
            color: alfa(cor.texto, 0.045 * k),
          }}
        >
          {palavra}
        </div>
      ) : null}
      {/* filetes: duas linhas finas de grade que se desenham (estrutura, não enfeite) */}
      <div style={{ position: 'absolute', left: W * 0.06, top: H * 0.115, width: W * 0.88 * kFio, height: 1, background: alfa(cor.texto, 0.12) }} />
      <div style={{ position: 'absolute', right: W * 0.06, bottom: H * 0.115, width: W * 0.88 * kFio, height: 1, background: alfa(cor.texto, 0.12) }} />
    </AbsoluteFill>
  );
};
