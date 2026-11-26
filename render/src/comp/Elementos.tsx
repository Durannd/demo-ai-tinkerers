import React from 'react';
import { AbsoluteFill, interpolate, useCurrentFrame } from 'remotion';
import { Odometro } from './Movimento';
import { alfa, clamp, ease, fonte, rng, T } from './tokens';

/**
 * Elementos gráficos da linguagem "colagem editorial" (explicativos estilo BBC/Vox): textura térmica,
 * riscos e poeira de película, vazamento de luz, ícones próprios (desenhados aqui, nada de marca de
 * terceiros), fio com nome + ano e ficha de dado. Usados por cenas/Colagem.tsx; servem a outras cenas.
 */

// ---------------------------------------------------------------- textura térmica (mapa de calor líquido)
const canais = (hexas: string[]) => {
  const rgb = hexas.map((h) => [0, 2, 4].map((i) => parseInt(h.replace('#', '').slice(i, i + 2), 16) / 255));
  return [0, 1, 2].map((k) => rgb.map((c) => c[k].toFixed(3)).join(' '));
};

// Textura da CENA (paleta + padrão): cada cena chama definirTextura() uma vez; todo preenchimento
// (sujeito, ícone, ficha, mosaico, formas) usa a mesma — a cena tem unidade, o vídeo tem variedade.
export type Padrao = 'manchas' | 'contornos' | 'listras' | 'liquido' | 'posterizado';
export const PADROES: Padrao[] = ['manchas', 'contornos', 'listras', 'liquido', 'posterizado'];
const texturaAtual: { paleta: string[]; padrao: Padrao } = { paleta: [], padrao: 'manchas' };
type Paletas = Record<string, string[]>;

/** pedido = visual.*.textura ({paleta: nome | [hex...], padrao}); o que faltar sai da semente da cena. */
export const definirTextura = (seed: number, pedido?: { paleta?: string | string[]; padrao?: string } | null) => {
  const C = T.colagem as unknown as { termico: string[]; paletas?: Paletas; paletas_auto?: string[]; padroes_auto?: string[] };
  const paletas: Paletas = C.paletas ?? { termico: C.termico };
  const r = rng(seed + 4242);
  const nomes = (C.paletas_auto ?? Object.keys(paletas)).filter((n) => paletas[n]);
  const pal = pedido?.paleta;
  texturaAtual.paleta = Array.isArray(pal) ? pal : paletas[pal ?? ''] ?? paletas[nomes[Math.floor(r() * nomes.length) % nomes.length]] ?? C.termico;
  const pads = (C.padroes_auto ?? PADROES) as Padrao[];
  texturaAtual.padrao = (pedido?.padrao as Padrao) ?? pads[Math.floor(r() * pads.length) % pads.length];
};

/**
 * <filter> SVG da textura "térmica". Com `imagem`, mistura a luminância da imagem (detalhe do rosto/objeto)
 * com ruído; sem, é só o ruído (preenche formas). Padrões: manchas (líquido largo), contornos (curvas de
 * nível, como mapa topográfico), listras (ruído esticado na horizontal), liquido (veios finos, turbulência),
 * posterizado (5 chapas de cor). O ruído evolui devagar; o alfa da fonte é preservado (operator in).
 */
