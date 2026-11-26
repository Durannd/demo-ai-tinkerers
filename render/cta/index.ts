// Entrada PRÓPRIA dos CTAs animados (pipeline/cta.py). Separada de src/ de propósito: o cache das cenas
// (pipeline/remotion.py → _versao_codigo) é o hash de render/src; mexer aqui não re-renderiza episódio nenhum.
import { registerRoot } from 'remotion';
import { RootCta } from './Root';

registerRoot(RootCta);
