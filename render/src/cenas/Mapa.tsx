import React, { useEffect, useMemo, useState } from 'react';
import { geoGraticule10, geoInterpolate, geoMercator, geoNaturalEarth1, geoPath, type GeoProjection } from 'd3-geo';
import { feature } from 'topojson-client';
import { AbsoluteFill, cancelRender, continueRender, delayRender, interpolate, staticFile, useCurrentFrame } from 'remotion';
import { quadro, tempoDe, Textura } from '../comp/Base';
import { txt } from '../comp/i18n';
import { alfa, clamp, cor, ease, fonte, mapaCores, q as qf, rng, TEMPO } from '../comp/tokens';
import type { PropsCena } from '../tipos';

// Mapa animado com dados Natural Earth (domínio público) via world-atlas.
// A geometria é projetada UMA vez (enquadramento final, recorte folgado) e a câmera anima por transform:
// barato de renderizar e sem "tremer". Traços com vector-effect não engrossam com o zoom.

type Lugar = { nome: string; lat: number; lon: number; ancora?: string; rotulo?: string };

// função (não constante de módulo): lê os tokens do canal já aplicados por <Cena>
const estilos = () => ({
  escura: {
    agua: cor.tinta, terra: mapaCores.terra, borda: mapaCores.borda, grade: 'rgba(255,255,255,0.035)', texto: cor.texto,
    sub: cor.texto_suave, marca: cor.destaque, rota: cor.secundaria, destaque: alfa(cor.destaque, 0.13), fonteRot: fonte.rotulo,
  },
  antiga: {
    agua: '#d8ccb2', terra: '#efe6d2', borda: '#7a6a52', grade: 'rgba(90,70,40,0.16)', texto: '#2c241a',
    sub: '#5c4d3a', marca: cor.destaque, rota: cor.destaque, destaque: alfa(cor.destaque, 0.12), fonteRot: fonte.documento,
  },
});

const useTopo = (arquivos: string[]) => {
  const [dados, setDados] = useState<any[] | null>(null);
  const [h] = useState(() => delayRender('mapa'));
  useEffect(() => {
    Promise.all(arquivos.map((a) => fetch(staticFile(`mapas/${a}`)).then((r) => r.json())))
      .then((js) => {
        setDados(js);
        continueRender(h);
      })
      .catch((e) => cancelRender(e));
  }, [h]);
  return dados;
};

/**
 * Converte as camadas SVG (data URL) em bitmaps UMA vez. Um <img> SVG é re-rasterizado pelo Chrome
 * sempre que a escala da câmera muda — com sombra desfocada e linhas d'água isso custava ~1 q/s.
 * Como bitmap, o voo da câmera só reamostra a textura (custo de antes, ~18 q/s).
 */
const useRaster = (svgs: (string | null)[] | null, w: number, h: number) => {
  const [urls, setUrls] = useState<(string | null)[] | null>(null);
  const [hd] = useState(() => delayRender('mapa-raster'));
  const chave = svgs ? `[${svgs.map((s) => (s ? s.length : 0)).join(',')}]` : 'nada';
  useEffect(() => {
    if (!svgs) return;
    Promise.all(
      svgs.map(
        (s) =>
          new Promise<string | null>((ok, falha) => {
            if (!s) return ok(null);
            const im = new Image();
            im.onload = () => {
              const c = document.createElement('canvas');
              c.width = w;
              c.height = h;
              c.getContext('2d')!.drawImage(im, 0, 0, w, h);
              c.toBlob((b) => (b ? ok(URL.createObjectURL(b)) : falha(new Error('toBlob'))), 'image/png');
            };
            im.onerror = () => falha(new Error('svg do mapa não carregou'));
            im.src = s;
          }),
      ),
    )
      .then((u) => {
        setUrls(u);
        continueRender(hd);
      })
      .catch((e) => cancelRender(e));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chave]);
  return urls;
};

const MAPA_BITMAP = true;