export const FiltroTermico: React.FC<{ id: string; seed: number; escala?: number; progresso?: number; imagem?: boolean; padrao?: Padrao; paleta?: string[] }> = ({
  id,
  seed,
  escala = 0.004,
  progresso = 0,
  imagem = false,
  padrao,
  paleta,
}) => {
  const pad = padrao ?? texturaAtual.padrao;
  const [R, G, B] = canais(paleta ?? (texturaAtual.paleta.length ? texturaAtual.paleta : T.colagem.termico));
  const bf = escala * (1 + 0.35 * progresso);
  const freq = pad === 'listras' ? `${bf * 0.18} ${bf * 3.2}` : pad === 'liquido' ? `${bf * 0.9} ${bf * 1.1}` : `${bf} ${bf * 1.35}`;
  const estica = pad === 'liquido' ? '2.6 0 0 0 -0.15  2.6 0 0 0 -0.15  2.6 0 0 0 -0.15  0 0 0 0 1' : '3.2 0 0 0 -1.1  3.2 0 0 0 -1.1  3.2 0 0 0 -1.1  0 0 0 0 1';
  const pre = pad === 'contornos' ? '0 1 0 1 0 1 0 1 0 1 0' : pad === 'posterizado' ? '0 0.25 0.5 0.75 1' : null;
  return (
    <filter id={id} x="0" y="0" width="100%" height="100%" colorInterpolationFilters="sRGB">
      <feTurbulence type={pad === 'liquido' ? 'turbulence' : 'fractalNoise'} baseFrequency={freq} numOctaves={pad === 'liquido' ? 4 : 3} seed={seed % 1000} result="ruido" />
      <feColorMatrix in="ruido" type="matrix" values={estica} result="ruidoK" />
      {imagem ? (
        <>
          <feColorMatrix in="SourceGraphic" type="matrix" values="0.3 0.59 0.11 0 0  0.3 0.59 0.11 0 0  0.3 0.59 0.11 0 0  0 0 0 0 1" result="lum" />
          <feComposite in="lum" in2="ruidoK" operator="arithmetic" k1={0} k2={0.62} k3={0.5} k4={-0.1} result="mix" />
        </>
      ) : (
        <feColorMatrix in="ruidoK" type="matrix" values="1 0 0 0 0  1 0 0 0 0  1 0 0 0 0  0 0 0 0 1" result="mix0" />
      )}
      {imagem ? <feColorMatrix in="mix" type="matrix" values="1 0 0 0 0  0 1 0 0 0  0 0 1 0 0  0 0 0 0 1" result="mix0" /> : null}
      {pre ? (
        <feComponentTransfer in="mix0" result="mix1">
          <feFuncR type={pad === 'posterizado' ? 'discrete' : 'table'} tableValues={pre} />
          <feFuncG type={pad === 'posterizado' ? 'discrete' : 'table'} tableValues={pre} />
          <feFuncB type={pad === 'posterizado' ? 'discrete' : 'table'} tableValues={pre} />
        </feComponentTransfer>
      ) : (
        <feColorMatrix in="mix0" type="matrix" values="1 0 0 0 0  0 1 0 0 0  0 0 1 0 0  0 0 0 0 1" result="mix1" />
      )}
      <feComponentTransfer in="mix1" result="pal">
        <feFuncR type="table" tableValues={R} />
        <feFuncG type="table" tableValues={G} />
        <feFuncB type="table" tableValues={B} />
      </feComponentTransfer>
      <feComposite in="pal" in2="SourceAlpha" operator="in" />
    </filter>
  );
};

/** Retângulo preenchido pela textura térmica (fundo de ficha, faixa, disco...). */
export const TermicoRect: React.FC<{ w: number; h: number; seed: number; raio?: number; escala?: number }> = ({ w, h, seed, raio = 0, escala = 0.008 }) => {
  const f = useCurrentFrame();
  const id = `term-r-${seed}`;
  return (
    <svg width={w} height={h} style={{ position: 'absolute', left: 0, top: 0 }}>
      <defs>
        <FiltroTermico id={id} seed={seed} escala={escala} progresso={Math.min(1, f / 300)} />
      </defs>
      <rect width={w} height={h} rx={raio} fill="#808080" filter={`url(#${id})`} />
    </svg>
  );
};

export type Forma = 'disco' | 'anel' | 'losango' | 'faixa' | 'blob' | 'hexagono';
export const FORMAS: Forma[] = ['disco', 'anel', 'losango', 'faixa', 'blob', 'hexagono'];

