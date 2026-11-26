import React, { useLayoutEffect, useRef } from 'react';
import { AbsoluteFill, cancelRender, continueRender, delayRender, interpolate, spring, useCurrentFrame } from 'remotion';
import { txt } from '../comp/i18n';
import { alfa, clamp, ease, fonte, q, T, TEMPO } from '../comp/tokens';
import type { PropsCena } from '../tipos';

/**
 * Peça de dominó (cada elo da cadeia é uma peça que cai).
 *
 * modo "peca": a fileira em 3/4 sobre um piso escuro; as peças anteriores já caíram e a última delas está
 * apoiada na peça ATUAL, de pé. A face da atual se escreve (pontos, "PEÇA n", data, título); na queda
 * (palavra `ancora`, ou ~60% da cena) ela tomba sobre a próxima peça (em branco: o próximo elo) — clique de
 * dominó (som.py, mesmos tempos) e a câmera acompanha. A cena seguinte do tipo começa nesse mesmo estado.
 * modo "recapitulacao": todas as peças (`pecas`) em fileira, caindo em sequência no tempo das âncoras, com a
 * câmera seguindo a frente da queda; no fim afasta para mostrar a fileira inteira deitada.
 *
 * Física simplificada (2D, no plano da face): cada peça gira no canto inferior da frente da queda; o ângulo
 * é o menor entre a queda livre (aceleração constante) e o contato com a peça seguinte — a fileira apoiada
 * resolve-se de trás para frente a cada quadro. Tempos de queda vêm do Python (dados.quedas, dados.dq).
 */

type Peca = { numero?: number; data?: string; titulo?: string };

// geometria em "u" (1 u = 1 px a 1080p). Espelhada em pipeline/remotion.py (DOMINO_*): mude nos dois.
const TW = 330; // largura da face
const TH = 620; // altura
const TD = 66; // espessura
const GAP = 170; // vão entre peças (apoio de pé = asin(GAP/TH) ≈ 16°; deitadas, cada uma descansa no canto da seguinte)
const P = TW + GAP; // passo da fileira (pivô a pivô)
const THETA0 = Math.asin(GAP / TH);
const RET = Math.PI / 2;

// pontos do dominó (grade 3×3: 0..8 = linha*3+coluna)
const PONTOS: Record<number, number[]> = {
  1: [4],
  2: [0, 8],
  3: [0, 4, 8],
  4: [0, 2, 6, 8],
  5: [0, 2, 4, 6, 8],
  6: [0, 2, 3, 5, 6, 8],
  7: [0, 2, 3, 4, 5, 6, 8],
  8: [0, 1, 2, 3, 5, 6, 7, 8],
  9: [0, 1, 2, 3, 4, 5, 6, 7, 8],
};

const paleta = () => ({
  fundo: '#0E0E10',
  marfim: '#F2E8D5',
  marfim_sombra: '#CDBF9F',
  tinta: '#1C1813',
  tijolo: '#C8432B',
  ouro: '#C9A55C',
  ouro_escuro: '#8A6A2E',
  ...((T as Record<string, any>).domino ?? {}),
});

/** Ângulo (rad) em que a peça i encosta na seguinte, girada `phi`. Pivôs a P de distância. */
const anguloContato = (phi: number): number => {
  const c = Math.cos(phi);
  const s = Math.sin(phi);
  const B = [P - TW * c, TW * s]; // canto inferior esquerdo da seguinte, já girado
  const d = [s, c]; // direção da face esquerda (para cima)
  const K = [B[0] + TH * d[0], B[1] + TH * d[1]];
  const cands: number[] = [];
  // (a) canto superior direito da peça i, C(θ) = (TH sinθ, TH cosθ), cai sobre o segmento B→K
  const fz = (th: number) => (TH * Math.sin(th) - B[0]) * d[1] - (TH * Math.cos(th) - B[1]) * d[0];
  let a = 0;
  let b = RET;
  if (fz(a) < 0 && fz(b) > 0) {
    for (let k = 0; k < 32; k++) {
      const m = (a + b) / 2;
      if (fz(m) < 0) a = m;
      else b = m;
    }
    const t = (TH * Math.sin(a) - B[0]) * d[0] + (TH * Math.cos(a) - B[1]) * d[1];
    if (t >= 0 && t <= TH) cands.push(a);
  }
  // (b) uma ponta do segmento (canto da seguinte) encosta na face direita da peça i
  for (const pt of [B, K]) {
    if (pt[1] >= 0 && Math.hypot(pt[0], pt[1]) <= TH) cands.push(Math.atan2(pt[0], pt[1]));
  }
  return cands.length ? Math.max(0, Math.min(...cands)) : RET;
};

