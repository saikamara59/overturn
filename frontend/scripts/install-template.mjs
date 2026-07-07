import { copyFileSync, readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const src = join(here, '..', 'dist', 'index.html');
const dest = join(here, '..', '..', 'overturn', 'templates', 'workbench.html');

const html = readFileSync(src, 'utf8');
const marker = '/*__OVERTURN_DATA__*/{}';
const count = html.split(marker).length - 1;
if (count !== 1) {
  console.error(`FATAL: data-island marker appears ${count} times (must be exactly 1)`);
  process.exit(1);
}
if (!html.includes('id="overturn-data"')) {
  console.error('FATAL: overturn-data script island missing');
  process.exit(1);
}
copyFileSync(src, dest);
console.log(`installed ${dest}`);