/** Contorno de uma forma de raio r em (cx, cy); blob = mancha orgânica (raio com ruído suave, pela semente). */
const caminhoForma = (forma: Forma, cx: number, cy: number, r: number, seed: number, giro = 0): string => {
  const pt = (a: number, rr: number) => `${cx + rr * Math.cos(a + giro)},${cy + rr * Math.sin(a + giro)}`;
  if (forma === 'losango') return `M${pt(-Math.PI / 2, r)} L${pt(0, r * 0.8)} L${pt(Math.PI / 2, r)} L${pt(Math.PI, r * 0.8)} Z`;
  if (forma === 'hexagono') return `M${Array.from({ length: 6 }, (_, i) => pt((i * Math.PI) / 3, r)).join(' L')} Z`;
  if (forma === 'faixa') return `M${cx - r * 1.9},${cy - r * 0.32} H${cx + r * 1.9} V${cy + r * 0.32} H${cx - r * 1.9} Z`;
  if (forma === 'blob') {
    const rr = rng(seed + 77);
    const n = 9;
    const raios = Array.from({ length: n }, () => r * (0.72 + rr() * 0.42));
    const pts = raios.map((ri, i) => [cx + ri * Math.cos((i / n) * 2 * Math.PI + giro), cy + ri * Math.sin((i / n) * 2 * Math.PI + giro)]);
    // curva suave (Catmull-Rom → Bézier) passando pelos pontos
    let d = `M${pts[0][0]},${pts[0][1]}`;
    for (let i = 0; i < n; i++) {
      const [p0, p1, p2, p3] = [pts[(i - 1 + n) % n], pts[i], pts[(i + 1) % n], pts[(i + 2) % n]];
      d += ` C${p1[0] + (p2[0] - p0[0]) / 6},${p1[1] + (p2[1] - p0[1]) / 6} ${p2[0] - (p3[0] - p1[0]) / 6},${p2[1] - (p3[1] - p1[1]) / 6} ${p2[0]},${p2[1]}`;
    }
    return d + ' Z';
  }
  // disco / anel
  return `M${cx - r},${cy} A${r},${r} 0 1 0 ${cx + r},${cy} A${r},${r} 0 1 0 ${cx - r},${cy} Z`;
};

/**
 * Forma (disco, anel, losango, faixa, mancha orgânica, hexágono) preenchida pela textura da cena, que
 * cresce com `k` (0→1) girando de leve. Fica atrás do sujeito: é o "fundo térmico" que muda de forma.
 */
export const FormaTermica: React.FC<{ forma: Forma; cx: number; cy: number; r: number; k: number; seed: number; W: number; H: number; giro?: number }> = ({
  forma,
  cx,
  cy,
  r,
  k,
  seed,
  W,
  H,
  giro = 0,
}) => {
  const f = useCurrentFrame();
  if (k <= 0) return null;
  const id = `ft-${seed}`;
  const rr = r * k;
  return (
    <svg width={W} height={H} style={{ position: 'absolute', left: 0, top: 0 }}>
      <defs>
        <clipPath id={`${id}-c`}>
          {forma === 'anel' ? null : <path d={caminhoForma(forma, cx, cy, rr, seed, giro)} />}
        </clipPath>
        <mask id={`${id}-m`} maskUnits="userSpaceOnUse" x="0" y="0" width={W} height={H}>
          <rect width={W} height={H} fill="#000" />
          <circle cx={cx} cy={cy} r={rr} fill="none" stroke="#fff" strokeWidth={rr * 0.22} />
        </mask>
        <FiltroTermico id={`${id}-t`} seed={seed} escala={0.0025 * (1080 / H)} progresso={Math.min(1, f / 300)} />
      </defs>
      <g clipPath={forma === 'anel' ? undefined : `url(#${id}-c)`} mask={forma === 'anel' ? `url(#${id}-m)` : undefined}>
        <rect x={cx - r * 2} y={cy - r * 2} width={r * 4} height={r * 4} fill="#808080" filter={`url(#${id}-t)`} />
      </g>
    </svg>
  );
};

// ---------------------------------------------------------------- película: riscos, fios de cabelo e poeira
/**
 * Riscos de película que mudam a cada 3 quadros (como sujeira de projetor). Baixa opacidade: é textura,
 * não efeito. `claro` = fundo claro (riscos escuros).
 */