/** Queda livre: ângulo que chega a THETA0 (contato com a vizinha de pé) exatamente em dq segundos. */
const quedaLivre = (t: number, inicio: number | null, dq: number) => {
  if (inicio === null || t <= inicio) return 0;
  const x = (t - inicio) / dq;
  return Math.min(RET, THETA0 * x * x);
};

const mola = (frame: number, fps: number, cfg = { damping: 26, stiffness: 120, mass: 0.9 }) => (frame <= 0 ? 0 : spring({ frame, fps, config: cfg }));

/** Retângulo de cantos arredondados (caminho). */
const caminhoArred = (ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number) => {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
};

/** Quebra o título em linhas que caibam na largura. */
const quebrar = (ctx: CanvasRenderingContext2D, palavras: string[], largura: number) => {
  const linhas: string[][] = [];
  let atual: string[] = [];
  for (const w of palavras) {
    const teste = [...atual, w].join(' ');
    if (atual.length && ctx.measureText(teste).width > largura) {
      linhas.push(atual);
      atual = [w];
    } else atual.push(w);
  }
  if (atual.length) linhas.push(atual);
  return linhas;
};

/**
 * Face da peça (marfim) desenhada em <canvas>: pontos, "PEÇA n", fio central com rebite, data e título.
 * Canvas e não DOM: texto dentro de camada 3D era re-rasterizado a cada quadro (o render caía para ~1 q/s);
 * a face vira uma textura só. `revela` = quadro em que a face começa a se escrever (null = já escrita).
 */
