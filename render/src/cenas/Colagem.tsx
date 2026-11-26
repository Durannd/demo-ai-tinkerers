import React from 'react';
import { AbsoluteFill, Img, interpolate, Loop, OffthreadVideo, staticFile, useCurrentFrame } from 'remotion';
import { quadro, tempoDe, Textura } from '../comp/Base';
import { definirTextura, FichaDados, FiltroTermico, FioNome, Ficha, FORMAS, FormaTermica, Icone, Riscos, Surge, Vazamento } from '../comp/Elementos';
import type { Forma } from '../comp/Elementos';
import { Entrada, LetrasAleatorias, Saida, sortearEntrada } from '../comp/Movimento';
import type { TipoEntrada } from '../comp/Movimento';
import { alfa, clamp, cor, ease, fonte, q, rng, T, TEMPO } from '../comp/tokens';
import type { PropsCena } from '../tipos';

/**
 * Colagem editorial (linguagem dos explicativos da BBC News Brasil / Vox): a foto de arquivo NÃO some —
 * vira matéria-prima de uma composição gráfica sobre fundo de estúdio (grafite ou papel claro) com
 * riscos de película e vazamento de luz.
 *
 *  retrato  sujeito recortado (ISNet, pipeline/colagem.py) em P&B, texto GIGANTE (ano/palavra) ATRÁS dele,
 *           fio com nome + ano; o recorte pode "esquentar" (mapa térmico) numa palavra da narração.
 *  circulo  círculo fino em volta da cabeça; dentro dele a foto inteira, escura; o recorte transborda.
 *  janela   foto ou VÍDEO numa janela com moldura deslocada (sem recorte) — serve para qualquer mídia.
 *
 * Extras (todos opcionais, cada um num momento da fala): icone (raio, ?, radiação, caveira... sólido ou
 * térmico, numa mira quadrada), ficha (quadrado de dado tipo tabela periódica), termico (palavra).
 * imagens = [foto ou vídeo, recorte RGBA do MESMO tamanho da foto (só retrato/circulo)].
 */
/** quadro "nunca" (finito: o interpolate do Remotion recusa Infinity) */
const NUNCA = 1e7;

