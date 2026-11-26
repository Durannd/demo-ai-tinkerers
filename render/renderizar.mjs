// Renderiza uma fila de cenas Remotion. Chamado pelo pipeline/remotion.py (e pelo pipeline/cta.py):
//   node renderizar.mjs fila.json
// fila.json = { concorrencia: number|null, gl, entrada?: "src/index.ts" | "cta/index.ts",
//               trabalhos: [{ props, saida, still?, composicao?: "Cena" | "Cta", alfa?: boolean }] }
// Empacota UMA vez e renderiza cada trabalho em sequência (cada render já é paralelo internamente).
// alfa = fundo transparente: ProRes 4444 (yuva444p10le) a partir de PNGs — os CTAs, sobrepostos pelo FFmpeg.
import { bundle } from '@remotion/bundler';
import { renderMedia, renderStill, selectComposition } from '@remotion/renderer';
import { readFileSync, rmSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const aqui = path.dirname(fileURLToPath(import.meta.url));
const fila = JSON.parse(readFileSync(process.argv[2], 'utf-8'));
const t0 = Date.now();
const serveUrl = await bundle({ entryPoint: path.join(aqui, fila.entrada ?? 'src/index.ts'), publicDir: path.join(aqui, 'public') });
console.log(`bundle ${((Date.now() - t0) / 1000).toFixed(1)}s`);

// o bundle (com a copia de public/, centenas de MB) fica na pasta Temp: sem apagar, cada chamada vaza um.
// Em 13/11/2026 foram 21 GB numa noite. Apaga o SEU bundle ao sair, com sucesso ou erro.
const limpar = () => { try { rmSync(serveUrl, { recursive: true, force: true }); } catch {} };
process.on('exit', limpar);

for (const job of fila.trabalhos) {
  const t = Date.now();
  const id = job.composicao ?? 'Cena';
  const composition = await selectComposition({ serveUrl, id, inputProps: job.props });
  if (job.still !== undefined) {
    await renderStill({ composition, serveUrl, inputProps: job.props, output: job.saida, frame: job.still, imageFormat: 'png' });
  } else if (job.alfa) {
    await renderMedia({
      composition,
      serveUrl,
      inputProps: job.props,
      codec: 'prores',
      proResProfile: '4444',
      pixelFormat: 'yuva444p10le',
      imageFormat: 'png',
      muted: true,
      concurrency: fila.concorrencia ?? null,
      outputLocation: job.saida,
      chromiumOptions: { gl: fila.gl ?? null },
    });
  } else {
    await renderMedia({
      composition,
      serveUrl,
      inputProps: job.props,
      codec: 'h264',
      crf: 12,
      x264Preset: 'ultrafast',
      pixelFormat: 'yuv420p',
      colorSpace: 'bt709',
      imageFormat: 'png',
      muted: true,
      concurrency: fila.concorrencia ?? null,
      outputLocation: job.saida,
      chromiumOptions: { gl: fila.gl ?? null },
    });
  }
  const s = (Date.now() - t) / 1000;
  console.log(`ok ${job.props.cena_id ?? job.props.id} ${composition.durationInFrames}q ${s.toFixed(1)}s (${(composition.durationInFrames / s).toFixed(1)} q/s)`);
}
