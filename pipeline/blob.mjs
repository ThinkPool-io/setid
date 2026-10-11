// Tiny Vercel Blob helper for the local worker. Credentials come from the Vercel project via
// `vercel env run`, never from files or the shell. Usage:
//   node pipeline/blob.mjs put <pathname> <localFile>      -> prints {"url": ...}
//   node pipeline/blob.mjs list <prefix>                   -> prints [{"pathname","url","uploadedAt"}]
import { put, list } from '@vercel/blob';
import { readFileSync } from 'node:fs';
const [cmd, a, b] = process.argv.slice(2);
if (cmd === 'put') {
  const r = await put(a, readFileSync(b), { access: 'public', addRandomSuffix: false, allowOverwrite: true, contentType: 'application/json', cacheControlMaxAge: 60 });
  console.log(JSON.stringify({ url: r.url }));
} else if (cmd === 'list') {
  const out = []; let cursor;
  do { const r = await list({ prefix: a || '', cursor, limit: 1000 }); out.push(...r.blobs.map(x => ({ pathname: x.pathname, url: x.url, uploadedAt: x.uploadedAt }))); cursor = r.cursor; } while (cursor);
  console.log(JSON.stringify(out));
} else { console.error('usage: put <pathname> <file> | list <prefix>'); process.exit(2); }
