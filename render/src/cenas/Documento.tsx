import React from 'react';
import { AbsoluteFill, Img, interpolate, staticFile, useCurrentFrame, useVideoConfig } from 'remotion';
import { Fundo, quadro, tempoDe, Textura } from '../comp/Base';
import { Coreografia } from '../comp/Movimento';
import { txt } from '../comp/i18n';
import { alfa, clamp, cor, ease, escolher, fonte, q, rng, TEMPO } from '../comp/tokens';
import type { PropsCena } from '../tipos';

/**
 * Documento com trecho destacado. Dois estilos (sem "jornal falso" — documento inventado engana):
 *  scan  → imagem REAL do documento (imagens[0]); câmera aproxima da região citada (regiao=[x,y,l,a] em 0..1)
 *          e o marca-texto varre a região; o trecho aparece num recorte de papel por cima.
 *  ficha → cartão datilografado com o trecho e a fonte ("Relatório X, 1920"), marca-texto palavra a palavra.
 * O marca-texto acompanha a narração quando o trecho é lido em voz alta.
 */
const norm = (s: string) => s.toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/[^\w]/g, '');

const temposDoTrecho = (p: PropsCena, trecho: string): number[] | null => {
  const alvo = trecho.split(/\s+/).map(norm).filter(Boolean);
  const nar = p.palavras.map((w) => norm(w.texto));
  for (let i = 0; i + 1 < nar.length; i++) {
    if (nar[i] === alvo[0] && nar[i + 1] === alvo[1]) {
      return alvo.map((_, k) => quadro(p, (p.palavras[i + k] ?? p.palavras[p.palavras.length - 1]).ini) - q(TEMPO.antecipacao, p.fps));
    }
  }
  return null;
};

const MarcaTexto: React.FC<{ palavras: string[]; tempos: number[]; tam: number; corTexto: string; corMarca: string; familia: string }> = ({
  palavras,
  tempos,
  tam,
  corTexto,
  corMarca,
  familia,
}) => {
  const { fps } = useVideoConfig();
  const f = useCurrentFrame();
  return (
    <div style={{ fontFamily: familia, fontSize: tam, lineHeight: 1.5, color: corTexto }}>
      {palavras.map((w, i) => {
        const k = interpolate(f, [tempos[i], tempos[i] + q(TEMPO.antecipacao * 2 + 1, fps)], [0, 1], { ...clamp, easing: ease.padrao });
        // marca-texto "de verdade": faixa levemente torta e irregular por palavra, pontas mais carregadas
        // (tinta acumula onde a caneta para), multiplicada sobre o papel. Determinístico pelo índice.
        const torto = Math.sin(i * 12.9898) * 0.25;
        const alt = Math.sin(i * 78.233) * 0.025;
        return (
          <span key={i} style={{ position: 'relative', display: 'inline-block', marginRight: '0.32em' }}>
            <span
              style={{
                // emenda com a próxima palavra (cobre o espaço): o traço parece contínuo, não "tijolinhos"
                position: 'absolute', left: i === 0 ? '-0.14em' : '-0.02em', right: i === palavras.length - 1 ? '-0.2em' : '-0.34em',
                top: `${0.2 + alt}em`, bottom: `${0.04 - alt}em`,
                background: corMarca,
                borderRadius: `${i === 0 ? '0.2em' : '0'} ${i === palavras.length - 1 ? '0.3em 0.24em' : '0 0'} ${i === 0 ? '0.16em' : '0'}`,
                transformOrigin: 'left', transform: `rotate(${torto}deg) scaleX(${k})`, mixBlendMode: 'multiply',
              }}
            />
            <span style={{ position: 'relative' }}>{w}</span>
          </span>
        );
      })}
    </div>
  );
};

