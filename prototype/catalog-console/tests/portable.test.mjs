import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';
import { sha256Fallback,rawDigest,demoId } from '../src/portable-crypto.ts';
import { createSeed,collect,sync } from '../src/engine.ts';

test('offline SHA-256 fallback matches Node vectors and raw Unicode/line endings',()=>{
  for(const raw of ['', 'abc','회원 원문 💾\n','a'.repeat(55),'a'.repeat(56),'a'.repeat(64),'a'.repeat(10000),'kind: Page\r\nmetadata:\r\n  name: demo']){
    assert.equal(sha256Fallback(raw),createHash('sha256').update(raw,'utf8').digest('hex'));
  }
});
test('standalone initialization and operations work without secure-context crypto APIs',async()=>{
  const descriptor=Object.getOwnPropertyDescriptor(globalThis,'crypto');
  try {
    Object.defineProperty(globalThis,'crypto',{value:undefined,configurable:true});
    assert.equal(await rawDigest('abc'),sha256Fallback('abc'));
    assert.notEqual(demoId(),demoId());
    const state=await createSeed();
    const observed=await collect(state);
    const applied=sync(observed,['members']);
    assert.equal(applied.resources.find(x=>x.id==='members').active,4);
  } finally {Object.defineProperty(globalThis,'crypto',descriptor);}
});
test('generated HTML is self-contained, parsable, and forbids runtime connections',async()=>{
  const html=await readFile(new URL('../index.html',import.meta.url),'utf8');
  assert.ok(html.startsWith('<!doctype html>'));
  assert.match(html,/<html lang="ko">/);
  assert.match(html,/connect-src 'none'/);
  assert.doesNotMatch(html,/<script[^>]+src=/i);
  assert.doesNotMatch(html,/<link[^>]+rel="stylesheet"/i);
  assert.doesNotMatch(html,/@import\s/);
  const scripts=[...html.matchAll(/<script>([\s\S]*?)<\/script>/g)];
  assert.equal(scripts.length,1);
  new vm.Script(scripts[0][1]);
  for(const license of ['MIT License','ISC License'])assert.ok(html.includes(license));
});
