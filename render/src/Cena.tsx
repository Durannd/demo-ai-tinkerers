import React from 'react';
import { AbsoluteFill } from 'remotion';
import { Fontes } from './comp/Base';
import { aplicarCanal, cor } from './comp/tokens';
import { Capitulo } from './cenas/Capitulo';
import { Citacao } from './cenas/Citacao';
import { Colagem } from './cenas/Colagem';
import { Comparacao } from './cenas/Comparacao';
import { Documento } from './cenas/Documento';
import { Domino } from './cenas/Domino';
import { Icones } from './cenas/Icones';
import { LinhaDoTempo } from './cenas/LinhaDoTempo';
import { Mapa } from './cenas/Mapa';
import { Numero } from './cenas/Numero';
import { Parallax } from './cenas/Parallax';
import type { PropsCena } from './tipos';

const CENAS: Record<string, React.FC<{ p: PropsCena }>> = {
  numero: Numero,
  capitulo: Capitulo,
  citacao: Citacao,
  mapa: Mapa,
  documento: Documento,
  linha_do_tempo: LinhaDoTempo,
  parallax: Parallax,
  comparacao: Comparacao,
  domino: Domino,
  colagem: Colagem,
  icones: Icones,
};

export const Cena: React.FC<PropsCena> = (p) => {
  // tokens/idioma do canal do episódio: aplicados antes de qualquer componente ler cor/fonte/textos
  aplicarCanal(p.tokens, p.idioma);
  const C = CENAS[p.tipo];
  return (
    <AbsoluteFill style={{ background: cor.tinta }}>
      <Fontes />
      {C ? <C p={p} /> : <div style={{ color: 'red', fontSize: 60 }}>tipo desconhecido: {p.tipo}</div>}
    </AbsoluteFill>
  );
};

export const TIPOS = Object.keys(CENAS);
