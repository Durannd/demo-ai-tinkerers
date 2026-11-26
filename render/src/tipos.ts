/** Contrato Python → Remotion. Escrito por pipeline/remotion.py; uma cena = um render. */
export type Palavra = { texto: string; ini: number; fim: number };

export type PropsCena = {
  cena_id: string;
  tipo: string;
  largura: number;
  altura: number;
  fps: number;
  /** total de quadros renderizados = alca_antes + corpo + alca_depois */
  frames: number;
  /** quadros extras antes do "corpo" (metade da transição de entrada) */
  alca_antes: number;
  corpo: number;
  /** semente estável (hash da cena): desempate de escolhas visuais */
  seed: number;
  narracao: string;
  /** tempo de cada palavra, em segundos, relativo ao início do corpo */
  palavras: Palavra[];
  /** imagens em public/ (caminhos para staticFile) */
  fundo?: string | null;
  imagens?: string[];
  /** largura/altura de cada imagem (mesma ordem) */
  aspectos?: number[];
  dados: Record<string, any>;
  /** canal do episódio, idioma (pt-BR | en) e tokens mesclados do canal (pipeline/remotion.py) */
  canal?: string;
  idioma?: string;
  tokens?: Record<string, any>;
};