export const Riscos: React.FC<{ W: number; H: number; seed: number; claro?: boolean; forca?: number }> = ({ W, H, seed, claro = false, forca = 1 }) => {
  const f = useCurrentFrame();
  const r = rng((seed ^ Math.imul(Math.floor(f / 3) + 1, 2654435761)) >>> 0);
  const u = H / 1080;
  const tinta = claro ? '20,20,20' : '235,230,220';
  const fios: React.ReactNode[] = [];
  const nFios = Math.floor(r() * 3.2);
  for (let i = 0; i < nFios; i++) {
    const x = r() * W;
    const y = r() * H;
    const L = (50 + r() * 160) * u;
    const a = r() * Math.PI * 2;
    const c1 = [x + Math.cos(a + 1.2) * L * 0.6, y + Math.sin(a + 1.2) * L * 0.6];
    const fim = [x + Math.cos(a) * L, y + Math.sin(a) * L];
    fios.push(
      <path key={`f${i}`} d={`M${x},${y} Q${c1[0]},${c1[1]} ${fim[0]},${fim[1]}`} stroke={`rgba(${tinta},${(0.25 + r() * 0.3) * forca})`} strokeWidth={(0.8 + r() * 1.2) * u} fill="none" strokeLinecap="round" />,
    );
  }
  if (r() < 0.3) {
    const x = r() * W;
    const d = 8 * u;
    fios.push(<path key="risco" d={`M${x},0 C${x + d},${H * 0.3} ${x - d},${H * 0.6} ${x + d * 0.5},${H}`} stroke={`rgba(${tinta},${0.12 * forca})`} strokeWidth={1.2 * u} fill="none" />);
  }
  const nPo = 10 + Math.floor(r() * 14);
  for (let i = 0; i < nPo; i++) {
    fios.push(<circle key={`p${i}`} cx={r() * W} cy={r() * H} r={(0.6 + r() * 2.2) * u} fill={`rgba(${tinta},${(0.2 + r() * 0.4) * forca})`} />);
  }
  return (
    <svg width={W} height={H} style={{ position: 'absolute', left: 0, top: 0, pointerEvents: 'none' }}>
      {fios}
    </svg>
  );
};

/** Manchas de luz quente que atravessam o quadro devagar (vazamento de luz de película). */
export const Vazamento: React.FC<{ frames: number; seed: number; claro?: boolean; forca?: number }> = ({ frames, seed, claro = false, forca = 1 }) => {
  const f = useCurrentFrame();
  const r = rng(seed + 17);
  const x0 = -10 + r() * 30;
  const y0 = 55 + r() * 30;
  const k = interpolate(f, [0, Math.max(1, frames)], [0, 1], clamp);
  const x = x0 + k * 28;
  const c = claro ? '255,140,120' : T.colagem.vazamento.replace('#', '').match(/../g)!.map((h) => parseInt(h, 16)).join(',');
  const a = (claro ? 0.16 : 0.55) * forca;
  return (
    <AbsoluteFill
      style={{
        pointerEvents: 'none',
        mixBlendMode: claro ? 'multiply' : 'screen',
        background: `radial-gradient(38% 60% at ${x}% ${y0}%, rgba(${c},${a}) 0%, rgba(${c},0) 70%), radial-gradient(26% 40% at ${x + 55}% ${y0 - 45}%, rgba(${c},${a * 0.6}) 0%, rgba(${c},0) 70%)`,
      }}
    />
  );
};

// ---------------------------------------------------------------- ícones (viewBox 100×100, desenho próprio)
// Branco = preenchido; preto = vazado (os ícones são usados como MÁSCARA: cor sólida ou textura térmica).
const P = '#fff';
const V = '#000';
const setor = (cx: number, cy: number, r0: number, r1: number, a0: number, a1: number) => {
  const p = (r: number, a: number) => `${cx + r * Math.cos((a * Math.PI) / 180)},${cy + r * Math.sin((a * Math.PI) / 180)}`;
  return `M${p(r0, a0)} L${p(r1, a0)} A${r1},${r1} 0 0 1 ${p(r1, a1)} L${p(r0, a1)} A${r0},${r0} 0 0 0 ${p(r0, a0)} Z`;
};
const glifo = (t: string, tam = 96) => (
  <text x="50" y="50" dominantBaseline="central" textAnchor="middle" fontFamily="Inter, sans-serif" fontWeight={800} fontSize={tam} fill={P}>
    {t}
  </text>
);