export const Documento: React.FC<{ p: PropsCena }> = ({ p }) => {
  const f = useCurrentFrame();
  const r = rng(p.seed);
  const d = p.dados;
  const W = p.largura;
  const H = p.altura;
  const u = H / 1080;
  const trecho: string = d.trecho ?? '';
  const palavras = trecho.split(/\s+/).filter(Boolean);
  const scan = p.imagens?.[0];
  const estilo: 'scan' | 'ficha' = d.estilo ?? (scan ? 'scan' : 'ficha');
  const ini = p.alca_antes;
  // v4: sem o trecho literal na fala, o marca-texto começa quando a âncora (ou o 1º termo do trecho) é dita
  const tAncora = Math.max(ini + q(TEMPO.entradaLonga, p.fps), quadro(p, tempoDe(p.palavras, [d.ancora, palavras.slice(0, 2).join(' ')], 0.6)));
  const sinc = temposDoTrecho(p, trecho);
  const tempos = sinc ?? palavras.map((_, i) => tAncora + Math.round((i * p.fps * 1.4) / Math.max(1, palavras.length)));
  const marca = alfa(cor.secundaria, 0.62);
  const giro = (r() - 0.5) * 3;

  if (estilo === 'scan' && scan) {
    const reg: [number, number, number, number] = d.regiao ?? [0.2, 0.25, 0.6, 0.2];
    // câmera: aproxima da região e CHEGA quando o trecho começa a ser lido; depois só deriva lentíssima
    const chegada = Math.max(ini + q(TEMPO.entradaLonga, p.fps), tempos[0]);
    const kCam = interpolate(f, [ini, chegada], [0, 0.94], { ...clamp, easing: ease.padrao }) + interpolate(f, [chegada, p.frames], [0, 0.06], clamp);
    const z0 = 1.05;
    // tamanho real da página na tela (contain) → zoom que deixa a região com ~70% da largura do quadro
    const asp = p.aspectos?.[0] ?? 0.7;
    const pagW = Math.min(W, H * asp);
    const pagH = pagW / asp;
    const z1 = Math.min(4, Math.max(1.2, Math.min((W * 0.72) / (reg[2] * pagW), (H * 0.6) / (reg[3] * pagH))));
    const z = z0 + (z1 - z0) * kCam;
    const cx = 0.5 + (reg[0] + reg[2] / 2 - 0.5) * kCam;
    const cy = 0.5 + (reg[1] + reg[3] / 2 - 0.5) * kCam;
    const kMarca = interpolate(f, [tempos[0], tempos[tempos.length - 1] + q(TEMPO.atrasoInicial, p.fps)], [0, 1], { ...clamp, easing: ease.padrao });
    const sombra = interpolate(f, [tempos[0] - q(TEMPO.entrada, p.fps), tempos[0]], [0, 0.45], clamp);
    const cartao = interpolate(f, [tempos[0], tempos[0] + q(TEMPO.entradaCurta, p.fps)], [0, 1], { ...clamp, easing: ease.saida });
    return (
      <AbsoluteFill style={{ background: '#1b1a17', overflow: 'hidden' }}>
        <Coreografia p={p} cx={W * (0.5 + (reg[0] + reg[2] / 2 - 0.5) * 0.6)} cy={H * (0.5 + (reg[1] + reg[3] / 2 - 0.5) * 0.6)} intensidade={0.45} reenq="avanca">
        <AbsoluteFill style={{ transform: `scale(${z}) translate(${(0.5 - cx) * 100}%, ${(0.5 - cy) * 100}%) rotate(${giro * (1 - kCam)}deg)` }}>
          <AbsoluteFill style={{ justifyContent: 'center', alignItems: 'center' }}>
            <div style={{ position: 'relative', height: '100%' }}>
              <Img src={staticFile(scan)} style={{ height: '100%', display: 'block', filter: 'sepia(0.25) contrast(1.05)' }} />
              <div style={{ position: 'absolute', inset: 0, background: `rgba(0,0,0,${sombra})`, clipPath: `polygon(0 0,100% 0,100% 100%,0 100%,0 ${reg[1] * 100}%,${reg[0] * 100}% ${reg[1] * 100}%,${reg[0] * 100}% ${(reg[1] + reg[3]) * 100}%,${(reg[0] + reg[2]) * 100}% ${(reg[1] + reg[3]) * 100}%,${(reg[0] + reg[2]) * 100}% ${reg[1] * 100}%,0 ${reg[1] * 100}%)` }} />
              <div
                style={{
                  position: 'absolute', left: `${reg[0] * 100}%`, top: `${reg[1] * 100}%`, width: `${reg[2] * 100 * kMarca}%`,
                  height: `${reg[3] * 100}%`, background: marca, mixBlendMode: 'multiply',
                }}
              />
            </div>
          </AbsoluteFill>
        </AbsoluteFill>
        {trecho ? (
          <div
            style={{
              position: 'absolute', left: W * (r() < 0.5 ? 0.07 : 0.5), bottom: H * 0.1, width: W * 0.42, padding: `${30 * u}px ${36 * u}px ${26 * u}px`,
              background: cor.papel, opacity: Math.min(1, cartao * 1.6),
              boxShadow: `0 ${2 * u}px ${3 * u}px rgba(0,0,0,0.25), 0 ${24 * u}px ${50 * u}px rgba(0,0,0,0.55)`,
              transform: `translateY(${(1 - cartao) * 40 * u}px) rotate(${-giro * 0.6 + (1 - cartao) * 2}deg)`,
            }}
          >
            <Fita u={u} lado="esq" giro={-giro * 4} />
            <Fita u={u} lado="dir" giro={giro * 3} />
            {d.traducao ? (
              <div style={{ display: 'inline-block', marginBottom: 14 * u, padding: `${3 * u}px ${10 * u}px`, border: `${1.5 * u}px solid ${cor.destaque}`, fontFamily: fonte.rotulo, fontWeight: 600, fontSize: 16 * u, letterSpacing: '0.24em', color: cor.destaque }}>
                {txt().traducao}
              </div>
            ) : null}
            <MarcaTexto palavras={palavras} tempos={tempos} tam={42 * u} corTexto="#211b13" corMarca={marca} familia={fonte.titulo} />
            {d.fonte_doc ? (
              <div style={{ marginTop: 16 * u, paddingTop: 12 * u, borderTop: `1px solid rgba(75,63,48,0.35)`, fontFamily: fonte.rotulo, fontWeight: 600, fontSize: 18 * u, letterSpacing: '0.2em', textTransform: 'uppercase', color: '#6b5d48' }}>
                {d.fonte_doc}
              </div>
            ) : null}
            <Textura papel vinheta={0.4} />
          </div>
        ) : null}
        </Coreografia>
        <Textura vinheta={0.9} />
      </AbsoluteFill>
    );
  }

  // ficha datilografada: o cartão "cai" na mesa (mola amortecida, sem quicar), o texto é datilografado
  // em ritmo rápido com cursor, depois o marca-texto acompanha a narração.
  const entra = interpolate(f, [ini, ini + q(TEMPO.entradaLonga, p.fps)], [0, 1], { ...clamp, easing: ease.saida });
  const lado = escolher(r, [-1, 1]);
  const total = trecho.length;
  const tDat = ini + q(TEMPO.entradaCurta, p.fps);
  const cps = Math.max(1.5, total / Math.max(12, Math.min(40, (tempos[0] ?? tDat + 30) - tDat - 4)));
  const nChars = Math.max(0, Math.floor((f - tDat) * cps));
  const datilografando = nChars < total;
  let resta = nChars;
  const visiveis = palavras.map((w) => {
    const v = w.slice(0, Math.max(0, resta));
    resta -= w.length + 1;
    return v;
  });
  const cursor = datilografando && f >= tDat && Math.floor(f / 8) % 2 === 0;
  return (
    <AbsoluteFill>
      <Fundo imagem={p.fundo} escurecer={0.82} />
      <Coreografia p={p} cx={W / 2} cy={H / 2}>
      <AbsoluteFill style={{ justifyContent: 'center', alignItems: 'center' }}>
        <div
          style={{
            position: 'relative', width: W * 0.66, padding: `${70 * u}px ${80 * u}px ${60 * u}px`, background: cor.papel,
            backgroundImage: 'linear-gradient(170deg, rgba(255,255,255,0.35) 0%, rgba(255,255,255,0) 40%, rgba(120,90,50,0.10) 100%)',
            boxShadow: `0 ${2 * u}px ${4 * u}px rgba(0,0,0,0.3), 0 ${40 * u}px ${90 * u}px rgba(0,0,0,0.6)`,
            opacity: Math.min(1, entra * 2),
            transform: `translateY(${(1 - entra) * 90 * u}px) rotate(${giro * 0.5 + lado * (1 - entra) * 4}deg) scale(${(1.04 - 0.04 * entra) * (1 + f * 0.0002)})`,
          }}
        >
          {/* margem vermelha de ficha de arquivo + furos */}
          <div style={{ position: 'absolute', left: 46 * u, top: 0, bottom: 0, width: 1.5 * u, background: alfa(cor.destaque, 0.35) }} />
          {[0.25, 0.75].map((y) => (
            <div key={y} style={{ position: 'absolute', left: 16 * u, top: `${y * 100}%`, width: 14 * u, height: 14 * u, borderRadius: 99, background: alfa(cor.tinta, 0.75), boxShadow: 'inset 0 2px 3px rgba(0,0,0,0.6)' }} />
          ))}
          {d.cabecalho ? (
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', fontFamily: fonte.documento, fontWeight: 700, fontSize: 26 * u, letterSpacing: '0.2em', color: '#4b3f30', marginBottom: 30 * u, borderBottom: `${2 * u}px solid #4b3f30`, paddingBottom: 12 * u }}>
              <span>{d.cabecalho}</span>
            </div>
          ) : null}
          <div style={{ position: 'relative' }}>
            {/* camada invisível reserva o espaço do texto final: o cartão não muda de tamanho enquanto datilografa */}
            <div style={{ visibility: 'hidden' }}>
              <MarcaTexto palavras={palavras} tempos={tempos} tam={(trecho.length > 120 ? 44 : 52) * u} corTexto="#211b13" corMarca={marca} familia={fonte.documento} />
            </div>
            <div style={{ position: 'absolute', inset: 0 }}>
              {datilografando ? (
                <div style={{ fontFamily: fonte.documento, fontSize: (trecho.length > 120 ? 44 : 52) * u, lineHeight: 1.5, color: '#211b13' }}>
                  {visiveis.map((v, i) => (v ? <span key={i} style={{ display: 'inline-block', marginRight: '0.32em' }}>{v}</span> : null))}
                  {cursor ? <span style={{ display: 'inline-block', width: '0.55em', height: '1em', verticalAlign: '-0.15em', background: 'rgba(33,27,19,0.75)' }} /> : null}
                </div>
              ) : (
                <MarcaTexto palavras={palavras} tempos={tempos} tam={(trecho.length > 120 ? 44 : 52) * u} corTexto="#211b13" corMarca={marca} familia={fonte.documento} />
              )}
            </div>
          </div>
          {d.fonte_doc ? (
            <div style={{ marginTop: 36 * u, fontFamily: fonte.documento, fontSize: 26 * u, color: '#6b5d48', opacity: interpolate(f, [tDat + total / cps, tDat + total / cps + 10], [0, 1], clamp) }}>
              — {d.fonte_doc}
            </div>
          ) : null}
          <Textura papel vinheta={0.5} />
        </div>
      </AbsoluteFill>
      </Coreografia>
      <Textura />
    </AbsoluteFill>
  );
};

/** Pedaço de fita adesiva translúcida segurando o recorte. */
const Fita: React.FC<{ u: number; lado: 'esq' | 'dir'; giro: number }> = ({ u, lado, giro }) => (
  <div
    style={{
      position: 'absolute', top: -16 * u, [lado === 'esq' ? 'left' : 'right']: -22 * u, width: 110 * u, height: 32 * u,
      background: 'linear-gradient(180deg, rgba(240,232,210,0.55), rgba(220,210,185,0.45))',
      boxShadow: '0 1px 2px rgba(0,0,0,0.15)', transform: `rotate(${(lado === 'esq' ? -32 : 30) + giro}deg)`,
      clipPath: 'polygon(3% 0, 97% 4%, 100% 50%, 96% 100%, 2% 96%, 0 50%)',
    }}
  />
);
