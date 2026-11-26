import React from 'react';
import { AbsoluteFill, Easing, interpolate, useCurrentFrame } from 'remotion';
import { clamp, ease, fonte, q, rng, TEMPO } from './tokens';

/**
 * Vocabulário de movimento da colagem editorial (explicativos BBC/Vox): nada entra "aparecendo" — abre,
 * desliza, cresce, se monta em fatias, e a cena tem mais de um tempo (entrada → reenquadramento → saída).
 *
 *  fatias   faixas horizontais que chegam alternadamente da esquerda e da direita e se encaixam
 *  cortina  abre na horizontal a partir do centro (como uma fresta que vira quadro)
 *  persiana abre na vertical a partir do centro
 *  iris     círculo que cresce a partir do centro do elemento
 *  lateral  entra de lado, rápido, com rastro (blur só na direção do movimento)
 *  baixo    sobe de baixo com rastro vertical
 *  escala   cresce de pequeno com leve passado do ponto
 *  giro     cresce girando (como o símbolo que se forma no vídeo de referência)
 */
export type TipoEntrada = 'fatias' | 'cortina' | 'persiana' | 'iris' | 'lateral' | 'baixo' | 'escala' | 'giro';
export const ENTRADAS: TipoEntrada[] = ['fatias', 'cortina', 'persiana', 'iris', 'lateral', 'baixo', 'escala', 'giro'];

const saidaRapida = Easing.bezier(0.12, 0.9, 0.2, 1);

/** Velocidade normalizada da curva no quadro f (para dosar o rastro de movimento). */
const velocidade = (f: number, ini: number, dur: number, curva: (x: number) => number) => {
  const a = curva(Math.min(1, Math.max(0, (f - ini) / dur)));
  const b = curva(Math.min(1, Math.max(0, (f + 1 - ini) / dur)));
  return Math.abs(b - a);
};

/**
 * Envolve um elemento com uma entrada. `cx`, `cy`, `w`, `h` = caixa do elemento na tela (px) — a íris e a
 * cortina abrem a partir do centro dela. `de` = lado de onde vem (lateral). Antes de `inicio`, nada aparece.
 */
export const Entrada: React.FC<{
  tipo: TipoEntrada;
  inicio: number;
  dur?: number;
  cx: number;
  cy: number;
  w: number;
  h: number;
  W: number;
  H: number;
  de?: 1 | -1;
  id: string;
  children: React.ReactNode;
}> = ({ tipo, inicio, dur = 18, cx, cy, w, h, W, H, de = 1, id, children }) => {
  const f = useCurrentFrame();
  if (f < inicio) return null;
  const k = interpolate(f, [inicio, inicio + dur], [0, 1], { ...clamp, easing: saidaRapida });
  if (k >= 1) return <AbsoluteFill>{children}</AbsoluteFill>;
  const v = velocidade(f, inicio, dur, saidaRapida);

  if (tipo === 'fatias') {
    const n = 7;
    const topo = cy - h / 2;
    const alt = h / n;
    return (
      <AbsoluteFill>
        {Array.from({ length: n }, (_, i) => {
          const ki = interpolate(f, [inicio + i * 1.5, inicio + i * 1.5 + dur * 0.8], [0, 1], { ...clamp, easing: saidaRapida });
          const lado = i % 2 ? 1 : -1;
          const y0 = topo + i * alt;
          return (
            <AbsoluteFill
              key={i}
              style={{
                clipPath: `inset(${Math.max(0, y0 - 1)}px 0 ${Math.max(0, H - y0 - alt - 1)}px 0)`,
                transform: `translateX(${lado * (1 - ki) * W * 0.35}px)`,
                opacity: ki > 0 ? 1 : 0,
              }}
            >
              {children}
            </AbsoluteFill>
          );
        })}
      </AbsoluteFill>
    );
  }
  if (tipo === 'cortina' || tipo === 'persiana') {
    const hor = tipo === 'cortina';
    // começa como uma fresta de 2 px que abre; leve escala no eixo da abertura
    const ax = hor ? (w / 2) * (1 - k) : 0;
    const ay = hor ? 0 : (h / 2) * (1 - k);
    return (
      <AbsoluteFill
        style={{
          clipPath: `inset(${Math.max(0, cy - h / 2 + ay)}px ${Math.max(0, W - (cx + w / 2) + ax)}px ${Math.max(0, H - (cy + h / 2) + ay)}px ${Math.max(0, cx - w / 2 + ax)}px)`,
          transform: hor ? `scaleX(${1.12 - 0.12 * k})` : `scaleY(${1.12 - 0.12 * k})`,
          transformOrigin: `${cx}px ${cy}px`,
        }}
      >
        {children}
      </AbsoluteFill>
    );
  }
  if (tipo === 'iris') {
    const r = Math.hypot(w, h) * 0.55 * k;
    return (
      <AbsoluteFill style={{ clipPath: `circle(${r}px at ${cx}px ${cy}px)`, transform: `scale(${1.08 - 0.08 * k})`, transformOrigin: `${cx}px ${cy}px` }}>
        {children}
      </AbsoluteFill>
    );
  }
  if (tipo === 'lateral' || tipo === 'baixo') {
    const hor = tipo === 'lateral';
    const d = (1 - k) * (hor ? W * 0.55 * de : H * 0.45);
    const rastro = Math.min(40, v * (hor ? W : H) * 0.35);
    return (
      <AbsoluteFill style={{ transform: hor ? `translateX(${d}px) skewX(${-de * (1 - k) * 8}deg)` : `translateY(${d}px)` }}>
        <svg width="0" height="0" style={{ position: 'absolute' }}>
          <filter id={`mb-${id}`} x="-20%" y="-20%" width="140%" height="140%">
            <feGaussianBlur stdDeviation={hor ? `${rastro} 0` : `0 ${rastro}`} />
          </filter>
        </svg>
        <AbsoluteFill style={{ filter: rastro > 0.5 ? `url(#mb-${id})` : undefined }}>{children}</AbsoluteFill>
      </AbsoluteFill>
    );
  }
  // escala / giro
  const ke = interpolate(f, [inicio, inicio + dur], [0, 1], { ...clamp, easing: ease.trava });
  const s = 0.25 + 0.75 * ke;
  const rot = tipo === 'giro' ? (1 - ke) * -120 : 0;
  return (
    <AbsoluteFill
      style={{
        transform: `scale(${s}) rotate(${rot}deg)`,
        transformOrigin: `${cx}px ${cy}px`,
        opacity: Math.min(1, k * 3),
        filter: v > 0.02 ? `blur(${Math.min(8, v * 60)}px)` : undefined,
      }}
    >
      {children}
    </AbsoluteFill>
  );
};