export const ICONES: Record<string, React.ReactNode> = {
  raio: <polygon points="60,2 16,57 45,57 36,98 84,38 55,38 66,2" fill={P} />,
  interrogacao: glifo('?'),
  exclamacao: glifo('!'),
  x: glifo('X', 104),
  dinheiro: glifo('$'),
  radiacao: (
    <g fill={P}>
      <circle cx="50" cy="50" r="9" />
      {[90, 210, 330].map((a) => (
        <path key={a} d={setor(50, 50, 15, 47, a - 30, a + 30)} />
      ))}
    </g>
  ),
  atomo: (
    <g fill="none" stroke={P} strokeWidth={4}>
      {[0, 60, 120].map((a) => (
        <ellipse key={a} cx="50" cy="50" rx="46" ry="16" transform={`rotate(${a} 50 50)`} />
      ))}
      <circle cx="50" cy="50" r="8" fill={P} />
    </g>
  ),
  alerta: (
    <g>
      <polygon points="50,4 97,92 3,92" fill={P} />
      <rect x="45" y="34" width="10" height="32" rx="3" fill={V} />
      <circle cx="50" cy="77" r="6" fill={V} />
    </g>
  ),
  coracao: <path d="M50 90 C20 68 4 50 4 31 C4 14 16 5 30 5 C40 5 47 11 50 19 C53 11 60 5 70 5 C84 5 96 14 96 31 C96 50 80 68 50 90 Z" fill={P} />,
  cruz: <path d="M36 4 H64 V36 H96 V64 H64 V96 H36 V64 H4 V36 H36 Z" fill={P} />,
  seta: <polygon points="4,38 58,38 58,14 96,50 58,86 58,62 4,62" fill={P} />,
  caveira: (
    <g>
      <circle cx="50" cy="42" r="36" fill={P} />
      <rect x="30" y="60" width="40" height="30" rx="8" fill={P} />
      <circle cx="36" cy="42" r="10" fill={V} />
      <circle cx="64" cy="42" r="10" fill={V} />
      <polygon points="50,54 44,66 56,66" fill={V} />
      {[40, 50, 60].map((x) => (
        <rect key={x} x={x - 2} y="74" width="4" height="16" fill={V} />
      ))}
    </g>
  ),
  olho: (
    <g>
      <path d="M2 50 C22 18 78 18 98 50 C78 82 22 82 2 50 Z" fill={P} />
      <circle cx="50" cy="50" r="22" fill={V} />
      <circle cx="50" cy="50" r="11" fill={P} />
    </g>
  ),
  relogio: (
    <g>
      <circle cx="50" cy="50" r="46" fill={P} />
      <circle cx="50" cy="50" r="38" fill={V} />
      <rect x="47" y="20" width="6" height="33" rx="3" fill={P} />
      <rect x="47" y="47" width="26" height="6" rx="3" fill={P} />
    </g>
  ),
  chave: (
    <g fill={P}>
      <circle cx="26" cy="50" r="22" />
      <circle cx="26" cy="50" r="9" fill={V} />
      <rect x="44" y="44" width="54" height="12" />
      <rect x="74" y="56" width="9" height="16" />
      <rect x="88" y="56" width="9" height="11" />
    </g>
  ),
  gota: <path d="M50 3 C50 3 17 46 17 65 A33 33 0 0 0 83 65 C83 46 50 3 50 3 Z" fill={P} />,
  fogo: <path d="M52 2 C58 24 80 34 80 62 A30 34 0 0 1 20 62 C20 46 30 38 34 26 C38 38 44 42 46 44 C48 30 46 16 52 2 Z" fill={P} />,
  engrenagem: (
    <g fill={P}>
      {Array.from({ length: 8 }, (_, i) => (
        <rect key={i} x="42" y="2" width="16" height="22" rx="3" transform={`rotate(${i * 45} 50 50)`} />
      ))}
      <circle cx="50" cy="50" r="34" />
      <circle cx="50" cy="50" r="13" fill={V} />
    </g>
  ),
  lupa: (
    <g>
      <circle cx="40" cy="40" r="34" fill={P} />
      <circle cx="40" cy="40" r="24" fill={V} />
      <rect x="62" y="56" width="14" height="44" rx="5" transform="rotate(-45 69 78)" fill={P} />
    </g>
  ),
  estrela: <polygon points="50,3 62,37 98,37 69,58 80,94 50,72 20,94 31,58 2,37 38,37" fill={P} />,
  check: <polyline points="8,52 38,82 92,20" fill="none" stroke={P} strokeWidth={16} strokeLinecap="round" strokeLinejoin="round" />,
  pessoa: (
    <g fill={P}>
      <circle cx="50" cy="24" r="18" />
      <path d="M14 98 C14 66 30 50 50 50 C70 50 86 66 86 98 Z" />
    </g>
  ),
};
export const NOMES_ICONES = Object.keys(ICONES);

