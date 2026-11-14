import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';

const roots = ['server.js', 'lib', 'public', 'test', 'scripts'];
const files = [];

for (const root of roots) {
  const stat = fs.statSync(root);
  if (stat.isFile() && root.endsWith('.js')) {
    files.push(root);
  } else if (stat.isDirectory()) {
    for (const entry of fs.readdirSync(root, { recursive: true })) {
      const full = path.join(root, entry);
      if (full.endsWith('.js') && fs.statSync(full).isFile()) {
        files.push(full);
      }
    }
  }
}

let failed = false;
for (const file of files) {
  try {
    execFileSync(process.execPath, ['--check', file], { stdio: 'pipe' });
    console.log(`ok    ${file}`);
  } catch (err) {
    failed = true;
    console.error(`FAIL  ${file}`);
    console.error(err.stderr.toString());
  }
}

if (failed) process.exit(1);
console.log(`\n${files.length} files checked, syntax OK`);