export const Colagem: React.FC<{ p: PropsCena }> = ({ p }) => {
  const f = useCurrentFrame();
  const d = p.dados;
  const W = p.largura;
  const H = p.altura;
  const u = H / 1080;
  const C = T.colagem;
  const claro = d.base === 'clara';
  const fundo = claro ? C.fundo_claro : C.fundo_escuro;
  const corLinha = claro ? C.tinta_clara : C.linha;
  const corNome = claro ? cor.destaque : C.nome;
  const corSub = claro ? alfa(C.tinta_clara, 0.7) : cor.texto_suave;
  const [midia, recorte] = p.imagens ?? [];
  const layout: string = recorte ? d.layout ?? 'retrato' : 'janela';
  const asp: number = d.aspecto ?? p.aspectos?.[0] ?? 1.5;
  const [bx0, by0, bx1, by1]: number[] = d.bbox ?? [0.2, 0.1, 0.8, 1];
  const bw = Math.max(0.05, bx1 - bx0);
  const bh = Math.max(0.05, by1 - by0);
  const tocaBase: boolean = d.toca_base ?? true;
  const temFicha = !!d.ficha?.texto;
  const temNome = !!(d.titulo || d.ano);
  definirTextura(p.seed, d.textura);

  // ---- tempos (quadros do render): cada elemento no momento em que a narração o pede
  const ini = p.alca_antes + q(TEMPO.atrasoInicial, p.fps);
  const corpoS = p.corpo / p.fps;
  const dito = (cands: (string | undefined | null)[], padrao: number) => quadro(p, tempoDe(p.palavras, cands, padrao)) - q(TEMPO.antecipacao, p.fps);
  const tFundo = Math.max(ini + 4, dito([d.texto_fundo, d.ano], 0.35));
  const tNome = Math.max(ini + q(12, p.fps), dito([d.titulo?.split(/\s+/).pop(), d.titulo, d.ano], 0.6));
  const tTerm = typeof d.termico === 'string' ? dito([d.termico], corpoS * 0.45) : d.termico ? ini + q(TEMPO.entradaLonga, p.fps) : NUNCA;
  const tIcone = d.icone ? dito([d.icone.em], corpoS * 0.5) : NUNCA;
  const tFicha = temFicha ? Math.max(ini + q(10, p.fps), dito([d.ficha.em, d.ficha.texto], corpoS * 0.4)) : NUNCA;
  const tDup = d.dupla && recorte ? (d.dupla_em ? dito([d.dupla_em], corpoS * 0.55) : Math.round(p.alca_antes + p.corpo * 0.55)) : NUNCA;

  // ---- câmera em três tempos (a cena nunca repousa):
  //  1) assenta: a composição chega 6% maior e pousa;  2) reenquadra no meio da fala (recua, avança ou
  //  desliza), com um elemento novo (disco/retângulo que se estica);  3) sai: recolhe nos últimos quadros.
  const r = rng(p.seed + 101);
  const kCam = interpolate(f, [0, p.frames], [0, 1], clamp);
  const fimCorpo = p.alca_antes + p.corpo;
  const kAssenta = interpolate(f, [ini - 4, ini + q(26, p.fps)], [0, 1], { ...clamp, easing: ease.saida });
  const temBeat2 = corpoS >= 4.2;
  const t2 = Math.round(Math.max(tNome + q(30, p.fps), p.alca_antes + p.corpo * 0.5));
  const k2 = temBeat2 ? interpolate(f, [t2, t2 + q(24, p.fps)], [0, 1], { ...clamp, easing: ease.camera }) : 0;
  // cena longa: 3º tempo (volta parcial, como quem reenquadra de novo)
  const t3 = Math.round(p.alca_antes + p.corpo * 0.8);
  const k3 = corpoS >= 7 ? interpolate(f, [t3, t3 + q(22, p.fps)], [0, 1], { ...clamp, easing: ease.camera }) : 0;
  const kBeat = k2 - 0.55 * k3;
  const reenq: string = d.reenquadra ?? (['recua', 'avanca', 'desliza'] as const)[Math.floor(r() * 3) % 3];
  const zoom = (1.08 - 0.08 * kAssenta) * (1 + 0.06 * kCam) * (reenq === 'recua' ? 1 - 0.18 * kBeat : reenq === 'avanca' ? 1 + 0.2 * kBeat : 1 + 0.04 * kBeat);
  const desliza = reenq === 'desliza' ? -kBeat * W * 0.1 : 0;
  // forma do 2º tempo: disco sólido (como o da referência) ou forma texturizada (disco, anel, losango, faixa, mancha, hexágono)
  const formaFundo: string = d.forma ?? (['solido', ...FORMAS] as string[])[Math.floor(r() * (FORMAS.length + 1)) % (FORMAS.length + 1)];
  const tipoSaida = (['recolhe', 'sobe', 'lado'] as const)[Math.floor(r() * 3) % 3];

  // ---- geometria do sujeito (a foto inteira é posicionada de modo que a CAIXA do recorte caia no alvo)
  // objeto = recorte de coisa (prédio, máquina, semente) centrado sobre um retângulo fino deslocado
  const objeto = layout === 'objeto';
  const temTxtFundo = !!d.texto_fundo;
  const cxAlvo = W * (temFicha ? 0.34 : layout === 'circulo' ? (temNome ? 0.62 : 0.5) : temNome ? (objeto ? 0.64 : 0.6) : 0.5);
  let alvoH =
    H * (layout === 'circulo' ? (tocaBase ? 0.98 : 0.8) : objeto ? (temTxtFundo ? 0.5 : 0.6) : tocaBase ? 0.88 : temTxtFundo ? 0.56 : 0.72);
  let ih = alvoH / bh;
  const maxLarg = W * (temFicha ? 0.44 : objeto ? (temNome ? 0.44 : 0.5) : 0.56);
  if (bw * ih * asp > maxLarg) {
    ih = maxLarg / (bw * asp);
    alvoH = bh * ih;
  }
  const iw = ih * asp;
  const baseY = objeto
    ? (temTxtFundo ? H * 0.62 : H * 0.5) + alvoH / 2
    : tocaBase
      ? H * 1.005
      : (temTxtFundo ? H * 0.62 : H * 0.52) + alvoH / 2;
  const left = cxAlvo - ((bx0 + bx1) / 2) * iw;
  const top = baseY - by1 * ih;
  const topoSujeito = top + by0 * ih;

  // ---- entrada do sujeito: tipo sorteado por layout (ou visual.colagem.entrada), com "glitch" RGB
  const opcoes: Record<string, TipoEntrada[]> = {
    retrato: ['fatias', 'baixo', 'lateral', 'persiana'],
    objeto: ['cortina', 'escala', 'giro', 'lateral', 'fatias'],
    circulo: ['baixo', 'escala', 'fatias'],
    janela: ['cortina', 'persiana', 'fatias', 'lateral', 'iris'],
  };
  const entSuj: TipoEntrada = d.entrada ?? sortearEntrada(p.seed, opcoes[layout] ?? opcoes.retrato);
  const tSuj = ini + (layout === 'circulo' ? q(10, p.fps) : q(3, p.fps));
  const kSuj = f >= tSuj ? 1 : 0;
  const glitch = interpolate(f, [tSuj, tSuj + 6], [14, 0], clamp) * u;
  const glitchT = interpolate(f, [tTerm, tTerm + 5], [10, 0], clamp) * u;
  const gx = Math.max(glitch, f >= tTerm ? glitchT : 0);
  const kTerm = interpolate(f, [tTerm, tTerm + 8], [0, 1], clamp);
  const kDup = interpolate(f, [tDup, tDup + q(14, p.fps)], [0, 1], { ...clamp, easing: ease.camera });
  const flash = interpolate(f, [tTerm, tTerm + 2, tTerm + 7], [0, 0.85, 0], clamp);
  const sobe = 0;
  const filtroPB = `grayscale(1) contrast(${claro ? 1.08 : 1.18}) brightness(${claro ? 1.02 : 0.96})${
    gx > 0.2 ? ` drop-shadow(${gx}px 0 0 rgba(255,40,96,0.75)) drop-shadow(${-gx}px 0 0 rgba(40,236,214,0.75))` : ''
  }`;

  // foto cortada rente ao sujeito (ombro saindo pela lateral/topo): a borda reta do recorte se desfaz
  const fadeE = bx0 < 0.012;
  const fadeD = bx1 > 0.988;
  const fadeT = by0 < 0.012;
  const fadeB = objeto && by1 > 0.988; // no objeto a base não encosta na borda da tela: o corte reto some
  const gradH = `linear-gradient(to right, ${fadeE ? 'transparent 0%, black 20%' : 'black 0%'}, ${fadeD ? 'black 80%, transparent 100%' : 'black 100%'})`;
  const gradV = `linear-gradient(to bottom, ${fadeT ? 'transparent 0%, black 12%' : 'black 0%'}, ${fadeB ? 'black 82%, transparent 100%' : 'black 100%'})`;
  const mascaraBorda: React.CSSProperties =
    fadeE || fadeD || fadeT || fadeB
      ? {
          WebkitMaskImage: `${gradH}, ${gradV}`,
          WebkitMaskComposite: 'source-in',
          maskComposite: 'intersect',
          WebkitMaskSize: `${iw}px ${ih}px`,
          WebkitMaskPosition: `${left}px ${top}px`,
          WebkitMaskRepeat: 'no-repeat',
        }
      : {};

  const sujeito = (src: string, comTermico: boolean) => (
    <div style={{ position: 'absolute', inset: 0, transform: `translateY(${sobe}px)`, opacity: kSuj, ...mascaraBorda }}>
      <Img src={staticFile(src)} style={{ position: 'absolute', left, top, width: iw, height: ih, filter: filtroPB }} />
      {comTermico && kTerm > 0 ? (
        <svg width={W} height={H} style={{ position: 'absolute', left: 0, top: 0, opacity: kTerm }}>
          <defs>
            <FiltroTermico id="term-suj" seed={p.seed} escala={0.0035 / u} progresso={(f - tTerm) / Math.max(1, p.frames)} imagem />
          </defs>
          <image href={staticFile(src)} x={left} y={top} width={iw} height={ih} preserveAspectRatio="none" filter="url(#term-suj)" />
        </svg>
      ) : null}
      {flash > 0 ? <Img src={staticFile(src)} style={{ position: 'absolute', left, top, width: iw, height: ih, filter: 'brightness(0) invert(1)', opacity: flash }} /> : null}
      {/* dupla exposição: a foto em cor "entra" por dentro da silhueta, com deriva própria (paralaxe) —
          os contornos do rosto/corpo em P&B continuam por cima da imagem colorida */}
      {kDup > 0 ? (
        <div
          style={{
            position: 'absolute',
            inset: 0,
            opacity: kDup * 0.85,
            mixBlendMode: 'screen',
            WebkitMaskImage: `url("${staticFile(src)}")`,
            WebkitMaskSize: `${iw}px ${ih}px`,
            WebkitMaskPosition: `${left}px ${top}px`,
            WebkitMaskRepeat: 'no-repeat',
            maskImage: `url("${staticFile(src)}")`,
            maskSize: `${iw}px ${ih}px`,
            maskPosition: `${left}px ${top}px`,
            maskRepeat: 'no-repeat',
          }}
        >
          <Img
            src={staticFile(midia)}
            style={{
              position: 'absolute',
              left,
              top,
              width: iw,
              height: ih,
              objectFit: 'cover',
              filter: 'saturate(1.12) contrast(1.06)',
              transform: `translate(${(kCam - 0.5) * 40 * u}px, ${(0.5 - kCam) * 26 * u}px) scale(${1.16 - 0.05 * kCam})`,
              transformOrigin: `${((bx0 + bx1) / 2) * iw}px ${(by0 + bh * 0.2) * ih}px`,
            }}
          />
        </div>
      ) : null}
    </div>
  );

  // ---- texto gigante atrás do sujeito (ano, sigla, palavra-chave)
  const txtFundo: string | undefined = d.texto_fundo ?? undefined;
  const tamFundo = txtFundo ? Math.min(H * 0.36, (W * 0.84) / (0.62 * Math.max(3, txtFundo.length))) : 0;
  // retrato encostado na base: o texto cruza a cabeça; sujeito "solto": o texto fica logo ACIMA dele, só a base escondida
  const yFundo =
    (tocaBase && !objeto ? Math.min(H * 0.42, Math.max(H * 0.2, topoSujeito + alvoH * 0.18)) : Math.max(H * 0.2, topoSujeito + tamFundo * 0.12)) -
    tamFundo * 0.5;
  // retângulo fino atrás do objeto (desenha da ponta superior esquerda)
  const sx0 = left + bx0 * iw;
  const sy0 = top + by0 * ih;
  const sW = bw * iw;
  const sH = bh * ih;
  const kRet = interpolate(f, [ini - 2, ini + q(26, p.fps)], [0, 1], { ...clamp, easing: ease.padrao });
  const fundoTexto = txtFundo ? (
    <div style={{ position: 'absolute', left: 0, width: W, top: yFundo, display: 'flex', justifyContent: 'center', transform: `translateX(${(cxAlvo - W / 2) * 0.6 - kCam * 30 * u}px)` }}>
      <LetrasAleatorias texto={txtFundo} inicio={Math.max(tFundo, ini + q(8, p.fps))} seed={p.seed} tam={tamFundo} cor={claro ? C.tinta_clara : C.linha} />
    </div>
  ) : null;

  // ---- círculo (layout circulo): em volta da cabeça
  const R = Math.min(H * 0.36, alvoH * 0.34);
  const cyC = topoSujeito + R * 0.92;
  const kCirc = interpolate(f, [ini - 2, ini + q(16, p.fps)], [0, 1], { ...clamp, easing: ease.saida });
  const circ = 2 * Math.PI * R;

  // ---- janela (qualquer mídia, inclusive vídeo)
  const jMaxW = W * (temNome || temFicha ? 0.5 : 0.6);
  const jMaxH = H * 0.64;
  const jw = Math.min(jMaxW, jMaxH * asp);
  const jh = jw / asp;
  const jcx = temFicha ? W * 0.36 : temNome ? W * 0.58 : W * 0.5;
  const jx = jcx - jw / 2;
  const jy = H * 0.44 - jh / 2;
  const kMold = interpolate(f, [ini + 6, ini + q(30, p.fps)], [0, 1], { ...clamp, easing: ease.padrao });
  const video: boolean = !!d.video;
  const iniVideo = Math.round((d.inicio_video ?? 0) * p.fps);
  const durVideo = Math.max(1, Math.round((d.dur_video ?? 9999) * p.fps) - iniVideo);
  const midiaJanela = midia ? (
    video ? (
      durVideo < p.frames ? (
        <Loop durationInFrames={durVideo}>
          <OffthreadVideo src={staticFile(midia)} startFrom={iniVideo} muted style={{ width: '100%', height: '100%', objectFit: 'cover', filter: d.pb ? filtroPB : 'none' }} />
        </Loop>
      ) : (
        <OffthreadVideo src={staticFile(midia)} startFrom={iniVideo} muted style={{ width: '100%', height: '100%', objectFit: 'cover', filter: d.pb ? filtroPB : 'none' }} />
      )
    ) : (
      <Img src={staticFile(midia)} style={{ width: '100%', height: '100%', objectFit: 'cover', filter: d.pb ? filtroPB : 'none' }} />
    )
  ) : null;

  // ---- ícone: por padrão, no rosto (terço de cima da caixa do sujeito) ou no centro da janela
  const ic = d.icone;
  const icX = ic?.x !== undefined ? ic.x * W : layout === 'janela' ? jcx : left + ((bx0 + bx1) / 2) * iw;
  const icY = ic?.y !== undefined ? ic.y * H : layout === 'janela' ? H * 0.44 : top + (by0 + bh * 0.22) * ih;

  const ficha: FichaDados | undefined = d.ficha;
  const linhaY = H * 0.78;
  const nomeX = temFicha ? W * 0.62 : W * 0.06;
  const nomeL = temFicha ? W * 0.32 : W * (layout === 'janela' || objeto ? 0.28 : 0.4);

  return (
    <AbsoluteFill style={{ background: fundo, overflow: 'hidden' }}>
      <Vazamento frames={p.frames} seed={p.seed} claro={claro} />
      <Saida fim={fimCorpo} cx={cxAlvo} cy={H * 0.45} tipo={tipoSaida}>
      <AbsoluteFill style={{ transform: `translateX(${desliza}px) scale(${zoom})`, transformOrigin: `${(cxAlvo / W) * 100}% 40%` }}>
        {fundoTexto}
        {temBeat2 && (layout === 'retrato' || (objeto && r() < 0.6)) && formaFundo !== 'solido' ? (
          // 2º tempo: forma preenchida pela textura da cena cresce atrás do sujeito, girando devagar
          <FormaTermica
            forma={formaFundo as Forma} cx={left + ((bx0 + bx1) / 2) * iw} cy={sy0 + sH * (objeto ? 0.5 : 0.32)} r={H * 0.33} k={k2}
            seed={p.seed + 21} W={W} H={H} giro={kCam * 0.8}
          />
        ) : null}
        {temBeat2 && (layout === 'retrato' || (objeto && r() < 0.6)) && formaFundo === 'solido' ? (
          // disco claro que cresce atrás do sujeito no 2º tempo
          <div
            style={{
              position: 'absolute', left: left + ((bx0 + bx1) / 2) * iw - H * 0.3, top: sy0 + sH * (objeto ? 0.5 : 0.3) - H * 0.3, width: H * 0.6, height: H * 0.6,
              borderRadius: '50%', background: claro ? alfa(C.tinta_clara, 0.9) : alfa(C.linha, 0.95), transform: `scale(${k2})`,
            }}
          />
        ) : null}
        {objeto ? (
          <div
            style={{
              position: 'absolute',
              left: sx0 + sW * 0.07 - kCam * 8 * u - k2 * sW * 0.32,
              top: sy0 - sH * 0.08 + k2 * sH * 0.3,
              width: sW * (0.98 + 0.64 * k2),
              height: sH * (0.96 - 0.5 * k2),
              border: `${Math.max(1, 1.6 * u)}px solid ${alfa(corLinha, 0.6)}`, clipPath: `inset(0 ${(1 - kRet) * 100}% ${(1 - kRet) * 100}% 0)`,
            }}
          />
        ) : null}
        {layout === 'circulo' ? (
          <>
            <div
              style={{
                position: 'absolute', inset: 0, clipPath: `circle(${R * kCirc}px at ${cxAlvo}px ${cyC}px)`,
                transform: `scale(${1.04 - 0.04 * kCirc})`, transformOrigin: `${cxAlvo}px ${cyC}px`,
              }}
            >
              <Img src={staticFile(midia)} style={{ position: 'absolute', left, top, width: iw, height: ih, filter: 'grayscale(1) brightness(0.42) contrast(1.1) blur(1px)' }} />
              {/* no 2º tempo o miolo do círculo esquenta (luz por trás da cabeça) */}
              <AbsoluteFill style={{ background: `radial-gradient(${R}px ${R}px at ${cxAlvo}px ${cyC}px, ${alfa(C.nome, 0.55 * k2)}, transparent)` }} />
            </div>
            <svg width={W} height={H} style={{ position: 'absolute', left: 0, top: 0 }}>
              {/* 2º tempo: anel que se expande a partir do círculo e some */}
              {k2 > 0 && k2 < 1 ? (
                <circle cx={cxAlvo} cy={cyC} r={R * (1 + 0.9 * k2)} fill="none" stroke={alfa(corLinha, 0.7 * (1 - k2))} strokeWidth={Math.max(1, 2 * u)} />
              ) : null}
              <circle
                cx={cxAlvo} cy={cyC} r={R} fill="none" stroke={alfa(corLinha, 0.85)} strokeWidth={Math.max(1, 2 * u)}
                strokeDasharray={`${circ * 0.94} ${circ * 0.06}`} strokeDashoffset={circ * (1 - kCirc)} transform={`rotate(${-90 + kCam * 70} ${cxAlvo} ${cyC})`}
              />
            </svg>
          </>
        ) : null}
        {layout === 'janela' ? (
          <>
            <div
              style={{
                position: 'absolute', left: jx + jw * 0.045 - kCam * 10 * u - k2 * jw * 0.12, top: jy - jh * 0.06 + k2 * jh * 0.12,
                width: jw * (1.0 + 0.2 * k2), height: jh * (1.04 - 0.1 * k2),
                border: `${Math.max(1, 1.6 * u)}px solid ${alfa(corLinha, 0.7)}`, clipPath: `inset(0 ${(1 - kMold) * 100}% ${(1 - kMold) * 100}% 0)`,
              }}
            />
            <Entrada tipo={entSuj} inicio={ini} dur={q(18, p.fps)} cx={jcx} cy={jy + jh / 2} w={jw} h={jh} W={W} H={H} de={r() < 0.5 ? 1 : -1} id={`jan-${p.cena_id}`}>
            <div
              style={{
                position: 'absolute', left: jx, top: jy, width: jw, height: jh, overflow: 'hidden',
                boxShadow: `0 ${24 * u}px ${60 * u}px rgba(0,0,0,${claro ? 0.18 : 0.5})`,
              }}
            >
              <div style={{ position: 'absolute', inset: 0, transform: `scale(${1.02 + 0.05 * kCam})` }}>{midiaJanela}</div>
              {kTerm > 0 ? (
                <div style={{ position: 'absolute', inset: 0, opacity: kTerm * 0.85, mixBlendMode: 'color' }}>
                  <svg width={jw} height={jh}>
                    <defs>
                      <FiltroTermico id="term-jan" seed={p.seed} escala={0.006 / u} progresso={(f - tTerm) / Math.max(1, p.frames)} />
                    </defs>
                    <rect width={jw} height={jh} fill="#808080" filter="url(#term-jan)" />
                  </svg>
                </div>
              ) : null}
            </div>
            </Entrada>
          </>
        ) : null}
        {layout !== 'janela' && recorte ? (
          <div style={{ position: 'absolute', inset: 0, transform: `translateX(${kCam * 40 * u * (cxAlvo > W / 2 ? -1 : 1)}px)` }}>
            <Entrada
              tipo={entSuj} inicio={tSuj} dur={q(18, p.fps)} cx={sx0 + sW / 2} cy={sy0 + sH / 2} w={sW * 1.1} h={sH * 1.1} W={W} H={H}
              de={cxAlvo > W / 2 ? 1 : -1} id={`suj-${p.cena_id}`}
            >
              {sujeito(recorte, kTerm > 0)}
            </Entrada>
          </div>
        ) : null}
        {ic?.nome ? (
          <Icone
            nome={ic.nome} x={icX} y={icY} tam={(ic.tamanho ?? 0.17) * H} inicio={tIcone} seed={p.seed + 3}
            termico={ic.termico ?? true} cor={corNome} moldura={ic.mira === false ? null : alfa(corLinha, 0.8)} u={u}
            vira={ic.vira} tVira={ic.vira ? Math.max(tIcone + q(14, p.fps), dito([ic.vira_em], corpoS * 0.75)) : undefined}
          />
        ) : null}
      </AbsoluteFill>
      {ficha?.texto ? (
        <Entrada tipo="cortina" inicio={tFicha} dur={q(14, p.fps)} cx={W * 0.6 + H * 0.17} cy={H * 0.2 + H * 0.17} w={H * 0.4} h={H * 0.4} W={W} H={H} id={`fic-${p.cena_id}`}>
        <Ficha
          x={W * 0.6} y={H * 0.2} tam={H * 0.34} inicio={tFicha} seed={p.seed + 9} texto={ficha.texto} numero={ficha.numero}
          cantos={ficha.cantos ?? []} legenda={ficha.legenda} termico={ficha.termico ?? false}
          corLinha={alfa(corLinha, 0.85)} corTexto={claro ? C.tinta_clara : cor.texto} corAcento={corNome} u={u}
          vira={ficha.vira} tVira={ficha.vira ? Math.max(tFicha + q(20, p.fps), dito([ficha.vira_em], corpoS * 0.75)) : undefined}
        />
        </Entrada>
      ) : null}
      {temNome ? (
        <FioNome
          x={nomeX} y={temFicha ? H * 0.72 : linhaY} largura={nomeL} inicio={tNome} nome={d.titulo} ano={d.ano} sub={d.subtitulo}
          u={u} corNome={corNome} corLinha={corLinha} corSub={corSub} tamNome={temFicha ? 56 : 74}
        />
      ) : null}
      {d.legenda_fundo && !txtFundo ? (
        <Surge inicio={tFundo} estilo={{ position: 'absolute', left: W * 0.06, top: H * 0.1 }}>
          <div style={{ fontFamily: fonte.rotulo, fontWeight: 800, fontSize: 30 * u, letterSpacing: '0.2em', color: corLinha }}>{d.legenda_fundo}</div>
        </Surge>
      ) : null}
      </Saida>
      <Riscos W={W} H={H} seed={p.seed} claro={claro} />
      <Textura vinheta={claro ? 0.35 : 0.8} />
    </AbsoluteFill>
  );
};
