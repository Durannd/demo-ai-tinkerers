import React from 'react';
import { Composition } from 'remotion';
import { Cena } from './Cena';
import type { PropsCena } from './tipos';

const EXEMPLO: PropsCena = {
  cena_id: 'c02',
  tipo: 'numero',
  largura: 1920,
  altura: 1080,
  fps: 30,
  frames: 150,
  alca_antes: 0,
  corpo: 150,
  seed: 7,
  narracao: 'Não era água. Eram milhões de litros de melaço.',
  palavras: [],
  dados: { valor: 8700000, unidade: 'litros de melaço', referencia: { valor: 2500000, rotulo: 'piscina olímpica' } },
};

export const Root: React.FC = () => (
  <Composition
    id="Cena"
    component={Cena as unknown as React.FC<Record<string, unknown>>}
    defaultProps={EXEMPLO as unknown as Record<string, unknown>}
    durationInFrames={150}
    fps={30}
    width={1920}
    height={1080}
    calculateMetadata={({ props }) => {
      const p = props as unknown as PropsCena;
      return { durationInFrames: p.frames, fps: p.fps, width: p.largura, height: p.altura };
    }}
  />
);