/**
 * Coreografia em três tempos para as cenas gráficas clássicas (número, citação, capítulo, comparação,
 * linha do tempo, documento): a composição chega maior e assenta; no meio da fala a câmera reenquadra
 * (recua, avança ou desliza, sorteado pela semente); nos últimos quadros a cena se recolhe/sobe/sai.
 * Envolve o CONTEÚDO da cena (o Fundo e a Textura ficam fora). `cx`,`cy` = origem do movimento (px).
 */
export const Coreografia: React.FC<{
  p: { alca_antes: number; corpo: number; frames: number; fps: number; seed: number; largura: number; altura: number };
  cx?: number;
  cy?: number;
  reenq?: 'recua' | 'avanca' | 'desliza';
  saida?: 'recolhe' | 'sobe' | 'lado';
  /** escala do 2º tempo e da deriva (0..1); cenas que já têm câmera própria usam valor baixo */
  intensidade?: number;
  children: React.ReactNode;
}> = ({ p, cx, cy, reenq, saida, intensidade = 1, children }) => {
  const f = useCurrentFrame();
  const r = rng(p.seed + 303);
  const W = p.largura;
  const H = p.altura;
  const ini = p.alca_antes + q(TEMPO.atrasoInicial, p.fps);
  const fimCorpo = p.alca_antes + p.corpo;
  const corpoS = p.corpo / p.fps;
  const kCam = interpolate(f, [0, p.frames], [0, 1], clamp);
  const kAssenta = interpolate(f, [ini - 4, ini + q(26, p.fps)], [0, 1], { ...clamp, easing: ease.saida });
  const temBeat2 = corpoS >= 4.2;
  const t2 = Math.round(p.alca_antes + p.corpo * 0.5);
  const k2 = temBeat2 ? interpolate(f, [t2, t2 + q(24, p.fps)], [0, 1], { ...clamp, easing: ease.camera }) : 0;
  const t3 = Math.round(p.alca_antes + p.corpo * 0.8);
  const k3 = corpoS >= 7 ? interpolate(f, [t3, t3 + q(22, p.fps)], [0, 1], { ...clamp, easing: ease.camera }) : 0;
  const kBeat = (k2 - 0.55 * k3) * intensidade;
  const tipo = reenq ?? (['recua', 'avanca', 'desliza'] as const)[Math.floor(r() * 3) % 3];
  const zoom =
    (1.07 - 0.07 * kAssenta) *
    (1 + 0.05 * kCam * intensidade) *
    (tipo === 'recua' ? 1 - 0.15 * kBeat : tipo === 'avanca' ? 1 + 0.18 * kBeat : 1 + 0.03 * kBeat);
  const desliza = tipo === 'desliza' ? -kBeat * W * 0.08 : 0;
  const tipoSaida = saida ?? (['recolhe', 'sobe', 'lado'] as const)[Math.floor(r() * 3) % 3];
  return (
    <Saida fim={fimCorpo} cx={cx ?? W / 2} cy={cy ?? H * 0.45} tipo={tipoSaida}>
      <AbsoluteFill style={{ transform: `translateX(${desliza}px) scale(${zoom})`, transformOrigin: `${cx ?? W / 2}px ${cy ?? H * 0.45}px` }}>
        {children}
      </AbsoluteFill>
    </Saida>
  );
};

