import { build } from 'esbuild';
import { createServer } from 'node:http';
import { randomUUID } from 'node:crypto';
import { mkdir, mkdtemp, readFile, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { basename, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('.', import.meta.url));
const outputRoot = await mkdtemp(join(tmpdir(), 'flashrsi-electric-'));
const captures = new Map();
const result = await build({
  entryPoints: [join(root, 'app.jsx')],
  outdir: join(root, 'build'),
  bundle: true,
  write: false,
  jsx: 'automatic',
  format: 'iife',
  define: { 'process.env.NODE_ENV': '"production"' },
});
const assets = new Map(result.outputFiles.map(file => ['/' + basename(file.path), file.contents]));
assets.set('/', await readFile(join(root, 'index.html')));
assets.set('/base.svg', await readFile(join(root, 'base.svg')));
const types = { '/': 'text/html', '/app.js': 'text/javascript', '/app.css': 'text/css', '/base.svg': 'image/svg+xml' };

const server = createServer(async (req, res) => {
  try {
    const path = new URL(req.url, 'http://localhost').pathname;
    if (req.method === 'GET' && assets.has(path)) {
      res.writeHead(200, { 'Content-Type': types[path], 'Cache-Control': 'no-store' });
      res.end(assets.get(path));
      return;
    }
    if (req.method !== 'POST') {
      res.writeHead(404).end();
      return;
    }
    const chunks = [];
    let size = 0;
    for await (const chunk of req) {
      size += chunk.length;
      if (size > 4 * 1024 * 1024) throw new Error('Frame payload too large');
      chunks.push(chunk);
    }
    const body = JSON.parse(Buffer.concat(chunks).toString());
    let response;
    if (path === '/api/start') {
      const id = randomUUID();
      const directory = join(outputRoot, id);
      await mkdir(directory);
      captures.set(id, directory);
      response = { id };
    } else {
      const directory = captures.get(body.id);
      if (!directory) throw new Error('Unknown capture');
      if (path === '/api/frame') {
        if (!Number.isInteger(body.index) || body.index < 0 || body.index > 200) throw new Error('Invalid frame index');
        if (!body.png.startsWith('data:image/png;base64,')) throw new Error('Expected PNG frame');
        await writeFile(join(directory, `frame-${String(body.index).padStart(3, '0')}.png`), Buffer.from(body.png.split(',')[1], 'base64'));
        response = { ok: true };
      } else if (path === '/api/complete') {
        await writeFile(join(directory, 'capture.json'), JSON.stringify({ count: body.count, frameMs: 80, component: 'React Bits ElectricLogo' }, null, 2) + '\n');
        response = { directory, count: body.count };
        console.log(JSON.stringify({ capture: 'complete', ...response }));
      } else {
        res.writeHead(404).end();
        return;
      }
    }
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify(response));
  } catch (error) {
    res.writeHead(400, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ error: error.message }));
  }
});
server.listen(0, '127.0.0.1', () => {
  console.log(`Preview: http://127.0.0.1:${server.address().port}/ (pid ${process.pid})`);
  console.log(`Capture directory: ${outputRoot}`);
});
