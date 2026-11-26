import tokens from '../../../assets/marca/tokens.json';
import { Easing } from 'remotion';
import { definirIdioma } from './i18n';

// Tokens do canal. Os valores-base são os de assets/marca/tokens.json; o pipeline manda os do
// canal do episódio em props.tokens e <Cena> chama aplicarCanal() ANTES de renderizar qualquer cena — por isso
// `cor`, `fonte` e `T` são objetos mutáveis (os componentes leem na hora do render, nunca no import).
type Tokens = typeof tokens;
export const T: Tokens = JSON.parse(JSON.stringify(tokens));
export const cor: Tokens['cores'] = { ...tokens.cores };
export const fonte = {
  titulo: tokens.familias.titulo,
  rotulo: tokens.familias.rotulo,
  documento: tokens.familias.documento,
};
export const mapaCores: Tokens['mapa'] = { ...tokens.mapa };

export const aplicarCanal = (tk?: Partial<Tokens> | null, idioma?: string | null) => {
  definirIdioma(idioma);
  const fonteTk = (tk ?? tokens) as Tokens;
  Object.assign(T, JSON.parse(JSON.stringify(tokens)), tk ?? {});
  Object.assign(cor, tokens.cores, fonteTk.cores ?? {});
  Object.assign(mapaCores, tokens.mapa, fonteTk.mapa ?? {});
  const fam = { ...tokens.familias, ...(fonteTk.familias ?? {}) };
  fonte.titulo = fam.titulo;
  fonte.rotulo = fam.rotulo;
  fonte.documento = fam.documento;
};

/** "#C8102E" → "200,16,46" (para montar rgba com alfa variável). */
export const rgbDe = (hexa: string) => {
  const h = hexa.replace('#', '');
  return [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16)).join(',');
};
/** Cor do token com alfa: alfa(cor.destaque, 0.5) → "rgba(200,16,46,0.5)". */
export const alfa = (hexa: string, a: number) => `rgba(${rgbDe(hexa)},${a})`;

const [a, b, c, d] = tokens.movimento.easing as [number, number, number, number];
export const ease = {
  padrao: Easing.bezier(a, b, c, d),
  saida: Easing.bezier(0.16, 1, 0.3, 1),
  entrada: Easing.bezier(0.7, 0, 0.84, 0),
  suave: Easing.bezier(0.33, 1, 0.68, 1),
  /** câmera: easeInOutCubic — acelera, cruza e pousa (mapa) */
  camera: Easing.inOut(Easing.cubic),
  /** overshoot leve (~2%) para o "travamento" do clímax; nada de bounce/elastic */
  trava: Easing.bezier(0.34, 1.25, 0.64, 1),
};

// ---------------------------------------------------------------------------------------------
// Tempos de movimento (v4). Fonte única dos números de timing das cenas — em QUADROS a 30 q/s;
// `q(n, fps)` reescala para outro fps. Regras (doutrina de motion de documentário):
//  · texto entra em 15–25 q; sai em ≈75% do tempo de entrada (sair é mais rápido que entrar);
//  · escalonamento (stagger) de um grupo soma no máximo 15 q, não importa quantos itens;
//  · antecipação de 2–4 q; o primeiro movimento da cena espera 3–9 q;
//  · no máximo 2 animações com o mesmo easing por cena (há 6 easings acima para isso);
//  · sem bounce/elastic: molas amortecidas ou overshoot leve (≤ 3%);
//  · nada de "balanço ocioso" (pulsar/flutuar só para preencher tempo): o que se move, se move
//    porque a narração pediu; fora isso a cena repousa.
export const TEMPO = {
  entrada: 20,
  entradaCurta: 15,
  entradaLonga: 25,
  saida: 15,
  staggerTotal: 15,
  antecipacao: 3,
  atrasoInicial: 6,
  /** Número: pausa com o valor "quase lá" antes de travar (antecipação do clímax) — 12–20 q */
  pausaClimax: 16,
  /** "ping" do pino no mapa (~600 ms) */
  ping: 18,
} as const;

/** quadros-base (30 q/s) → quadros no fps da cena */
export const q = (n: number, fps: number) => Math.round((n * fps) / 30);

/** Atraso do item i num grupo de n, com o total limitado a TEMPO.staggerTotal. */
export const escalonar = (i: number, n: number, fps = 30, passo = 4) =>
  q(Math.min(passo, n > 1 ? TEMPO.staggerTotal / (n - 1) : 0) * i, fps);

/** Molas sem quique: use no lugar de configs "elásticas". */
export const MOLA = {
  firme: { damping: 200, stiffness: 120, mass: 1 },
  leve: { damping: 22, stiffness: 140, mass: 0.8 },
} as const;

export const clamp = { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' } as const;

/** Gerador pseudoaleatório determinístico (mulberry32). Mesma seed → mesmas escolhas. */
export const rng = (seed: number) => {
  let t = seed >>> 0;
  return () => {
    t += 0x6d2b79f5;
    let r = Math.imul(t ^ (t >>> 15), 1 | t);
    r ^= r + Math.imul(r ^ (r >>> 7), 61 | r);
    return ((r ^ (r >>> 14)) >>> 0) / 4294967296;
  };
};

export const escolher = <X,>(r: () => number, xs: X[]): X => xs[Math.floor(r() * xs.length) % xs.length];
