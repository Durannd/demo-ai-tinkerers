import React from 'react';
import { AbsoluteFill, interpolate, useCurrentFrame } from 'remotion';
import { Fio, Fundo, quadro, tempoDaAncora, tempoDe, Textura } from '../comp/Base';
import { num, sepDecimal, txt } from '../comp/i18n';
import { Coreografia } from '../comp/Movimento';
import { alfa, clamp, cor, ease, escolher, fonte, q, rng, TEMPO } from '../comp/tokens';
import type { PropsCena } from '../tipos';

// Adaptado da ideia do Counter (grio-motion): o número sobe até o valor real com easing de saída.
// Tudo deriva do conteúdo: duração da contagem cresce com log(valor); abreviação pt-BR para
// milhões/bilhões; barras de escala se houver "referencia".
// v3: dígitos tabulares com vírgula em cor de destaque, sufixo em itálico, luz atrás da cifra,
// régua de base que desenha, barras com régua de quartos, valor que acompanha a ponta e a razão (≈ N×).

const fmt = (v: number, casas: number) => num(v, { minimumFractionDigits: casas, maximumFractionDigits: casas });

const escala = (valor: number): { div: number; sufixo: string } => {
  const a = Math.abs(valor);
  if (a >= 1e9) return { div: 1e9, sufixo: txt().bilhao[a >= 2e9 ? 1 : 0] };
  if (a >= 1e6) return { div: 1e6, sufixo: txt().milhao[a >= 2e6 ? 1 : 0] };
  return { div: 1, sufixo: '' };
};

/** Pinta a vírgula decimal com a cor de destaque (detalhe tipográfico dos gráficos de documentário). */
const Cifra: React.FC<{ texto: string }> = ({ texto }) => {
  const sep = sepDecimal();
  const i = texto.lastIndexOf(sep);
  if (i < 0) return <>{texto}</>;
  return (
    <>
      {texto.slice(0, i)}
      <span style={{ color: cor.destaque }}>{sep}</span>
      {texto.slice(i + 1)}
    </>
  );
};

