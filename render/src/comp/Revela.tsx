import React from 'react';
import { interpolate, spring, useCurrentFrame, useVideoConfig } from 'remotion';
import { cor } from './tokens';

// Adaptado do Caption do harness grio-motion: entrada palavra a palavra com mola + blur.
// Diferença: cada palavra pode entrar no TEMPO EM QUE É NARRADA (inicios[i]), não só em stagger fixo.

type Parte = { texto: string; destaque: boolean };

/** "texto com **destaque**|nova linha" → linhas de palavras. */
export const separar = (s: string): Parte[][][] =>
  s.split('|').map((linha) => {
    const out: Parte[][] = [];
    let dest = false;
    let colado = false;
    for (const pedaco of linha.split(/(\*\*)/)) {
      if (pedaco === '**') {
        dest = !dest;
        continue;
      }
      pedaco.split(' ').forEach((t, i) => {
        if (!t) {
          colado = false;
          return;
        }
        if (i === 0 && colado && out.length) out[out.length - 1].push({ texto: t, destaque: dest });
        else out.push([{ texto: t, destaque: dest }]);
        colado = true;
      });
      colado = !pedaco.endsWith(' ');
    }
    return out;
  });

export const Revela: React.FC<{
  texto: string;
  /** quadro de entrada de cada palavra (na ordem); se faltar, usa inicio + i*escalonar */
  inicios?: number[];
  inicio?: number;
  escalonar?: number;
  estilo?: React.CSSProperties;
  corDestaque?: string;
  alinhar?: 'left' | 'center';
  borrar?: boolean;
  /** entrada "editorial": cada palavra sobe de trás de uma máscara (sem blur — mais nítido e mais barato) */
  mascara?: boolean;
  /** palavras ainda não ditas aparecem "fantasma" com esta opacidade (0 = escondidas) */
  fantasma?: number;
}> = ({ texto, inicios, inicio = 0, escalonar = 2, estilo, corDestaque = cor.secundaria, alinhar = 'left', borrar = true, mascara = false, fantasma = 0 }) => {
  const f = useCurrentFrame();
  const { fps } = useVideoConfig();
  const linhas = separar(texto);
  let k = 0;
  return (
    <div style={{ textAlign: alinhar, ...estilo }}>
      {linhas.map((ws, li) => (
        <div key={li}>
          {ws.map((w, wi) => {
            const i = k++;
            const t0 = inicios?.[i] ?? inicio + i * escalonar;
            if (mascara) {
              const m = spring({ frame: f - t0, fps, config: { damping: 26, stiffness: 120, mass: 0.9 } });
              return (
                <span key={wi} style={{ display: 'inline-block', overflow: 'hidden', verticalAlign: 'top', marginRight: '0.26em', paddingBottom: '0.12em', marginBottom: '-0.12em' }}>
                  <span style={{ display: 'inline-block', transform: `translateY(${(1 - m) * 108}%)` }}>
                    {w.map((p, pi) => (
                      <span key={pi} style={{ color: p.destaque ? corDestaque : undefined }}>
                        {p.texto}
                      </span>
                    ))}
                  </span>
                </span>
              );
            }
            const s = spring({ frame: f - t0, fps, config: { damping: 20, stiffness: 170, mass: 0.7 } });
            if (fantasma > 0) {
              // "karaoke" editorial: a frase inteira já está lá, apagada; cada palavra acende quando é dita
              const k = interpolate(s, [0, 0.6], [0, 1], { extrapolateRight: 'clamp' });
              return (
                <span key={wi} style={{ display: 'inline-block', marginRight: '0.26em', opacity: fantasma + (1 - fantasma) * k }}>
                  {w.map((p, pi) => (
                    <span key={pi} style={{ color: p.destaque && k > 0.5 ? corDestaque : undefined }}>
                      {p.texto}
                    </span>
                  ))}
                </span>
              );
            }
            return (
              <span
                key={wi}
                style={{
                  display: 'inline-block',
                  marginRight: '0.26em',
                  opacity: interpolate(s, [0, 0.45], [0, 1], { extrapolateRight: 'clamp' }),
                  transform: `translateY(${(1 - s) * 0.4}em)`,
                  filter: borrar && s < 0.98 ? `blur(${(1 - s) * 8}px)` : undefined,
                }}
              >
                {w.map((p, pi) => (
                  <span key={pi} style={{ color: p.destaque ? corDestaque : undefined }}>
                    {p.texto}
                  </span>
                ))}
              </span>
            );
          })}
        </div>
      ))}
    </div>
  );
};

/** Quantas palavras um texto com markup tem (para mapear tempos). */
export const contarPalavras = (texto: string) => separar(texto).reduce((n, l) => n + l.length, 0);
