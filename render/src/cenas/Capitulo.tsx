import React from 'react';
import { AbsoluteFill, interpolate, useCurrentFrame } from 'remotion';
import { Chapeu, Deriva, Fio, Fundo, FundoTipo, Textura } from '../comp/Base';
import { Revela } from '../comp/Revela';
import { Coreografia } from '../comp/Movimento';
import { txt } from '../comp/i18n';
import { cor, escolher, fonte, q, rng, TEMPO } from '../comp/tokens';
import type { PropsCena } from '../tipos';

const ROMANOS = ['', 'I', 'II', 'III', 'IV', 'V', 'VI', 'VII', 'VIII', 'IX', 'X', 'XI', 'XII'];

/**
 * Cartela de capítulo. Layout decidido pelo comprimento do título (curto → enorme e centrado; longo →
 * editorial alinhado à esquerda) e a seed só desempata. O fundo é o quadro da cena seguinte desfocado.
 * v3: numeral gigante "fantasma" (só contorno) atravessando o quadro em paralaxe lenta, chapéu com fios,
 * título que sobe de trás de uma máscara palavra a palavra, fio que desenha, grão + vinheta.
 */
export const Capitulo: React.FC<{ p: PropsCena }> = ({ p }) => {
  const f = useCurrentFrame();
  const r = rng(p.seed);
  const d = p.dados;
  const W = p.largura;
  const H = p.altura;
  const u = H / 1080;
  const titulo: string = d.titulo ?? '';
  const n: number | undefined = d.numero;
  const numTxt = n ? (d.estilo_numero === 'arabico' ? String(n).padStart(2, '0') : ROMANOS[n] ?? String(n)) : '';
  const curto = titulo.length <= 18;
  const layout = curto ? escolher(r, ['gigante', 'centro']) : escolher(r, ['editorial', 'lateral']);
  const t0 = p.alca_antes + q(TEMPO.atrasoInicial, p.fps);
  const centrado = layout === 'gigante' || layout === 'centro';

  // v4: fundo "nunca vazio" — palavra gigante (o numeral, ou a palavra mais longa do título) sangrando do quadro
  const palavraFundo: string = d.palavra_fundo ?? (numTxt || titulo.split(/\s+/).reduce((a, b) => (b.length > a.length ? b : a), ''));
  const fundoTipo = (
    <FundoTipo
      palavra={palavraFundo}
      W={W}
      H={H}
      glowX={centrado ? W / 2 : W * 0.4}
      glowY={H * 0.48}
      lado={centrado || layout === 'editorial' ? 'dir' : 'esq'}
      inicio={t0}
      frames={p.frames}
      italico={!numTxt}
    />
  );
  const chapeu = numTxt ? (
    <div style={{ marginBottom: 34 * u }}>
      <Chapeu texto={`${d.rotulo_numero ?? txt().capitulo} ${numTxt}`} inicio={t0} u={u} alinhar={centrado ? 'center' : 'left'} tamanho={26} />
    </div>
  ) : null;

  const estiloTitulo: React.CSSProperties = {
    fontFamily: fonte.titulo,
    fontWeight: layout === 'gigante' ? 700 : 600,
    color: cor.texto,
    lineHeight: 1.02,
    letterSpacing: layout === 'gigante' ? '-0.03em' : '-0.02em',
    fontSize: (layout === 'gigante' ? 190 : layout === 'centro' ? 148 : 120) * u,
  };

  const subtitulo = d.subtitulo ? (
    <div style={{ marginTop: 30 * u }}>
      <Revela
        texto={d.subtitulo}
        inicio={t0 + q(TEMPO.entradaLonga, p.fps)}
        escalonar={2}
        mascara
        alinhar={centrado ? 'center' : 'left'}
        estilo={{ fontFamily: fonte.titulo, fontStyle: 'italic', fontWeight: 400, fontSize: 44 * u, color: cor.texto_suave, letterSpacing: '0.005em' }}
      />
    </div>
  ) : null;

  let corpo: React.ReactNode;
  if (centrado) {
    corpo = (
      <AbsoluteFill style={{ justifyContent: 'center', alignItems: 'center', textAlign: 'center' }}>
        <div style={{ width: W * 0.84 }}>
          {chapeu}
          <Revela texto={titulo} inicio={t0 + q(TEMPO.antecipacao * 2, p.fps)} escalonar={4} alinhar="center" mascara estilo={estiloTitulo} />
          <div style={{ display: 'flex', justifyContent: 'center', marginTop: 36 * u, height: Math.max(2, 3 * u) }}>
            <div style={{ position: 'relative', width: W * 0.12 }}>
              <Fio x={0} y={0} largura={W * 0.12} inicio={t0 + q(TEMPO.entradaCurta, p.fps)} espessura={Math.max(2, 3 * u)} />
            </div>
          </div>
          {subtitulo}
        </div>
      </AbsoluteFill>
    );
  } else {
    const xEsq = layout === 'editorial' ? W * 0.1 : W * 0.36;
    corpo = (
      <>
        <Fio x={xEsq - 40 * u} y={H * 0.34} largura={H * 0.34} inicio={t0} vertical espessura={Math.max(3, 4 * u)} />
        <div style={{ position: 'absolute', left: xEsq, top: H * 0.33, width: W * (layout === 'editorial' ? 0.74 : 0.56) }}>
          {chapeu}
          <Revela texto={titulo} inicio={t0 + q(TEMPO.antecipacao * 2, p.fps)} escalonar={3} mascara estilo={estiloTitulo} />
          {subtitulo}
        </div>
      </>
    );
  }
  return (
    <AbsoluteFill>
      <Deriva intensidade={0.6} direcao={r() < 0.5 ? -1 : 1}>
        <Fundo imagem={p.fundo} escurecer={0.84} luzX={layout === 'lateral' ? 0.65 : 0.4} />
      </Deriva>
      <Coreografia p={p} cx={centrado ? W / 2 : W * 0.4} cy={H * 0.48} intensidade={0.85}>
        {fundoTipo}
        {corpo}
      </Coreografia>
      <Textura />
    </AbsoluteFill>
  );
};
