import { Config } from '@remotion/cli/config';

// PNG + bt709 evita o yuvj420p (pretos lavados) — lição do harness grio-motion
Config.setVideoImageFormat('png');
Config.setColorSpace('bt709');
Config.setPixelFormat('yuv420p');
