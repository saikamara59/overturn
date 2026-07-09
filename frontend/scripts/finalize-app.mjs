import { renameSync, existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const dist = join(dirname(fileURLToPath(import.meta.url)), '..', 'dist-app');
const from = join(dist, 'app.html');
const to = join(dist, 'index.html');
if (!existsSync(from)) {
  console.error('FATAL: dist-app/app.html not found — did the build run?');
  process.exit(1);
}
renameSync(from, to);
console.log(`renamed app.html -> index.html in ${dist}`);
