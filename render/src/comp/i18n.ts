// Textos fixos das cenas e formatação numérica por idioma. Espelho de pipeline/i18n.py.
// O idioma chega em props.idioma ("pt-BR" | "en") e é aplicado por aplicarCanal() no início da cena.

const TEXTOS = {
  pt: {
    capitulo: 'Capítulo',
    traducao: 'TRADUÇÃO',
    milhao: ['milhão', 'milhões'],
    bilhao: ['bilhão', 'bilhões'],
    meses: ['jan.', 'fev.', 'mar.', 'abr.', 'maio', 'jun.', 'jul.', 'ago.', 'set.', 'out.', 'nov.', 'dez.'],
    creditoMapa: 'Natural Earth',
    peca: 'Peça',
  },
  en: {
    capitulo: 'Chapter',
    traducao: 'TRANSLATION',
    milhao: ['million', 'million'],
    bilhao: ['billion', 'billion'],
    meses: ['Jan.', 'Feb.', 'Mar.', 'Apr.', 'May', 'June', 'July', 'Aug.', 'Sept.', 'Oct.', 'Nov.', 'Dec.'],
    creditoMapa: 'Natural Earth',
    peca: 'Piece',
  },
} as const;

type Lingua = keyof typeof TEXTOS;
const estado: { lingua: Lingua; locale: string } = { lingua: 'pt', locale: 'pt-BR' };

export const definirIdioma = (idioma?: string | null) => {
  const en = String(idioma ?? 'pt-BR').toLowerCase().startsWith('en');
  estado.lingua = en ? 'en' : 'pt';
  estado.locale = en ? 'en-US' : 'pt-BR';
};

export const lingua = () => estado.lingua;
export const txt = () => TEXTOS[estado.lingua];
/** Separador decimal do idioma ("," em pt-BR, "." em en). */
export const sepDecimal = () => (estado.lingua === 'en' ? '.' : ',');
/** toLocaleString no idioma do episódio (8,7 / 71.000 em pt-BR; 8.7 / 71,000 em en-US). */
export const num = (v: number, opcoes?: Intl.NumberFormatOptions) => v.toLocaleString(estado.locale, opcoes);
/** Data "1919-01-15" → { ano: "1919", resto: "15 jan." (pt) | "Jan. 15" (en) }. */
export const dataCurta = (dia: number | null, mes: number) => {
  const m = txt().meses[mes - 1] ?? String(mes);
  if (!dia) return m;
  return estado.lingua === 'en' ? `${m} ${dia}` : `${dia} ${m}`;
};
