// zplr_preview_server.mjs
// Локальный фолбэк превью: рендер ZPL -> PNG через zplr (Node).
//
// Вход:  ZPL-код на stdin.
// Выход: PNG в stdout (только один и только PNG).
// Переменные окружения:
//   ZPLR_DPMM       — плотность печати, точек/мм (по умолчанию 8).
//   ZPLR_TEXT_SCALE — масштаб текстовых полей (по умолчанию 0.66).
//   ZPLR_FONT       — путь к TTF/OTF с кириллицей для текста.
//
// Смысл: геометрия/графика/штрихкоды совпадают с Labelary, а текст
// отрисовывается шрифтом с кириллицей (встроенный шрифт zplr её не имеет).
// Опциональный узел: если node/zplr недоступны, Python-сторона переходит
// на Pillow. Здесь при недоступности zplr возвращаем ненулевой код.

import { readFile } from 'node:fs/promises';
import { renderZplPNG } from 'zplr';

const dpmm = Number(process.env.ZPLR_DPMM || 8);
const scale = Number(process.env.ZPLR_TEXT_SCALE || '0.66');
const fontFile = process.env.ZPLR_FONT || '';

const data = await new Promise((resolve, reject) => {
  let buf = '';
  process.stdin.setEncoding('utf8');
  process.stdin.on('data', (c) => { buf += c; });
  process.stdin.on('end', () => resolve(buf));
  process.stdin.on('error', reject);
});

// Преобразуем поля со встроенного шрифта "0" на именованный TrueType,
// сохраняя ориентацию и масштабируя h/w на заданный коэффициент.
const transform = data.replace(/\^A0([NRIB]),(\d+),(\d+)/g, (_m, o, h, w) => {
  const hh = Math.max(1, Math.round(Number(h) * scale));
  const ww = Math.max(1, Math.round(Number(w) * scale));
  return `^A@${o},${hh},${ww},R:PREVIEW.TTF`;
});

try {
  const [png] = await renderZplPNG(transform, {
    printDensity: dpmm,
    fontProvider: {
      async resolveFont(name) {
        if (String(name).toUpperCase().endsWith('PREVIEW.TTF')) {
          if (!fontFile) return undefined;
          return readFile(fontFile);
        }
        return undefined;
      },
    },
  });
  if (!png) {
    console.error('zplr вернул пустой результат');
    process.exit(1);
  }
  process.stdout.write(png);
} catch (e) {
  console.error('zplr renderZplPNG failed:', e && e.message ? e.message : e);
  process.exit(1);
}
