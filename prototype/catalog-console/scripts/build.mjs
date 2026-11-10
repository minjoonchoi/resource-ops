import { build } from 'esbuild';
import { readFile, writeFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root=resolve(dirname(fileURLToPath(import.meta.url)),'..');
const checking=process.argv.includes('--check');
const result=await build({
  absWorkingDir:root,entryPoints:['src/main.tsx'],bundle:true,minify:true,write:false,
  format:'iife',platform:'browser',target:'es2022',jsx:'automatic',legalComments:'inline',
  define:{'process.env.NODE_ENV':'"production"'},metafile:true,outfile:'console.js',
});
const packages=['react','react-dom','scheduler','yaml','lucide-react'];
const notices=['# Third-party notices','This standalone HTML redistributes the following browser dependencies.\nTheir original license notices are retained below and embedded in index.html.\n'];
for(const name of packages){
  const base=resolve(root,'node_modules',name);
  const meta=JSON.parse(await readFile(resolve(base,'package.json'),'utf8'));
  const license=await readFile(resolve(base,'LICENSE'),'utf8');
  notices.push(`## ${name} ${meta.version}\n\nLicense: ${meta.license}\n\n${license.trim()}\n`);
}
const licenseText=notices.join('\n');
const js=result.outputFiles[0].text.replace(/<\/script/gi,'<\\/script');
const css=(await readFile(resolve(root,'src/styles.css'),'utf8')).replace(/<\/style/gi,'<\\/style');
const html=`<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="description" content="resource-ops YAML 카탈로그 운영 콘솔 · 독립 HTML 시뮬레이션">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data: blob:; connect-src 'none'; base-uri 'none'; form-action 'none'; object-src 'none'">
<title>resource-ops · Catalog Console</title>
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Crect width='64' height='64' rx='16' fill='%234366e4'/%3E%3Cpath d='m12 24 20-11 20 11-20 11Zm0 9 20 11 20-11M12 42l20 11 20-11' fill='none' stroke='white' stroke-width='3.5' stroke-linejoin='round'/%3E%3C/svg%3E">
<!-- Generated from prototype/catalog-console/src. No CDN, backend, or runtime downloads. -->
<!--\n${licenseText.replace(/-->/g,'-- >')}\n-->
<style>${css}</style>
</head>
<body>
<div id="root"></div>
<noscript>이 시뮬레이션은 브라우저의 JavaScript가 필요합니다. 원격 서버에는 연결하지 않습니다.</noscript>
<script>${js}</script>
</body>
</html>
`;
for(const [file,contents] of [['index.html',html],['THIRD_PARTY_NOTICES.md',licenseText]]){
  const output=resolve(root,file);
  if(checking){if(await readFile(output,'utf8')!==contents)throw Error(`${file} differs from source; run npm run build.`);}
  else await writeFile(output,contents);
}
console.log(`${checking?'Verified':'Built'} self-contained index.html (${Buffer.byteLength(html).toLocaleString()} bytes); no external assets.`);