/**
 * Ícone com preenchimento sólido ou térmico, que "estala" na tela (escala com leve overshoot) dentro de
 * um quadrado fino de mira. `inicio` = quadro de entrada.
 */
export const Icone: React.FC<{
  nome: string;
  x: number;
  y: number;
  tam: number;
  inicio: number;
  seed: number;
  termico?: boolean;
  cor?: string;
  moldura?: string | null;
  u: number;
  /** metamorfose: em `tVira` o ícone gira no próprio eixo e volta como `vira` */
  vira?: string | null;
  tVira?: number;
}> = ({ nome, x, y, tam, inicio, seed, termico = true, cor = '#fff', moldura = null, u, vira = null, tVira = 1e7 }) => {
  const f = useCurrentFrame();
  const kv = vira ? interpolate(f, [tVira, tVira + 10], [0, 1], { ...clamp, easing: ease.padrao }) : 0;
  const forma = kv >= 0.5 && vira ? ICONES[vira] ?? ICONES.alerta : ICONES[nome] ?? ICONES.alerta;
  const giroY = Math.abs(Math.cos(Math.PI * kv));
  const pulo = 1 + 0.18 * Math.sin(Math.PI * kv);
  const k = interpolate(f, [inicio, inicio + 9], [0, 1], { ...clamp, easing: ease.trava });
  const km = interpolate(f, [inicio - 4, inicio + 10], [0, 1], { ...clamp, easing: ease.saida });
  if (f < inicio - 4) return null;
  // pisca 3 vezes antes de firmar (como a medalha que pisca sobre o retrato na referência)
  const pisca = f >= inicio && f < inicio + 8 ? ((f - inicio) >> 1) % 2 === 0 : true;
  const id = `ic-${seed}`;
  const m = tam * 1.45;
  return (
    <div style={{ position: 'absolute', left: x - m / 2, top: y - m / 2, width: m, height: m }}>
      {moldura ? (
        <div
          style={{
            position: 'absolute', inset: 0, border: `${Math.max(1, 1.6 * u)}px solid ${moldura}`,
            clipPath: `inset(0 ${(1 - km) * 100}% ${(1 - km) * 100}% 0)`, opacity: 0.85,
          }}
        />
      ) : null}
      <svg width={m} height={m} viewBox="-22.5 -22.5 145 145" style={{ position: 'absolute', inset: 0, transform: `scale(${k * pulo}) scaleX(${giroY}) rotate(${(1 - k) * -30}deg)`, overflow: 'visible', opacity: pisca ? 1 : 0 }}>
        <defs>
          <mask id={`${id}-m${kv >= 0.5 ? 'b' : ''}`} maskUnits="userSpaceOnUse" x="-22.5" y="-22.5" width="145" height="145">
            <rect x="-22.5" y="-22.5" width="145" height="145" fill="#000" />
            {forma}
          </mask>
          {termico ? <FiltroTermico id={`${id}-t`} seed={seed} escala={0.05} progresso={Math.min(1, (f - inicio) / 240)} /> : null}
        </defs>
        <g mask={`url(#${id}-m${kv >= 0.5 ? 'b' : ''})`}>
          <rect x="0" y="0" width="100" height="100" fill={termico ? '#808080' : cor} filter={termico ? `url(#${id}-t)` : undefined} />
        </g>
      </svg>
    </div>
  );
};