const Face: React.FC<{
  peca: Peca;
  u: number;
  pal: ReturnType<typeof paleta>;
  revela: number | null;
  vazia?: boolean;
  fps: number;
}> = ({ peca, u, pal, revela, vazia = false, fps }) => {
  const f = useCurrentFrame();
  const ref = useRef<HTMLCanvasElement>(null);
  const K = 1.6; // supersampling: a peça chega perto da câmera e ainda leva zoom
  const cw = Math.round(TW * u * K);
  const ch = Math.round(TH * u * K);
  const e = u * K; // px de canvas por "u"
  const r0 = revela ?? -1e6;
  // estado da animação neste quadro (só números: o efeito redesenha quando algum muda)
  const kFio = vazia ? 1 : interpolate(f, [r0, r0 + q(16, fps)], [0, 1], { ...clamp, easing: ease.padrao });
  const kChapeu = interpolate(f, [r0 + q(8, fps), r0 + q(24, fps)], [0, 1], { ...clamp, easing: ease.saida });
  const kData = revela === null ? 1 : mola(f - r0 - q(14, fps), fps);
  const n = peca.numero ?? 0;
  const lista = PONTOS[n];
  const kPontos = (lista ?? [0]).map((_, i) => (revela === null ? 1 : mola(f - r0 - i * 2, fps, { damping: 15, stiffness: 190, mass: 0.6 })));
  const palavras = (peca.titulo ?? '').split(/\s+/).filter(Boolean);
  const kPal = palavras.map((_, i) => (revela === null ? 1 : mola(f - r0 - q(22, fps) - i * 2, fps)));
  const estado = [kFio, kChapeu, kData, ...kPontos, ...kPal].map((x) => x.toFixed(4)).join(',');

  useLayoutEffect(() => {
    const cv = ref.current;
    if (!cv) return;
    const h = delayRender('face-domino');
    const desenhar = () => {
      const ctx = cv.getContext('2d')!;
      ctx.clearRect(0, 0, cw, ch);
      // corpo marfim com chanfro (luz em cima, sombra embaixo, fio de contorno)
      const raio = 18 * e;
      caminhoArred(ctx, 0, 0, cw, ch, raio);
      const g = ctx.createLinearGradient(0, 0, cw * 0.55, ch);
      g.addColorStop(0, pal.marfim);
      g.addColorStop(0.6, pal.marfim);
      g.addColorStop(1, pal.marfim_sombra);
      ctx.fillStyle = g;
      ctx.fill();
      ctx.save();
      ctx.clip();
      const sb = ctx.createLinearGradient(0, ch - 22 * e, 0, ch);
      sb.addColorStop(0, 'rgba(60,40,10,0)');
      sb.addColorStop(1, 'rgba(60,40,10,0.22)');
      ctx.fillStyle = sb;
      ctx.fillRect(0, ch - 22 * e, cw, 22 * e);
      ctx.fillStyle = 'rgba(255,255,255,0.65)';
      ctx.fillRect(0, 0, cw, 3 * e);
      ctx.restore();
      caminhoArred(ctx, e, e, cw - 2 * e, ch - 2 * e, raio - e);
      ctx.strokeStyle = 'rgba(60,40,10,0.18)';
      ctx.lineWidth = 2 * e;
      ctx.stroke();
      // fio central + rebite de latão (a "barra" do dominó)
      const yFio = ch / 2;
      ctx.fillStyle = pal.ouro_escuro;
      const lf = cw * 0.8 * kFio;
      ctx.fillRect(cw / 2 - lf / 2, yFio - 2 * e, lf, 4 * e);
      const rg = ctx.createRadialGradient(cw / 2 - 3 * e, yFio - 3 * e, 0, cw / 2, yFio, 9 * e);
      rg.addColorStop(0, '#F1DDA6');
      rg.addColorStop(0.45, pal.ouro);
      rg.addColorStop(1, pal.ouro_escuro);
      ctx.beginPath();
      ctx.arc(cw / 2, yFio, 9 * e, 0, Math.PI * 2);
      ctx.fillStyle = rg;
      ctx.fill();
      if (vazia) return;
      // pontos "cavados" (ou o algarismo, acima de 9)
      if (lista) {
        const rp = TW * 0.0525 * e;
        lista.forEach((pos, i) => {
          const k = kPontos[i];
          if (k <= 0.001) return;
          const x = TW * (0.24 + (pos % 3) * 0.26) * e;
          const y = TH * (0.095 + Math.floor(pos / 3) * 0.118) * e;
          ctx.beginPath();
          ctx.arc(x, y + 1.5 * e * k, rp * k, 0, Math.PI * 2);
          ctx.fillStyle = 'rgba(255,255,255,0.55)';
          ctx.fill();
          ctx.beginPath();
          ctx.arc(x, y, rp * k, 0, Math.PI * 2);
          ctx.fillStyle = n === 1 ? pal.tijolo : pal.tinta;
          ctx.fill();
          const sh = ctx.createLinearGradient(0, y - rp, 0, y + rp);
          sh.addColorStop(0, 'rgba(0,0,0,0.45)');
          sh.addColorStop(0.5, 'rgba(0,0,0,0)');
          ctx.fillStyle = sh;
          ctx.fill();
        });
      } else if (n > 0) {
        ctx.save();
        ctx.globalAlpha = Math.min(1, kPontos[0]);
        ctx.font = `700 ${TH * 0.26 * e}px ${fonte.titulo}`;
        ctx.textAlign = 'center';
        ctx.fillStyle = pal.tinta;
        ctx.fillText(String(n), cw / 2, TH * 0.32 * e);
        ctx.restore();
      }
      // "PEÇA n"
      if (kChapeu > 0) {
        ctx.save();
        ctx.globalAlpha = kChapeu;
        ctx.font = `600 ${22 * e}px ${fonte.rotulo}`;
        (ctx as unknown as { letterSpacing: string }).letterSpacing = `${0.32 * 22 * e}px`;
        ctx.textAlign = 'center';
        ctx.fillStyle = pal.tijolo;
        ctx.fillText(`${txt().peca} ${n || ''}`.toUpperCase(), cw / 2 + 0.16 * 22 * e, TH * 0.44 * e + (1 - kChapeu) * 10 * e);
        ctx.restore();
      }
      // data: sobe de trás de uma máscara
      if (peca.data) {
        const top = TH * 0.545 * e;
        const alt = 72 * e;
        ctx.save();
        ctx.beginPath();
        ctx.rect(0, top, cw, alt);
        ctx.clip();
        ctx.font = `700 ${60 * e}px ${fonte.titulo}`;
        ctx.textAlign = 'center';
        ctx.fillStyle = pal.ouro_escuro;
        ctx.fillText(peca.data, cw / 2, top + 58 * e + (1 - kData) * alt * 1.05);
        ctx.restore();
      }
      // título: palavra a palavra, cada uma de trás da sua fenda
      if (palavras.length) {
        const titulo = peca.titulo ?? '';
        const tam = titulo.length > 34 ? 31 : titulo.length > 22 ? 35 : 40;
        ctx.font = `600 ${tam * e}px ${fonte.titulo}`;
        ctx.textAlign = 'left';
        const linhas = quebrar(ctx, palavras, TW * 0.84 * e);
        const lh = tam * 1.14 * e;
        const topo = TH * (peca.data ? 0.68 : 0.585) * e;
        const esp = ctx.measureText(' ').width;
        let idx = 0;
        linhas.forEach((ws, li) => {
          const total = ctx.measureText(ws.join(' ')).width;
          let x = cw / 2 - total / 2;
          const yb = topo + li * lh + tam * 0.9 * e;
          ws.forEach((w) => {
            const k = kPal[idx++] ?? 1;
            const ww = ctx.measureText(w).width;
            ctx.save();
            ctx.beginPath();
            ctx.rect(x - 2 * e, yb - tam * 0.95 * e, ww + 4 * e, lh);
            ctx.clip();
            ctx.fillStyle = pal.tinta;
            ctx.fillText(w, x, yb + (1 - k) * lh * 1.08);
            ctx.restore();
            x += ww + esp;
          });
        });
      }
    };
    const fontes = [`600 ${22 * e}px ${fonte.rotulo}`, `700 ${60 * e}px ${fonte.titulo}`, `600 ${40 * e}px ${fonte.titulo}`];
    Promise.all(fontes.map((x) => document.fonts.load(x)))
      .then(() => {
        desenhar();
        continueRender(h);
      })
      .catch((err) => cancelRender(err));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [estado, cw, ch, vazia, peca.titulo, peca.data, n]);

  return <canvas ref={ref} width={cw} height={ch} style={{ position: 'absolute', left: 0, top: 0, width: '100%', height: '100%', borderRadius: 18 * u }} />;
};

/** Uma peça em 3D (caixa: frente, lado e topo), girando no canto inferior direito. */
const Pedra: React.FC<{
  x: number; // pivô (canto inferior direito), em u
  ang: number; // rad, horário
  u: number;
  pal: ReturnType<typeof paleta>;
  peca: Peca;
  revela: number | null;
  vazia?: boolean;
  escurecer?: number;
  fps: number;
}> = ({ x, ang, u, pal, peca, revela, vazia, escurecer = 0, fps }) => {
  // a face recebe menos luz quando deita (luz vem de cima e um pouco da frente)
  const sombraAng = 0.32 * Math.sin(ang);
  return (
    <div
      style={{
        position: 'absolute',
        left: (x - TW) * u,
        top: -TH * u,
        width: TW * u,
        height: TH * u,
        transformStyle: 'preserve-3d',
        transformOrigin: '100% 100%',
        transform: `rotateZ(${(ang * 180) / Math.PI}deg)`,
      }}
    >
      {/* lado direito (espessura) */}
      <div
        style={{
          position: 'absolute',
          left: (TW - TD / 2) * u,
          top: 0,
          width: TD * u,
          height: TH * u,
          background: `linear-gradient(90deg, ${pal.marfim_sombra}, #A89A7C)`,
          borderRadius: 10 * u,
          transform: 'rotateY(90deg)',
        }}
      />
      {/* topo */}
      <div
        style={{
          position: 'absolute',
          left: 0,
          top: -TD / 2 * u,
          width: TW * u,
          height: TD * u,
          background: `linear-gradient(0deg, ${pal.marfim}, #FFF8EA)`,
          borderRadius: 10 * u,
          transform: 'rotateX(90deg)',
        }}
      />
      {/* frente */}
      <div style={{ position: 'absolute', inset: 0, transform: `translateZ(${(TD / 2) * u}px)` }}>
        <Face peca={peca} u={u} pal={pal} revela={revela} vazia={vazia} fps={fps} />
        <AbsoluteFill style={{ borderRadius: 18 * u, background: `rgba(14,10,6,${Math.min(0.85, escurecer + sombraAng)})` }} />
      </div>
    </div>
  );
};

export const Domino: React.FC<{ p: PropsCena }> = ({ p }) => {
  const f = useCurrentFrame();
  const d = p.dados;
  const W = p.largura;
  const H = p.altura;
  // vertical (Shorts 9:16, pipeline/shorts.py): a peça é medida pela LARGURA e o piso sobe para cima da legenda
  const retrato = H > W * 1.2;
  const u = retrato ? (W / 1080) * 1.1 : H / 1080;
  const fps = p.fps;
  const pal = paleta();
  const t = (f - p.alca_antes) / fps; // segundos no corpo
  const dq: number = d.dq ?? 0.42;
  const recap = d.modo === 'recapitulacao';
  const pecasDados: Peca[] = Array.isArray(d.pecas) ? d.pecas : [];
  const quedas: number[] = Array.isArray(d.quedas) ? d.quedas : [];
  const corpo = p.corpo / fps;

  // ---- fileira: lista de peças (índice 0..), qual cai quando
  type Item = { peca: Peca; x: number; inicio: number | null; base: number; vazia?: boolean; revela: number | null; escurecer: number };
  const itens: Item[] = [];
  let foco = 0; // índice da peça em foco (câmera)
  if (recap) {
    const n = Math.max(2, pecasDados.length);
    for (let i = 0; i < n; i++) {
      const pc = { numero: i + 1, ...(pecasDados[i] ?? {}) };
      itens.push({ peca: pc, x: (i + 1) * P, inicio: quedas[i] ?? 0.6 + i * dq * 2, base: 0, revela: null, escurecer: 0 });
    }
  } else {
    const n: number = Math.max(1, Number(d.numero) || 1);
    const anteriores = Math.min(n - 1, 3); // até 3 peças já caídas atrás
    for (let k = anteriores; k >= 1; k--) {
      const num = n - k;
      const dadosAnt = pecasDados[num - 1] ?? {};
      itens.push({ peca: { numero: num, ...dadosAnt }, x: 0, inicio: -100, base: RET, revela: null, escurecer: 0.32 });
    }
    foco = itens.length;
    itens.push({
      peca: { numero: n, data: d.data, titulo: d.titulo },
      x: 0,
      inicio: quedas[0] ?? Math.max(1.8, corpo * 0.6),
      base: 0,
      revela: p.alca_antes + q(TEMPO.atrasoInicial, fps),
      escurecer: 0,
    });
    itens.push({ peca: { numero: n + 1 }, x: 0, inicio: null, base: 0, vazia: true, revela: null, escurecer: 0.22 });
    itens.forEach((it, i) => (it.x = (i + 1) * P));
  }

  // ---- ângulos: de trás para frente (a peça da frente decide onde a de trás se apoia)
  const angs = new Array(itens.length).fill(0);
  for (let i = itens.length - 1; i >= 0; i--) {
    const it = itens[i];
    let livre = it.base >= RET ? RET : quedaLivre(t, it.inicio, dq);
    if (!recap && it.vazia) {
      // a próxima peça leva o empurrão, balança e fica (ela cai na próxima cena do tipo)
      const tc = (itens[i - 1].inicio ?? 1e9) + dq;
      const x = t - tc;
      livre = x > 0 ? Math.max(0, 0.075 * Math.exp(-x * 5.5) * Math.sin(x * Math.PI * 2 * 1.7)) : 0;
    }
    angs[i] = i === itens.length - 1 ? livre : Math.min(livre, anguloContato(angs[i + 1]));
  }

  // ---- câmera
  const xFoco = (i: number) => itens[Math.max(0, Math.min(itens.length - 1, i))].x - TW / 2;
  let camX: number;
  let z: number;
  let giro = 0; // 0 = 3/4 de perto; 1 = mais frontal e mais alto (visão da fileira inteira)
  if (recap) {
    // segue a frente da queda: quando a peça i cai, a câmera viaja até a i+1 (0,9 s, easeInOut)
    camX = xFoco(0) + 40;
    for (let i = 0; i < itens.length - 1; i++) {
      const a = (itens[i].inicio ?? 0) + dq * 0.4;
      camX += (xFoco(i + 1) - xFoco(i)) * interpolate(t, [a, a + 0.9], [0, 1], { ...clamp, easing: ease.camera });
    }
    // fim: afasta e mostra a fileira inteira
    const largura = (itens.length - 1) * P + TW + TH;
    // vertical: a fileira inteira não cabe na largura — o fim mostra as últimas peças deitadas, mais de perto
    const zFim = retrato ? 0.62 : Math.min(1, (0.8 * W) / (largura * u));
    const tFim = Math.max((itens[itens.length - 1].inicio ?? 0) + dq * 2.5, corpo - 1.6);
    const kFim = interpolate(t, [tFim, tFim + 1.4], [0, 1], { ...clamp, easing: ease.camera });
    // + 9%: com o giro em 3/4 o fim da fila fica mais perto da câmera (maior) e puxa o conjunto para a direita
    const centroFila = retrato
      ? itens[itens.length - 1].x - P * 0.9
      : (itens[0].x - TW + itens[itens.length - 1].x + TH * 0.9) / 2 + largura * 0.09;
    camX = camX + (centroFila - camX) * kFim;
    z = interpolate(t, [-0.3, corpo], [1.04, 1.0], clamp) * (1 - kFim) + zFim * kFim;
    giro = kFim;
  } else {
    const ini = itens[foco].inicio ?? corpo;
    const k = interpolate(t, [ini, ini + 1.1], [0, 1], { ...clamp, easing: ease.camera });
    // sem peças caídas atrás (peça 1), o enquadramento puxa para a direita: nada de canto vazio
    camX = xFoco(foco) + (retrato ? 20 : foco === 0 ? P * 0.3 : 40) + k * P * (retrato ? 0.5 : 0.42);
    z = interpolate(t, [-p.alca_antes / fps, corpo], [1.0, 1.06], { ...clamp, easing: ease.padrao });
  }
  // tranco curto a cada contato (2–4 px), sem balanço ocioso
  let tranco = 0;
  const contatos = itens.map((it) => (it.inicio !== null && it.inicio > -50 ? it.inicio + dq : null)).filter((x): x is number => x !== null);
  for (const tc of contatos) {
    const x = t - tc;
    if (x >= 0 && x < 0.25) tranco += Math.exp(-x * 18) * Math.sin(x * 90) * 5;
  }

  // entrada da cena: fileira surge do escuro
  const entra = interpolate(f, [0, p.alca_antes + q(TEMPO.entrada, fps)], [0, 1], { ...clamp, easing: ease.saida });
  const yPiso = retrato ? H * (0.54 - 0.03 * giro) : H * (0.79 - 0.13 * giro);
  const persp = 2600 * u;

  // sombras de contato no piso (projeção da peça deitando)
  const sombras = itens.map((it, i) => {
    const a = angs[i];
    const x0 = it.x - TW * Math.cos(a);
    const x1 = it.x + TH * Math.sin(a);
    return { x0: Math.min(x0, it.x - TW), x1: Math.max(x1, it.x), forca: 0.35 + 0.35 * Math.sin(a) };
  });

  return (
    <AbsoluteFill style={{ background: pal.fundo, overflow: 'hidden' }}>
      {/* luz quente de cima, atrás da fileira */}
      <AbsoluteFill
        style={{
          background: `radial-gradient(${W * 0.55}px ${H * 0.5}px at ${W * 0.47}px ${H * 0.52}px, ${alfa(pal.ouro, 0.13)} 0%, ${alfa(pal.ouro, 0.04)} 55%, rgba(0,0,0,0) 100%)`,
          opacity: entra,
        }}
      />
      <AbsoluteFill
        style={{
          background: `radial-gradient(${W * 0.62}px ${H * 0.16}px at ${W * 0.5}px ${yPiso + H * 0.02}px, ${alfa(pal.ouro, 0.14)} 0%, ${alfa(pal.ouro, 0.04)} 60%, rgba(0,0,0,0) 100%)`,
          opacity: entra,
        }}
      />
      <AbsoluteFill style={{ perspective: persp, perspectiveOrigin: `50% ${H * 0.42}px`, opacity: entra }}>
        <div
          style={{
            position: 'absolute',
            left: W / 2,
            top: yPiso,
            width: 0,
            height: 0,
            transformStyle: 'preserve-3d',
            transform: `translateY(${tranco * u}px) scale(${z}) rotateX(${-9 - 9 * giro}deg) rotateY(${-24 + 12 * giro}deg) translateX(${-camX * u}px)`,
          }}
        >
          {/* piso: só as sombras de contato (gradiente pronto; filtro blur por quadro derrubava o render) */}
          <div style={{ position: 'absolute', left: 0, top: 0, width: 0, height: 0, transformStyle: 'preserve-3d', transform: 'rotateX(90deg)' }}>
            {sombras.map((s, i) => (
              <div
                key={i}
                style={{
                  position: 'absolute',
                  left: (s.x0 - 70) * u,
                  top: -TD * 1.6 * u,
                  width: (s.x1 - s.x0 + 140) * u,
                  height: TD * 3.2 * u,
                  background: `radial-gradient(closest-side, rgba(0,0,0,${s.forca}) 0%, rgba(0,0,0,${s.forca * 0.55}) 45%, rgba(0,0,0,0) 100%)`,
                }}
              />
            ))}
          </div>
          {itens.map((it, i) => (
            <Pedra
              key={i}
              x={it.x}
              ang={angs[i]}
              u={u}
              pal={pal}
              peca={it.peca}
              revela={it.revela}
              vazia={it.vazia}
              escurecer={it.escurecer}
              fps={fps}
            />
          ))}
        </div>
      </AbsoluteFill>
      {/* vinheta própria (o acabamento do montar.py ainda põe a dele e o grão) */}
      <AbsoluteFill style={{ background: 'radial-gradient(115% 95% at 50% 45%, rgba(0,0,0,0) 52%, rgba(0,0,0,0.62) 100%)' }} />
    </AbsoluteFill>
  );
};