export const Mapa: React.FC<{ p: PropsCena }> = ({ p }) => {
  const f = useCurrentFrame();
  const d = p.dados;
  const r = rng(p.seed);
  const W = p.largura;
  const H = p.altura;
  const u = H / 1080;
  const lugares: Lugar[] = d.lugares ?? [];
  const ESTILOS = estilos();
  const est = ESTILOS[(d.base as 'escura' | 'antiga') ?? 'escura'] ?? ESTILOS.escura;

  // extensão: caixa dos lugares + folga; um lugar só → zoom pedido (cidade/regiao/pais/mundo)
  const lats = lugares.map((l) => l.lat);
  const lons = lugares.map((l) => l.lon);
  const spanPedido: Record<string, number> = { cidade: 1.4, regiao: 9, pais: 22, continente: 60, mundo: 360 };
  const minSpan = spanPedido[d.zoom as string] ?? (lugares.length > 1 ? 2 : 9);
  const cLat = lats.length ? (Math.min(...lats) + Math.max(...lats)) / 2 : 20;
  const cLon = lons.length ? (Math.min(...lons) + Math.max(...lons)) / 2 : 0;
  const span = Math.max(minSpan, lats.length ? (Math.max(...lats) - Math.min(...lats)) * 1.6 : 0, lons.length ? (Math.max(...lons) - Math.min(...lons)) * 1.35 : 0);
  const res = span > 45 ? '110m' : span > 5 ? '50m' : '10m';
  const mundo = span >= 120;

  const topo = useTopo([`land-${res}.json`, `countries-${res}.json`]);

  const geo = useMemo(() => {
    if (!topo) return null;
    const [land, countries] = topo;
    const proj: GeoProjection = mundo ? geoNaturalEarth1() : geoMercator();
    if (mundo) proj.fitExtent([[W * 0.04, H * 0.06], [W * 0.96, H * 0.94]], { type: 'Sphere' } as any);
    else {
      const half = span / 2;
      const caixa = {
        type: 'Feature',
        // a caixa sempre contém os lugares com folga (antes, rotas norte–sul deixavam o ponto colado na borda)
        geometry: {
          type: 'MultiPoint',
          coordinates: [
            [cLon - half, Math.max(-80, lats.length ? Math.min(cLat - half * 0.56, Math.min(...lats) - 0.18 * (Math.max(...lats) - Math.min(...lats))) : cLat - half * 0.56)],
            [cLon + half, Math.min(80, lats.length ? Math.max(cLat + half * 0.56, Math.max(...lats) + 0.18 * (Math.max(...lats) - Math.min(...lats))) : cLat + half * 0.56)],
          ],
        },
      };
      proj.fitExtent([[W * 0.08, H * 0.1], [W * 0.92, H * 0.9]], caixa as any);
    }
    proj.clipExtent([[-W * 0.55, -H * 0.55], [W * 1.55, H * 1.55]]);
    const caminho = geoPath(proj);
    const terra = caminho(feature(land, land.objects.land) as any) ?? '';
    const paises = (feature(countries, countries.objects.countries) as any).features;
    const fronteiras = paises.map((x: any) => caminho(x) ?? '').join(' ');
    const alvo = ([] as string[]).concat(d.destaque_pais ?? []).map((s) => s.toLowerCase());
    const destaque = paises
      .filter((x: any) => alvo.includes(String(x.properties?.name ?? '').toLowerCase()))
      .map((x: any) => caminho(x) ?? '')
      .join(' ');
    const grade = caminho(geoGraticule10()) ?? '';
    const pts = lugares.map((l) => proj([l.lon, l.lat]) as [number, number]);
    // rota em grande círculo entre lugares consecutivos
    let rota = '';
    let compr = 0;
    let seqG: [number, number][] = [];
    if (d.rota && lugares.length > 1) {
      const seq: [number, number][] = [];
      for (let i = 0; i + 1 < lugares.length; i++) {
        const it = geoInterpolate([lugares[i].lon, lugares[i].lat], [lugares[i + 1].lon, lugares[i + 1].lat]);
        const a = proj(it(0)) as [number, number];
        const b = proj(it(1)) as [number, number];
        // arco: desloca o meio do trecho perpendicularmente (lado alternado), como nos mapas de documentário
        const dx = b[0] - a[0];
        const dy = b[1] - a[1];
        const L = Math.hypot(dx, dy) || 1;
        const lado = i % 2 === 0 ? 1 : -1;
        for (let k = 0; k <= 48; k++) {
          const t = k / 48;
          const q = proj(it(t)) as [number, number];
          const bojo = Math.sin(Math.PI * t) * L * 0.14 * lado;
          seq.push([q[0] - (dy / L) * bojo, q[1] + (dx / L) * bojo]);
        }
      }
      rota = 'M' + seq.map((q) => `${q[0].toFixed(1)},${q[1].toFixed(1)}`).join('L');
      for (let i = 1; i < seq.length; i++) compr += Math.hypot(seq[i][0] - seq[i - 1][0], seq[i][1] - seq[i - 1][1]);
      seqG = seq;
    }
    // base estática vira UMA imagem (SVG → data URL): o Chrome rasteriza uma vez e a câmera só transforma
    // o bitmap. Antes: milhares de vértices redesenhados por quadro (3–4 q/s); agora: ~20 q/s.
    // área = o que a câmera chega a mostrar (voo de até ~1,9×); escala final ~1 → sem supersampling
    const M = 0.5;
    const svg = (corpo: string) =>
      `data:image/svg+xml;charset=utf-8,${encodeURIComponent(
        `<svg xmlns="http://www.w3.org/2000/svg" width="${W * (1 + 2 * M)}" height="${H * (1 + 2 * M)}" viewBox="${-W * M} ${-H * M} ${W * (1 + 2 * M)} ${H * (1 + 2 * M)}">${corpo}</svg>`,
      )}`;
    // v3: sombra projetada da terra (relevo de "recorte de papel"), linhas d'água na costa (cartografia
    // antiga) ou brilho frio na costa (escura), luz interna suave e fronteiras finas. Tudo estático.
    const antiga = d.base === 'antiga';
    const agua = antiga
      ? [26, 16, 8].map((w, i) => `<path d="${terra}" fill="none" stroke="${est.borda}" stroke-opacity="${0.07 + i * 0.05}" stroke-width="${w * u}" stroke-linejoin="round"/>`).join('')
      : [18, 8].map((w, i) => `<path d="${terra}" fill="none" stroke="${mapaCores.costa}" stroke-opacity="${0.05 + i * 0.05}" stroke-width="${w * u}" stroke-linejoin="round"/>`).join('');
    const defs =
      `<defs>` +
      `<filter id="s" x="-10%" y="-10%" width="120%" height="120%"><feGaussianBlur stdDeviation="${6 * u}"/></filter>` +
      `<radialGradient id="lz" cx="0.4" cy="0.35" r="0.7"><stop offset="0" stop-color="#fff" stop-opacity="${antiga ? 0.22 : 0.06}"/><stop offset="1" stop-color="#fff" stop-opacity="0"/></radialGradient>` +
      `</defs>`;
    const base = svg(
      defs +
        `<path d="${grade}" fill="none" stroke="${est.grade}" stroke-width="1.2"/>` +
        agua +
        // sombra em 3 camadas deslocadas (sem feGaussianBlur: blur num SVG que a câmera escala é re-rasterizado)
        [[3, 5, 0.1], [5, 9, 0.08], [8, 14, 0.06]]
          .map(([dx, dy, a]) => `<path d="${terra}" fill="#000" fill-opacity="${antiga ? a * 1.6 : a * 4}" transform="translate(${dx * u},${dy * u})"/>`)
          .join('') +
        `<path d="${terra}" fill="${est.terra}"/>` +
        `<path d="${terra}" fill="url(#lz)"/>` +
        `<path d="${fronteiras}" fill="none" stroke="${est.borda}" stroke-opacity="0.8" stroke-width="${1.1 * u}" stroke-dasharray="${antiga ? `${5 * u} ${3 * u}` : 'none'}"/>` +
        `<path d="${terra}" fill="none" stroke="${est.borda}" stroke-width="${1.4 * u}"/>`,
    );
    const camadaDestaque = destaque
      ? svg(
          defs.replace('</defs>', `<filter id="g" x="-20%" y="-20%" width="140%" height="140%"><feGaussianBlur stdDeviation="${10 * u}"/></filter></defs>`) +
            `<path d="${destaque}" fill="none" stroke="${est.marca}" stroke-opacity="0.55" stroke-width="${10 * u}" filter="url(#g)"/>` +
            `<path d="${destaque}" fill="${est.destaque}"/>` +
            `<path d="${destaque}" fill="none" stroke="${est.marca}" stroke-width="${2.2 * u}" stroke-linejoin="round"/>`,
        )
      : null;
    // pontos da rota com comprimento acumulado → posição da "ponta" que viaja
    const acum: number[] = [0];
    for (let i = 1; i < seqG.length; i++) acum.push(acum[i - 1] + Math.hypot(seqG[i][0] - seqG[i - 1][0], seqG[i][1] - seqG[i - 1][1]));
    const pontoNa = (s: number): [number, number] | null => {
      if (seqG.length < 2) return null;
      let i = 1;
      while (i < acum.length - 1 && acum[i] < s) i++;
      const t = (s - acum[i - 1]) / Math.max(1e-6, acum[i] - acum[i - 1]);
      return [seqG[i - 1][0] + (seqG[i][0] - seqG[i - 1][0]) * t, seqG[i - 1][1] + (seqG[i][1] - seqG[i - 1][1]) * t];
    };
    return { base, camadaDestaque, destaque, pts, rota, compr, pontoNa };
  }, [topo]);

  const bitmaps = useRaster(geo ? (MAPA_BITMAP ? [geo.base, geo.camadaDestaque] : []) : null, W * 2, H * 2);
  if (!geo || !bitmaps) return null;

  // v4: câmera easeInOutCubic (acelera, cruza, POUSA) e PARA: depois da chegada nada se move na base;
  // rota, contorno e pinos só se desenham com a câmera parada (o olho não persegue duas coisas).
  // Motion blur: não usado — exigiria N sub-quadros por quadro (custo ×N) num voo que já é curto.
  const ini = p.alca_antes;
  const fimCam = ini + Math.min(p.corpo * 0.6, p.fps * 2.2);
  const k = interpolate(f, [ini, fimCam], [0, 1], { ...clamp, easing: ease.camera });
  const voo = d.rota ? 1.25 : mundo ? 1.12 : 1.6 + r() * 0.3;
  const escala = interpolate(k, [0, 1], [1 / voo, 1]);
  const foco0 = d.rota && geo.pts.length ? geo.pts[0] : [W / 2 + (r() - 0.5) * W * 0.1, H / 2];
  const fx = interpolate(k, [0, 1], [foco0[0], W / 2]);
  const fy = interpolate(k, [0, 1], [foco0[1], H / 2]);
  const tela = (q: [number, number]): [number, number] => [W / 2 + (q[0] - fx) * escala, H / 2 + (q[1] - fy) * escala];
  const transf = `translate(${W / 2}px, ${H / 2}px) scale(${escala}) translate(${-fx}px, ${-fy}px)`;

  // quando cada lugar aparece: quando é DITO (âncora → nome), nunca antes da câmera pousar; em ordem
  const parada = fimCam;
  const tLugar: number[] = [];
  let depoisSeg = -Infinity;
  lugares.forEach((l, i) => {
    const seg = tempoDe(p.palavras, [l.ancora, l.rotulo, l.nome], -1, depoisSeg);
    const t = quadro(p, seg >= 0 ? seg : 0.5 + i * 0.7) - qf(TEMPO.antecipacao, p.fps);
    tLugar.push(Math.max(i === 0 ? parada : tLugar[i - 1] + qf(TEMPO.entradaCurta, p.fps), t));
    if (seg >= 0) depoisSeg = seg + 0.05;
  });
  const rotaIni = Math.max(parada, tLugar[0] ?? ini);
  const rotaFim = Math.max(rotaIni + p.fps * 1.5, tLugar[tLugar.length - 1] ?? 0);
  const kRota = interpolate(f, [rotaIni, rotaFim], [0, 1], { ...clamp, easing: ease.padrao });
  // contorno do país em destaque: desenha (dashoffset) depois da parada
  const kContorno = interpolate(f, [parada, parada + qf(TEMPO.entradaLonga, p.fps) * 2], [0, 1], { ...clamp, easing: ease.padrao });
  const escura = est !== ESTILOS.antiga;
  const halo = escura ? cor.tinta : est.terra;
  const ponta = geo.rota && kRota > 0 && kRota < 1 ? geo.pontoNa(geo.compr * kRota) : null;
  const kTit = interpolate(f, [ini + qf(TEMPO.atrasoInicial, p.fps), ini + qf(TEMPO.atrasoInicial + TEMPO.entrada, p.fps)], [0, 1], { ...clamp, easing: ease.saida });

  return (
    <AbsoluteFill style={{ background: est.agua }}>
      {/* luz ambiente na água */}
      <AbsoluteFill
        style={{
          background: escura
            ? `radial-gradient(70% 60% at 45% 40%, rgba(${mapaCores.ambiente},0.22) 0%, rgba(${mapaCores.ambiente},0) 70%)`
            : 'radial-gradient(70% 60% at 45% 40%, rgba(255,250,235,0.35) 0%, rgba(255,250,235,0) 70%)',
        }}
      />
      <div style={{ position: 'absolute', left: 0, top: 0, transform: transf, transformOrigin: '0 0' }}>
        <img src={MAPA_BITMAP ? bitmaps[0] ?? undefined : geo.base} style={{ position: 'absolute', left: -W * 0.5, top: -H * 0.5, width: W * 2, height: H * 2 }} />
        {geo.camadaDestaque ? (
          <img
            src={MAPA_BITMAP ? bitmaps[1] ?? undefined : geo.camadaDestaque}
            style={{
              position: 'absolute', left: -W * 0.5, top: -H * 0.5, width: W * 2, height: H * 2,
              opacity: interpolate(f, [parada, parada + qf(TEMPO.entradaLonga, p.fps)], [0, 1], { ...clamp, easing: ease.saida }),
            }}
          />
        ) : null}
      </div>
      <svg width={W} height={H} style={{ position: 'absolute', inset: 0 }}>
        <g style={{ transform: transf, transformOrigin: '0 0' }}>
          {geo.destaque && kContorno > 0 ? (
            <path
              d={geo.destaque} fill="none" stroke={est.marca} strokeWidth={3 * u} strokeLinejoin="round" pathLength={1}
              strokeDasharray="1 1" strokeDashoffset={1 - kContorno} vectorEffect="non-scaling-stroke"
            />
          ) : null}
          {geo.rota ? (
            <>
              {/* "casco" escuro sob o traço: separa a rota do relevo */}
              <path
                d={geo.rota} fill="none" stroke={halo} strokeOpacity={0.8} strokeWidth={10 * u} strokeLinecap="round"
                strokeDasharray={`${geo.compr} ${geo.compr}`} strokeDashoffset={geo.compr * (1 - kRota)} vectorEffect="non-scaling-stroke"
              />
              <path
                d={geo.rota} fill="none" stroke={est.rota} strokeWidth={4.5 * u} strokeLinecap="round"
                strokeDasharray={`${geo.compr} ${geo.compr}`} strokeDashoffset={geo.compr * (1 - kRota)} vectorEffect="non-scaling-stroke"
              />
              {/* trilha pontilhada do trecho que falta, bem discreta */}
              <path
                d={geo.rota} fill="none" stroke={est.rota} strokeOpacity={0.28 * Math.min(1, kRota * 8)} strokeWidth={2 * u}
                strokeDasharray={`${2 * u} ${10 * u}`} strokeLinecap="round" vectorEffect="non-scaling-stroke"
              />
            </>
          ) : null}
        </g>
      </svg>
      {ponta
        ? (() => {
            const [x, y] = tela(ponta);
            return (
              <div style={{ position: 'absolute', left: x, top: y }}>
                <div style={{ position: 'absolute', left: -30 * u, top: -30 * u, width: 60 * u, height: 60 * u, borderRadius: 99, background: `radial-gradient(circle, ${escura ? alfa(cor.secundaria, 0.55) : alfa(cor.destaque, 0.4)} 0%, rgba(0,0,0,0) 70%)` }} />
                <div style={{ position: 'absolute', left: -7 * u, top: -7 * u, width: 14 * u, height: 14 * u, borderRadius: 99, background: escura ? '#fff4dc' : est.rota, boxShadow: `0 0 0 ${2.5 * u}px ${est.rota}` }} />
              </div>
            );
          })()
        : null}
      {lugares.map((l, i) => {
        const [x, y] = tela(geo.pts[i]);
        // pino: entra com overshoot leve; UM ping de ~600 ms quando é dito (sem anel em loop)
        const s = interpolate(f, [tLugar[i], tLugar[i] + qf(TEMPO.entradaCurta, p.fps)], [0, 1], { ...clamp, easing: ease.trava });
        const a = interpolate(f, [tLugar[i] + qf(TEMPO.antecipacao, p.fps), tLugar[i] + qf(TEMPO.entrada, p.fps)], [0, 1], { ...clamp, easing: ease.saida });
        const anel = interpolate(f, [tLugar[i], tLugar[i] + qf(TEMPO.ping, p.fps)], [0, 1], { ...clamp, easing: ease.saida });
        const direita = x < W * 0.7;
        // rótulo nunca sai do quadro: se o ponto está colado na borda de cima/baixo, o texto vai para dentro
        const yRot = y < H * 0.12 ? 18 * u : y > H * 0.88 ? -66 * u : -24 * u;
        const nome = l.rotulo ?? l.nome;
        return (
          <div key={i} style={{ position: 'absolute', left: x, top: y }}>
            {f >= tLugar[i] && anel < 1 ? (
              <div
                style={{
                  position: 'absolute', left: -10 * u - anel * 34 * u, top: -10 * u - anel * 34 * u, width: (20 + anel * 68) * u, height: (20 + anel * 68) * u,
                  borderRadius: 99, border: `${1.5 * u}px solid ${est.marca}`, opacity: (1 - anel) * 0.8,
                }}
              />
            ) : null}
            <div
              style={{
                position: 'absolute', left: -11 * u, top: -11 * u, width: 22 * u, height: 22 * u, borderRadius: 99, background: est.marca,
                boxShadow: `0 0 0 ${3.5 * u}px ${escura ? '#f4efe6' : '#fffaf0'}, 0 ${4 * u}px ${14 * u}px rgba(0,0,0,0.45)`,
                transform: `scale(${s})`,
              }}
            />
            <div
              style={{
                position: 'absolute', top: yRot, [direita ? 'left' : 'right']: 26 * u, whiteSpace: 'nowrap',
                opacity: a, transform: `translateX(${(1 - a) * (direita ? -14 : 14) * u}px)`,
              }}
            >
              <div
                style={{
                  fontFamily: est.fonteRot, fontWeight: escura ? 800 : 700, fontSize: (escura ? 34 : 40) * u,
                  letterSpacing: escura ? '0.16em' : '0.02em', textTransform: escura ? 'uppercase' : 'none', color: est.texto,
                  // halo em volta das letras (como em cartografia): legível sobre qualquer relevo, sem caixa
                  WebkitTextStroke: `${7 * u}px ${halo}`, paintOrder: 'stroke fill',
                } as React.CSSProperties}
              >
                {nome}
              </div>
            </div>
          </div>
        );
      })}
      {d.titulo ? (
        <div style={{ position: 'absolute', left: W * 0.06, top: H * 0.075, opacity: kTit, transform: `translateY(${(1 - kTit) * 12 * u}px)` }}>
          <div style={{ width: 48 * u * kTit, height: Math.max(2, 3 * u), background: cor.destaque, marginBottom: 16 * u }} />
          <div
            style={{
              fontFamily: fonte.titulo, fontWeight: 600, fontSize: 56 * u, letterSpacing: '-0.01em', color: est.texto,
              WebkitTextStroke: `${8 * u}px ${est.agua}`, paintOrder: 'stroke fill',
            } as React.CSSProperties}
          >
            {d.titulo}
          </div>
        </div>
      ) : null}
      <div style={{ position: 'absolute', right: W * 0.025, bottom: H * 0.025, fontFamily: fonte.rotulo, fontSize: 13 * u, letterSpacing: '0.12em', color: est.sub, opacity: 0.4 }}>
        {txt().creditoMapa}
      </div>
      {/* sem fibra aqui: custava ~15% de velocidade no voo da câmera */}<Textura vinheta={escura ? 0.8 : 0.5} />
    </AbsoluteFill>
  );
};
