import React from 'react';
import { Composition } from 'remotion';
import { Cta, type PropsCta } from './Cta';
import { ShortFx, type PropsShortFx } from './ShortFx';
import { Objeto, type PropsObjeto } from './Objeto';

const EXEMPLO: PropsCta = {
  id: 'cta_combo',
  tipo: 'combo',
  largura: 580,
  altura: 196,
  fps: 30,
  frames: 132,
  escala: 1,
  lado: 'dir',
  ancora: 'baixo',
  tempos: { cursor: 0.25, like: 0.8, clique: 1.55, clique_sino: 2.3, sino: 2.33, sai: 3.9, fim: 4.4 },
  texto: '',
  textos: { inscrever: 'INSCREVA-SE', inscrito: 'INSCRITO', like: 'Deixe seu like', comentar: 'Comenta aí' },
  seed: 7,
  contador: 1248,
};

const EXEMPLO_FX: PropsShortFx = {
  id: 'fx_gancho',
  tipo: 'gancho',
  largura: 1080,
  altura: 1920,
  fps: 30,
  frames: 90,
  escala: 1,
  seed: 7,
  dir: 1,
  texto: 'Favela já foi o nome de 1 único morro',
};

const EXEMPLO_OBJ: PropsObjeto = {
  id: 'obj',
  largura: 720,
  altura: 720,
  fps: 30,
  frames: 120,
  lado: 450,
  escala: 1,
  seed: 3,
  icone: 'gota',
  entrada: 'cai',
  acoes: [{ tipo: 'cor', t: 1.2, cor: '#3FA34D' }],
  sai: 3.7,
};

export const RootCta: React.FC = () => (
  <>
    <Composition
      id="Objeto"
      component={Objeto as unknown as React.FC<Record<string, unknown>>}
      defaultProps={EXEMPLO_OBJ as unknown as Record<string, unknown>}
      durationInFrames={EXEMPLO_OBJ.frames}
      fps={30}
      width={EXEMPLO_OBJ.largura}
      height={EXEMPLO_OBJ.altura}
      calculateMetadata={({ props }) => {
        const p = props as unknown as PropsObjeto;
        return { durationInFrames: p.frames, fps: p.fps, width: p.largura, height: p.altura };
      }}
    />
    <Composition
      id="Cta"
      component={Cta as unknown as React.FC<Record<string, unknown>>}
      defaultProps={EXEMPLO as unknown as Record<string, unknown>}
      durationInFrames={EXEMPLO.frames}
      fps={30}
      width={EXEMPLO.largura}
      height={EXEMPLO.altura}
      calculateMetadata={({ props }) => {
        const p = props as unknown as PropsCta;
        return { durationInFrames: p.frames, fps: p.fps, width: p.largura, height: p.altura };
      }}
    />
    <Composition
      id="ShortFx"
      component={ShortFx as unknown as React.FC<Record<string, unknown>>}
      defaultProps={EXEMPLO_FX as unknown as Record<string, unknown>}
      durationInFrames={EXEMPLO_FX.frames}
      fps={30}
      width={EXEMPLO_FX.largura}
      height={EXEMPLO_FX.altura}
      calculateMetadata={({ props }) => {
        const p = props as unknown as PropsShortFx;
        return { durationInFrames: p.frames, fps: p.fps, width: p.largura, height: p.altura };
      }}
    />
  </>
);