export const Numero: React.FC<{ p: PropsCena }> = ({ p }) => {
  const f = useCurrentFrame();
  const d = p.dados;
  const r = rng(p.seed);
  const valor: number = Number(d.valor);
  const { div, sufixo } = escala(valor);
  const alvo = valor / div;
  const casas = d.casas ?? (Number.isInteger(alvo) ? 0 : 1);
  const de: number = (d.de ?? 0) / div;
  // v4: a cifra entra quando o valor é DITO; conta até ~96%, PAUSA (antecipação do clímax) e só então
  // trava no valor exato com um micro-overshoot. Sem "assentamento" senoidal nem pulsos ociosos.
  const t0 = Math.max(p.alca_antes + q(TEMPO.atrasoInicial, p.fps), quadro(p, tempoDaAncora(p.palavras, d.ancora, 0.2)));
  const durConta = Math.round(p.fps * Math.min(1.8, Math.max(0.7, 0.5 + 0.2 * Math.log10(Math.max(10, Math.abs(valor))))));
  const QUASE = 0.965;
  // inteiro pequeno (3 cabos, 5 dias): contar 0→1→2 com pausa no "2" parece erro — entra já no valor e só trava
  const pequeno = casas === 0 && Math.abs(alvo - de) <= 10;
  const pausa = q(TEMPO.pausaClimax, p.fps);
  const trava = pequeno ? t0 + 1 : t0 + durConta + pausa;
  const kConta = interpolate(f, [t0, t0 + durConta], [0, QUASE], { ...clamp, easing: ease.padrao });
  const travado = f >= trava;
  // decimal (8,7): parar em 96% mostraria "8,4" com cara de definitivo — continua contando devagar até travar
  const kDecimal = interpolate(f, [t0, trava], [0, 1], { ...clamp, easing: ease.padrao });
  const k = travado ? 1 : casas > 0 ? kDecimal : kConta;
  // valor exibido durante a contagem/pausa: arredondado no nível certo, para a pausa não mostrar
  // um número "falso" com cara de definitivo (ex.: 68.515 vira 68.500 enquanto espera)
  const passoPausa = Math.pow(10, Math.max(0, Math.floor(Math.log10(Math.max(1, Math.abs(alvo)))) - 2));
  const atual = travado ? alvo : casas === 0 ? Math.floor((de + (alvo - de) * k) / passoPausa) * passoPausa : de + (alvo - de) * k;
  const kTrava = interpolate(f, [trava, trava + q(TEMPO.entradaCurta, p.fps)], [0, 1], { ...clamp, easing: ease.trava });
  const W = p.largura;
  const H = p.altura;
  const u = H / 1080;
  const ref = d.referencia as { valor: number; rotulo: string } | undefined;
  const layout: 'centro' | 'esquerda' = ref ? 'esquerda' : escolher(r, ['centro', 'esquerda', 'centro']);
  const esq = layout === 'esquerda';
  const x0 = esq ? W * 0.1 : 0;
  const larguraBloco = esq ? W * 0.8 : W;
  // entrada: começa uma antecipação antes da palavra (o olho chega junto com o som)
  const tEntra = t0 - q(TEMPO.antecipacao, p.fps);
  const entra = interpolate(f, [tEntra, tEntra + q(TEMPO.entrada, p.fps)], [0, 1], { ...clamp, easing: ease.saida });
  const prefixo = d.prefixo ?? '';
  // largura do bloco calculada com o valor FINAL: a cifra não "respira" durante a contagem
  const textoFinal = `${prefixo}${fmt(alvo, casas)}`;
  const texto = `${prefixo}${fmt(atual, casas)}`;
  const tamanho = Math.min((ref ? 270 : 320) * u, (W * 0.66) / Math.max(2.5, textoFinal.length * 0.6 + (sufixo ? sufixo.length * 0.27 : 0)));
  const topo = H * (ref ? 0.17 : 0.3);

  // unidade: quando é dita (ex.: "mortos"), senão logo depois da trava
  const legendaIni = Math.max(t0 + q(TEMPO.entradaCurta, p.fps), quadro(p, tempoDe(p.palavras, [d.ancora_unidade, d.unidade], (trava - p.alca_antes) / p.fps + 0.1, (t0 - p.alca_antes) / p.fps)));
  const legenda = interpolate(f, [legendaIni, legendaIni + q(TEMPO.entradaCurta, p.fps)], [0, 1], { ...clamp, easing: ease.suave });
  // trava: escala 0,975 → 1 com overshoot leve (~2%), só uma vez
  const assenta = travado ? 0.975 + 0.025 * kTrava : 0.975 + 0.02 * Math.min(1, kConta / QUASE);

  // barras: proporção real entre valor e referência; a de referência entra quando ela é DITA
  const barIni = trava + q(TEMPO.atrasoInicial, p.fps);
  const maior = ref ? Math.max(Math.abs(valor), Math.abs(ref.valor)) : 1;
  const larguraBarra = W * 0.62;
  const barras = ref
    ? [
        { rot: d.rotulo_barra ?? d.unidade ?? '', v: valor, c: cor.destaque, t: barIni },
        {
          rot: ref.rotulo, v: ref.valor, c: cor.neutro,
          t: Math.max(barIni + q(TEMPO.staggerTotal, p.fps), quadro(p, tempoDe(p.palavras, [(ref as any).ancora, ref.rotulo], -1, (t0 - p.alca_antes) / p.fps))),
        },
      ]
    : [];
  const razao = ref && ref.valor ? Math.abs(valor / ref.valor) : 0;
  const tRazao = (barras[1]?.t ?? barIni) + q(TEMPO.entradaLonga, p.fps) + q(TEMPO.atrasoInicial, p.fps);
  const kRazao = interpolate(f, [tRazao, tRazao + q(TEMPO.entrada, p.fps)], [0, 1], { ...clamp, easing: ease.suave });

  return (
    <AbsoluteFill>
      <Fundo imagem={p.fundo} luzX={esq ? 0.3 : 0.5} luzY={0.42} />
      {/* luz quente atrás da cifra: dá volume sem "glow" de neon */}
      <AbsoluteFill
        style={{
          background: `radial-gradient(${W * 0.32}px ${H * 0.26}px at ${esq ? x0 + W * 0.22 : W / 2}px ${topo + tamanho * 0.5}px, ${alfa(cor.secundaria, 0.07 * entra)} 0%, ${alfa(cor.secundaria, 0)} 100%)`,
        }}
      />
      <Coreografia p={p} cx={esq ? x0 + W * 0.3 : W / 2} cy={topo + tamanho * 0.5}>
      <div
        style={{
          position: 'absolute',
          left: x0,
          width: larguraBloco,
          top: topo,
          textAlign: esq ? 'left' : 'center',
          fontFamily: fonte.titulo,
          fontWeight: 700,
          fontSize: tamanho,
          lineHeight: 1,
          letterSpacing: '-0.035em',
          color: cor.texto,
          fontVariantNumeric: 'tabular-nums lining-nums',
          fontFeatureSettings: '"tnum" 1, "lnum" 1',
          opacity: interpolate(entra, [0, 0.5], [0, 1], clamp),
          transform: `translateY(${(1 - entra) * 40 * u}px) scale(${assenta})`,
          transformOrigin: esq ? 'left bottom' : 'center bottom',
          whiteSpace: 'nowrap',
        }}
      >
        <Cifra texto={texto} />
        {sufixo ? (
          <span style={{ fontWeight: 400, fontStyle: 'italic', fontSize: tamanho * 0.36, marginLeft: '0.22em', letterSpacing: '-0.005em', color: cor.texto }}>
            {sufixo}
          </span>
        ) : null}
      </div>
      {/* régua de base sob a cifra */}
      <div style={{ position: 'absolute', left: esq ? x0 : W / 2 - W * 0.09, top: topo + tamanho * 1.08 }}>
        <Fio x={0} y={0} largura={esq ? W * 0.18 : W * 0.18} inicio={trava} espessura={Math.max(2, 3 * u)} />
      </div>
      {d.unidade ? (
        <div
          style={{
            position: 'absolute',
            left: x0,
            width: larguraBloco,
            top: topo + tamanho * 1.08 + 30 * u,
            textAlign: esq ? 'left' : 'center',
            fontFamily: fonte.rotulo,
            fontWeight: 600,
            fontSize: 30 * u,
            letterSpacing: '0.26em',
            textTransform: 'uppercase',
            color: cor.texto_suave,
            opacity: legenda,
            transform: `translateY(${(1 - legenda) * 14 * u}px)`,
          }}
        >
          {d.unidade}
        </div>
      ) : null}
      {ref ? (
        <div style={{ position: 'absolute', left: x0, top: H * 0.6, width: larguraBarra }}>
          {/* régua de quartos */}
          {[0, 0.25, 0.5, 0.75, 1].map((q) => (
            <div
              key={q}
              style={{
                position: 'absolute', left: larguraBarra * q, top: -14 * u, width: 1, height: H * 0.27,
                background: q === 0 ? alfa(cor.texto, 0.35) : alfa(cor.texto, 0.08),
                opacity: interpolate(f, [barIni - 6, barIni + 6], [0, 1], clamp),
              }}
            />
          ))}
          {barras.map((b, i) => {
            const kb = interpolate(f, [b.t, b.t + q(TEMPO.entradaLonga, p.fps)], [0, 1], { ...clamp, easing: ease.padrao });
            const kr = interpolate(f, [b.t - q(TEMPO.antecipacao, p.fps), b.t + q(TEMPO.entradaCurta, p.fps)], [0, 1], { ...clamp, easing: ease.saida });
            const larg = (larguraBarra * Math.abs(b.v)) / maior;
            return (
              <div key={i} style={{ position: 'relative', marginBottom: 40 * u, opacity: kr }}>
                <div
                  style={{
                    fontFamily: fonte.rotulo, fontWeight: 600, fontSize: 24 * u, letterSpacing: '0.2em', textTransform: 'uppercase',
                    color: i === 0 ? cor.texto : cor.texto_suave, marginBottom: 12 * u, transform: `translateX(${(1 - kr) * -10 * u}px)`,
                  }}
                >
                  {b.rot}
                </div>
                <div style={{ display: 'flex', alignItems: 'center', height: 34 * u }}>
                  <div
                    style={{
                      height: '100%', width: larg * kb, background: b.c,
                      
                    }}
                  />
                  <div
                    style={{
                      marginLeft: 16 * u, fontFamily: fonte.titulo, fontWeight: 600, fontSize: 34 * u, color: i === 0 ? cor.texto : cor.texto_suave,
                      fontVariantNumeric: 'tabular-nums lining-nums', whiteSpace: 'nowrap', opacity: kb,
                    }}
                  >
                    {num(Math.round(Math.abs(b.v) * kb))}
                  </div>
                </div>
              </div>
            );
          })}
          {razao >= 1.2 ? (
            <div
              style={{
                position: 'absolute', left: larguraBarra + 60 * u, top: 0, opacity: kRazao,
                transform: `translateY(${(1 - kRazao) * 12 * u}px)`, borderLeft: `${Math.max(2, 3 * u)}px solid ${cor.secundaria}`, paddingLeft: 22 * u,
              }}
            >
              <div style={{ fontFamily: fonte.titulo, fontWeight: 700, fontSize: 92 * u, lineHeight: 1, color: cor.secundaria, fontVariantNumeric: 'tabular-nums lining-nums' }}>
                ≈{num(razao, { maximumFractionDigits: razao < 10 ? 1 : 0 })}×
              </div>
              <div style={{ marginTop: 8 * u, fontFamily: fonte.rotulo, fontWeight: 600, fontSize: 20 * u, letterSpacing: '0.2em', textTransform: 'uppercase', color: cor.texto_suave }}>
                {ref.rotulo}
              </div>
            </div>
          ) : null}
        </div>
      ) : null}
      </Coreografia>
      <Textura />
    </AbsoluteFill>
  );
};