// ---------------------------------------------------------------- texto que sobe de trás de uma linha
/** Bloco de texto revelado por máscara: sobe (de=baixo) ou desce (de=cima) até a posição, sem fade. */
export const Surge: React.FC<{ inicio: number; de?: 'baixo' | 'cima'; dur?: number; children: React.ReactNode; estilo?: React.CSSProperties }> = ({
  inicio,
  de = 'baixo',
  dur = 14,
  children,
  estilo,
}) => {
  const f = useCurrentFrame();
  const k = interpolate(f, [inicio, inicio + dur], [0, 1], { ...clamp, easing: ease.saida });
  const d = (1 - k) * 110 * (de === 'baixo' ? 1 : -1);
  return (
    <div style={{ overflow: 'hidden', ...estilo }}>
      <div style={{ transform: `translateY(${d}%)` }}>{children}</div>
    </div>
  );
};

/**
 * Fio com nome e ano (lower third editorial): a linha desenha da esquerda; o ano sobe e pousa SOBRE a
 * linha na ponta direita; o nome (caixa alta, pesado, cor de destaque) desce de trás da linha.
 */
export const FioNome: React.FC<{
  x: number;
  y: number;
  largura: number;
  inicio: number;
  nome?: string | null;
  ano?: string | null;
  sub?: string | null;
  u: number;
  corNome: string;
  corLinha: string;
  corSub: string;
  tamNome?: number;
}> = ({ x, y, largura, inicio, nome, ano, sub, u, corNome, corLinha, corSub, tamNome = 74 }) => {
  const f = useCurrentFrame();
  const kl = interpolate(f, [inicio, inicio + 18], [0, 1], { ...clamp, easing: ease.padrao });
  const tn = tamNome * u * (nome && nome.length > 22 ? 0.78 : 1);
  return (
    <>
      <div style={{ position: 'absolute', left: x, top: y, width: largura * kl, height: Math.max(1, 1.6 * u), background: alfa(corLinha, 0.7) }} />
      {ano ? (
        // o ano "corre" pelo fio dígito a dígito até a ponta direita
        <div style={{ position: 'absolute', left: x + largura - 300 * u, width: 300 * u, top: y - 46 * u, overflow: 'hidden' }}>
          <Odometro texto={ano} inicio={inicio + 2} tam={34 * u} cor={corLinha} />
        </div>
      ) : null}
      {nome ? (
        <div style={{ position: 'absolute', left: x, top: y + 10 * u, width: largura + 400 * u }}>
          {(nome.split(/\s+/).length === 2 ? nome.split(/\s+/) : [nome]).map((w, i) => (
            // cada palavra desce de trás da linha, a de baixo um pouco depois
            <Surge key={i} inicio={inicio + 4 + i * 4} de="cima" dur={14}>
              <div style={{ fontFamily: fonte.rotulo, fontWeight: 800, fontSize: tn, lineHeight: 0.92, color: corNome, textTransform: 'uppercase', letterSpacing: '-0.015em' }}>{w}</div>
            </Surge>
          ))}
        </div>
      ) : null}
      {sub ? (
        <div
          style={{
            position: 'absolute', left: x, top: y + 10 * u + tn * (nome && nome.split(/\s+/).length === 2 ? 1.84 : 0.92) + 14 * u,
            fontFamily: fonte.rotulo, fontWeight: 600, fontSize: 24 * u, letterSpacing: '0.16em', textTransform: 'uppercase', color: corSub,
            opacity: interpolate(f, [inicio + 16, inicio + 28], [0, 1], clamp),
          }}
        >
          {sub}
        </div>
      ) : null}
    </>
  );
};

export type FichaDados = {
  texto: string;
  numero?: string;
  cantos?: string[];
  legenda?: string;
  termico?: boolean;
  em?: string;
  /** metamorfose: a ficha gira no eixo vertical e volta com outro valor (ex.: 1929 → 1939) */
  vira?: { texto: string; numero?: string; cantos?: string[]; legenda?: string };
  vira_em?: string;
};

/**
 * Ficha de dado (como o quadrado de um elemento na tabela periódica): número/sigla grande no centro,
 * valor no canto superior direito, até 3 rótulos nos outros cantos. Borda que desenha; preenchimento
 * térmico opcional (texto vira tinta escura sobre a textura).
 */