/**
 * Saída da cena: nos últimos `dur` quadros do corpo, a composição se recolhe (encolhe e gira de leve em
 * direção ao centro do elemento principal), com rastro. Segura a pose final durante a alça de transição.
 */
export const Saida: React.FC<{ fim: number; dur?: number; cx: number; cy: number; tipo?: 'recolhe' | 'sobe' | 'lado'; children: React.ReactNode }> = ({
  fim,
  dur = 9,
  cx,
  cy,
  tipo = 'recolhe',
  children,
}) => {
  const f = useCurrentFrame();
  const k = interpolate(f, [fim - dur, fim], [0, 1], { ...clamp, easing: ease.entrada });
  if (k <= 0) return <AbsoluteFill>{children}</AbsoluteFill>;
  const t =
    tipo === 'recolhe'
      ? `scale(${1 - 0.22 * k}) rotate(${4 * k}deg)`
      : tipo === 'sobe'
        ? `translateY(${-k * 120}px) scale(${1 - 0.08 * k})`
        : `translateX(${-k * 260}px) scale(${1 - 0.06 * k})`;
  return (
    <AbsoluteFill style={{ transform: t, transformOrigin: `${cx}px ${cy}px`, filter: k > 0.05 ? `blur(${k * 6}px)` : undefined, opacity: 1 - k * 0.35 }}>
      {children}
    </AbsoluteFill>
  );
};

/** Letras que surgem FORA de ordem (cada uma sobe e pousa), como a palavra que se monta na referência. */
export const LetrasAleatorias: React.FC<{ texto: string; inicio: number; seed: number; tam: number; cor: string; espalhar?: number }> = ({
  texto,
  inicio,
  seed,
  tam,
  cor,
  espalhar = 16,
}) => {
  const f = useCurrentFrame();
  const r = rng(seed);
  const chars = [...texto];
  const ordem = chars.map((_, i) => ({ i, x: r() })).sort((a, b) => a.x - b.x);
  const atraso: number[] = [];
  ordem.forEach((o, n) => (atraso[o.i] = (n * espalhar) / Math.max(1, chars.length - 1)));
  return (
    <div style={{ display: 'flex', whiteSpace: 'pre' }}>
      {chars.map((ch, i) => {
        const k = interpolate(f, [inicio + atraso[i], inicio + atraso[i] + 10], [0, 1], { ...clamp, easing: ease.saida });
        return (
          <div key={i} style={{ height: tam * 1.02, overflow: 'hidden' }}>
            <div
              style={{
                fontFamily: fonte.rotulo, fontWeight: 800, fontSize: tam, lineHeight: 1, letterSpacing: '-0.04em', color: cor,
                transform: `translateY(${(1 - k) * 105}%)`,
              }}
            >
              {ch}
            </div>
          </div>
        );
      })}
    </div>
  );
};

/**
 * Odômetro: os caracteres entram um a um (cada um sobe), e o bloco desliza para a direita conforme cresce —
 * o ano "corre" pelo fio até a posição final (alinhado à direita).
 */
export const Odometro: React.FC<{ texto: string; inicio: number; tam: number; cor: string; passo?: number; peso?: number }> = ({
  texto,
  inicio,
  tam,
  cor,
  passo = 3,
  peso = 800,
}) => {
  const f = useCurrentFrame();
  const chars = [...texto];
  const n = chars.length;
  const visiveis = interpolate(f, [inicio, inicio + passo * n], [0, n], clamp);
  const larg = tam * 0.6;
  const falta = (n - visiveis) * larg;
  return (
    <div style={{ display: 'flex', justifyContent: 'flex-end', transform: `translateX(${-falta}px)` }}>
      {chars.map((ch, i) => {
        const k = interpolate(f, [inicio + i * passo, inicio + i * passo + 8], [0, 1], { ...clamp, easing: ease.saida });
        return (
          <div key={i} style={{ height: tam * 1.15, overflow: 'hidden' }}>
            <div style={{ fontFamily: fonte.rotulo, fontWeight: peso, fontSize: tam, lineHeight: 1.15, color: cor, transform: `translateY(${(1 - k) * 100}%)`, whiteSpace: 'pre' }}>
              {ch}
            </div>
          </div>
        );
      })}
    </div>
  );
};

/** Escolhe uma entrada pela semente, evitando a anterior da mesma cena (variedade dentro do vídeo). */
export const sortearEntrada = (seed: number, opcoes: TipoEntrada[], salto = 0): TipoEntrada => {
  const r = rng(seed + salto * 7919);
  return opcoes[Math.floor(r() * opcoes.length) % opcoes.length];
};
