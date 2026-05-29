// build_yisim.mjs — bundle the yi-sim engine into web/yisim.bundle.js.
//
// The engine's card_info.js dynamically imports either card_json_node.js
// (uses fs/path/url) or card_json_web.js (JSON imports) based on `process`.
// We define `process` as undefined to force the web branch, and stub the node
// builtins so the (unused) node branch still bundles. ufuzzy resolves from
// node_modules. Output is a self-contained IIFE that sets globalThis.yisim.
//
// Build-time only — the shipped app needs neither Node nor esbuild.

import { build } from 'esbuild';
import { fileURLToPath } from 'url';
import path from 'path';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

const stubNodeBuiltins = {
  name: 'stub-node-builtins',
  setup(b) {
    b.onResolve({ filter: /^(fs|path|url|node:fs|node:path|node:url)$/ }, (args) => ({
      path: args.path, namespace: 'node-stub',
    }));
    b.onLoad({ filter: /.*/, namespace: 'node-stub' }, () => ({
      contents: `
        export default {};
        export const fileURLToPath = () => '';
        export const readFileSync = () => '';
        export const join = (...a) => a.join('/');
        export const dirname = () => '';
      `,
      loader: 'js',
    }));
  },
};

await build({
  entryPoints: [path.join(__dirname, 'vendor', 'yisim', 'yisim_entry.js')],
  bundle: true,
  format: 'iife',
  platform: 'browser',
  target: ['chrome100'],
  outfile: path.join(__dirname, 'web', 'yisim.bundle.js'),
  define: { process: 'undefined' },
  loader: { '.json': 'json' },
  plugins: [stubNodeBuiltins],
  logLevel: 'info',
});

console.log('built web/yisim.bundle.js');