export const Ficha: React.FC<{
  x: number;
  y: number;
  tam: number;
  inicio: number;
  seed: number;
  texto: string;
  numero?: string | null;
  cantos?: string[];
  legenda?: string | null;
  termico?: boolean;
  corLinha: string;
  corTexto: string;
  corAcento: string;
  u: number;
  vira?: FichaDados['vira'];
  tVira?: number;
}> = ({ x, y, tam, inicio, seed, texto: texto0, numero: numero0, cantos: cantos0 = [], legenda: legenda0, termico = false, corLinha, corTexto, corAcento, u, vira, tVira = 1e7 }) => {
  const f = useCurrentFrame();
  const kv = vira ? interpolate(f, [tVira, tVira + 12], [0, 1], { ...clamp, easing: ease.padrao }) : 0;
  const virou = kv >= 0.5 && !!vira;
  const texto = virou ? vira!.texto : texto0;
  const numero = virou ? vira!.numero ?? numero0 : numero0;
  const cantos = virou ? vira!.cantos ?? cantos0 : cantos0;
  const legenda = virou ? vira!.legenda ?? legenda0 : legenda0;
  const giroY = Math.abs(Math.cos(Math.PI * kv));
  const kb = interpolate(f, [inicio, inicio + 16], [0, 1], { ...clamp, easing: ease.padrao });
  const kc = interpolate(f, [inicio + 8, inicio + 22], [0, 1], { ...clamp, easing: ease.saida });
  const kt = interpolate(f, [inicio + 18, inicio + 26], [0, 1], clamp);
  if (f < inicio) return null;
  const tinta = termico ? '#141414' : corTexto;
  const tTexto = tam * (texto.length <= 2 ? 0.46 : texto.length <= 4 ? 0.3 : 0.2);
  const canto = (t: string | undefined, pos: React.CSSProperties, grande = false) =>
    t ? (
      <div style={{ position: 'absolute', ...pos, fontFamily: fonte.rotulo, fontWeight: grande ? 600 : 600, fontSize: (grande ? 0.16 : 0.075) * tam, lineHeight: 1, color: grande && !termico ? corAcento : tinta }}>
        {t}
      </div>
    ) : null;
  return (
    <div style={{ position: 'absolute', left: x, top: y, width: tam, height: tam, transform: `scaleX(${giroY}) scale(${1 + 0.08 * Math.sin(Math.PI * kv)})` }}>
      {termico ? (
        <div style={{ position: 'absolute', inset: 0, opacity: kt }}>
          <TermicoRect w={tam} h={tam} seed={seed} escala={0.012} />
        </div>
      ) : null}
      <div style={{ position: 'absolute', inset: 0, border: `${Math.max(1, 2 * u)}px solid ${corLinha}`, clipPath: `inset(${(1 - kb) * 50}% 0 ${(1 - kb) * 50}% 0)` }} />
      <div style={{ position: 'absolute', inset: 0, opacity: kc, transform: `translateY(${(1 - kc) * 10 * u}px)` }}>
        {canto(cantos[0], { left: 0.07 * tam, top: 0.07 * tam })}
        {canto(numero ?? undefined, { right: 0.07 * tam, top: 0.05 * tam }, true)}
        <div
          style={{
            position: 'absolute', left: 0, right: 0, top: 0, bottom: 0, display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontFamily: fonte.rotulo, fontWeight: 700, fontSize: tTexto, color: tinta, letterSpacing: '-0.02em',
          }}
        >
          {texto}
        </div>
        {canto(cantos[1], { left: 0.07 * tam, bottom: 0.07 * tam })}
        {canto(cantos[2], { right: 0.07 * tam, bottom: 0.07 * tam })}
      </div>
      {legenda ? (
        <div
          style={{
            position: 'absolute', left: 0, top: tam + 16 * u, width: tam * 1.6, fontFamily: fonte.rotulo, fontWeight: 600, fontSize: 22 * u,
            letterSpacing: '0.14em', textTransform: 'uppercase', color: corTexto, opacity: kc * 0.85,
          }}
        >
          {legenda}
        </div>
      ) : null}
    </div>
  );
};
