import React from 'react';
import { AbsoluteFill, Img, interpolate, staticFile, useCurrentFrame } from 'remotion';
import { Deriva, Fundo, FundoTipo, quadro, tempoDe, Textura } from '../comp/Base';
import { contarPalavras, Revela } from '../comp/Revela';
import { Coreografia } from '../comp/Movimento';
import { alfa, clamp, cor, ease, escolher, fonte, q, rng, TEMPO } from '../comp/tokens';
import type { PropsCena } from '../tipos';

/**
 * Citação: a frase aparece palavra a palavra NO TEMPO EM QUE O NARRADOR A LÊ (se a citação estiver
 * na narração), com **destaque** opcional. Com retrato (imagens[0]), a foto ocupa um lado em P&B.
 * v3: quando há sincronia com a voz, a frase inteira já está na tela "apagada" e cada palavra acende
 * ao ser dita (leitura guiada, como nos explicativos da Vox); aspa tipográfica gigante como ornamento,
 * fio vertical que desenha, atribuição com travessão longo; retrato com halftone sutil e moldura de luz.
 */
export const Citacao: React.FC<{ p: PropsCena }> = ({ p }) => {
  const f = useCurrentFrame();
  const r = rng(p.seed);
  const d = p.dados;
  const W = p.largura;
  const H = p.altura;
  const u = H / 1080;
  const texto: string = d.texto ?? p.narracao;
  const n = contarPalavras(texto);
  const limpo = (s: string) =>
    s.toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/[^\w]/g, '');

  // casa a citação com a narração para pegar o tempo de cada palavra
  const alvo = texto.replace(/\*\*|\|/g, ' ').split(/\s+/).filter(Boolean).map(limpo);
  const narr = p.palavras.map((w) => limpo(w.texto));
  let inicioIdx = -1;
  for (let i = 0; i + 1 < narr.length && inicioIdx < 0; i++) if (narr[i] === alvo[0] && narr[i + 1] === alvo[1]) inicioIdx = i;
  const inicios =
    inicioIdx >= 0 && alvo.length === n
      ? alvo.map((_, k) => quadro(p, p.palavras[Math.min(p.palavras.length - 1, inicioIdx + k)].ini) - q(TEMPO.antecipacao, p.fps))
      : undefined;

  const retrato = p.imagens?.[0];
  const lado = retrato ? (escolher(r, ['dir', 'esq']) as 'dir' | 'esq') : 'nenhum';
  const xTexto = lado === 'esq' ? W * 0.47 : W * 0.12;
  const largura = retrato ? W * 0.43 : W * 0.7;
  const tam = (texto.length > 140 ? 58 : texto.length > 80 ? 70 : 84) * u;
  // v4: sem sincronia exata, a frase começa quando a narração diz sua primeira palavra (ou o autor)
  const ini = p.alca_antes + q(TEMPO.atrasoInicial, p.fps);
  const tTexto = inicios ? inicios[0] : Math.max(ini + q(TEMPO.entradaCurta, p.fps), quadro(p, tempoDe(p.palavras, [alvo[0], d.autor], 0.4)));
  const aspas = interpolate(f, [ini, ini + q(TEMPO.entradaLonga, p.fps)], [0, 1], { ...clamp, easing: ease.saida });
  const fotoK = interpolate(f, [ini, ini + q(TEMPO.entradaLonga, p.fps)], [0, 1], { ...clamp, easing: ease.saida });
  const fio = interpolate(f, [ini + q(TEMPO.antecipacao, p.fps), ini + q(TEMPO.entradaLonga, p.fps)], [0, 1], { ...clamp, easing: ease.padrao });
  // atribuição: quando o autor é DITO (depois do início da frase); senão, logo após a última palavra
  const ultimoPadrao = (inicios?.[inicios.length - 1] ?? tTexto + n * 3) + q(TEMPO.atrasoInicial, p.fps);
  const tAutorDito = d.autor ? tempoDe(p.palavras, [String(d.autor).split(/\s+/).pop()], -1, (tTexto - p.alca_antes) / p.fps) : -1;
  const ultimo = tAutorDito >= 0 ? quadro(p, tAutorDito) : ultimoPadrao;
  const atrib = interpolate(f, [ultimo, ultimo + q(TEMPO.entradaCurta, p.fps)], [0, 1], { ...clamp, easing: ease.saida });
  const topo = H * 0.3;

  return (
    <AbsoluteFill>
      <Fundo imagem={retrato ? null : p.fundo} escurecer={0.86} luzX={lado === 'esq' ? 0.7 : 0.3} />
      <Coreografia p={p} cx={xTexto + largura * 0.35} cy={topo + H * 0.15} intensidade={0.8}>
      {retrato ? null : (
        <FundoTipo palavra={d.palavra_fundo ?? texto.replace(/\*\*|\|/g, ' ').split(/\s+/).map((w) => w.replace(/[^\p{L}]/gu, '')).reduce((a, b) => (b.length > a.length ? b : a), '')} W={W} H={H} glowX={xTexto + largura * 0.4} glowY={topo + H * 0.15} lado="esq" y={0.92} inicio={ini} frames={p.frames} italico />
      )}
      {retrato ? (
        <div
          style={{
            position: 'absolute', top: 0, bottom: 0, [lado === 'dir' ? 'right' : 'left']: 0, width: W * 0.42, overflow: 'hidden',
            opacity: fotoK,
            WebkitMaskImage: `linear-gradient(${lado === 'dir' ? 'to left' : 'to right'}, black 50%, transparent 100%)`,
          }}
        >
          <Deriva intensidade={0.8}>
            <Img src={staticFile(retrato)} style={{ width: '100%', height: '100%', objectFit: 'cover', filter: 'grayscale(1) contrast(1.12) brightness(0.92)' }} />
            {/* trama de meio-tom bem fina: lembra impressão de jornal sem virar efeito */}
            <AbsoluteFill
              style={{
                backgroundImage: `radial-gradient(${alfa(cor.tinta, 0.55)} 32%, transparent 36%)`,
                backgroundSize: `${5 * u}px ${5 * u}px`,
                mixBlendMode: 'multiply',
                opacity: 0.5,
              }}
            />
          </Deriva>
        </div>
      ) : null}
      {/* aspa ornamental gigante, quase transparente, atrás do texto */}
      <div
        style={{
          position: 'absolute', left: xTexto - 70 * u, top: topo - 250 * u, fontFamily: fonte.titulo, fontWeight: 700,
          fontSize: 520 * u, lineHeight: 1, color: cor.destaque, opacity: aspas * 0.55,
          transform: `translateY(${(1 - aspas) * 40 * u}px)`,
          WebkitMaskImage: 'linear-gradient(to bottom, black 30%, transparent 75%)',
        }}
      >
        “
      </div>
      <div style={{ position: 'absolute', left: xTexto - 44 * u, top: topo + 8 * u, width: Math.max(2, 3 * u), height: H * 0.42 * fio, background: `linear-gradient(${cor.destaque}, ${alfa(cor.destaque, 0)})` }} />
      <div style={{ position: 'absolute', left: xTexto, top: topo, width: largura }}>
        <Revela
          texto={texto}
          inicios={inicios}
          inicio={tTexto}
          escalonar={3}
          fantasma={inicios ? 0.16 : 0}
          mascara={!inicios}
          estilo={{ fontFamily: fonte.titulo, fontStyle: 'italic', fontWeight: 400, fontSize: tam, lineHeight: 1.22, letterSpacing: '-0.01em', color: cor.texto }}
        />
        {d.autor ? (
          <div style={{ marginTop: 40 * u, display: 'flex', alignItems: 'center', gap: 18 * u, opacity: atrib, transform: `translateY(${(1 - atrib) * 12 * u}px)` }}>
            <div style={{ width: 56 * u * atrib, height: Math.max(2, 2 * u), background: cor.secundaria }} />
            <div style={{ fontFamily: fonte.rotulo, fontWeight: 600, fontSize: 26 * u, letterSpacing: '0.24em', textTransform: 'uppercase', color: cor.texto }}>
              {d.autor}
              {d.contexto ? (
                <span style={{ fontFamily: fonte.titulo, fontStyle: 'italic', fontWeight: 400, fontSize: 30 * u, letterSpacing: 0, textTransform: 'none', color: cor.texto_suave, marginLeft: 14 * u }}>
                  {d.contexto}
                </span>
              ) : null}
            </div>
          </div>
        ) : null}
      </div>
      </Coreografia>
      <Textura />
    </AbsoluteFill>
  );
};
