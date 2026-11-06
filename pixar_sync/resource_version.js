#!/usr/bin/env node
// Updates only the registered Pixar V2 JavaScript URL in Lovelace resources.
// No dashboards, devices, YAML, or other JavaScript resources are modified.
'use strict';
const fs = require('node:fs');
const path = require('node:path');
const TARGET = '/local/pixar-board/pixar-board-v2.js';
const HASH = process.argv[2] || '';
const TOKEN = process.env.SUPERVISOR_TOKEN;
const TEST_ONLY = Boolean(process.env.PIXAR_TEST_WS_URL);
const WS_URL = process.env.PIXAR_TEST_WS_URL || 'ws://supervisor/core/websocket';
const BACKUPS = process.env.PIXAR_RESOURCE_BACKUP_ROOT || '/data/resource-versions';
function fail(reason) {
  process.stderr.write('[pixar-resource] ' + String(reason) + '\n');
  process.exit(1);
}
if (!/^[a-f0-9]{64}$/i.test(HASH)) fail('Invalid JavaScript SHA-256');
if (!TOKEN && !TEST_ONLY) fail('Supervisor token unavailable');
if (!TEST_ONLY && WS_URL !== 'ws://supervisor/core/websocket') fail('Invalid WebSocket address');
if (typeof WebSocket !== 'function') fail('Node WebSocket unavailable');
const ws = new WebSocket(WS_URL);
let phase = 'handshake', sequence = 0, resource = null, newURL = '', backupPath = '';
const timeout = setTimeout(() => fail('Timed out; resource URL unchanged'), 16000);
function send(type, props = {}) {
  ws.send(JSON.stringify({id: ++sequence, type, ...props}));
}
function getList(msg) {
  if (Array.isArray(msg.result)) return msg.result;
  if (Array.isArray(msg.result?.items)) return msg.result.items;
  return [];
}
function isPixar(item) {
  if (!item || typeof item.url !== 'string') return false;
  if (!item.url.startsWith(TARGET)) return false;
  if (item.url.length > TARGET.length && item.url[TARGET.length] !== '?') return false;
  try {
    return new URL(item.url, 'http://homeassistant.local').pathname === TARGET;
  } catch (_) { return false; }
}
function versioned(url) {
  const qs = url.indexOf('?');
  const params = new URLSearchParams(qs < 0 ? '' : url.slice(qs + 1));
  params.set('v', 'git-' + HASH.slice(0, 12));
  return TARGET + '?' + params.toString();
}
function saveBeforeUpdate(item) {
  fs.mkdirSync(BACKUPS, {recursive: true, mode: 0o700});
  const filename = new Date().toISOString().replace(/[:.]/g, '-') +
    '-' + process.pid + '.json';
  const destination = path.join(BACKUPS, filename);
  const snapshot = {
    timestamp: new Date().toISOString(),
    resource_id: item.id, url_before: item.url,
    url_after: newURL, res_type: item.type || item.res_type,
    script_sha256: HASH,
  };
  fs.writeFileSync(destination, JSON.stringify(snapshot, null, 2),
    {encoding:'utf8',flag:'wx',mode:0o600});
  return destination;
}
function succeed(message) {
  clearTimeout(timeout);
  console.log('[pixar-resource] ' + message);
  phase = 'done';
  ws.close(1000);
}
ws.addEventListener('error', () => fail('Could not reach Home Assistant WebSocket'));
ws.addEventListener('close', () => {
  if (phase === 'done') process.exit(0);
  fail('WebSocket closed before confirmation');
});
ws.addEventListener('message', event => {
  let msg;
  try { msg = JSON.parse(event.data); }
  catch (_) { return fail('Invalid API response'); }
  if (msg.type === 'auth_required') {
    if (phase !== 'handshake') return fail('Unexpected authentication request');
    ws.send(JSON.stringify({type:'auth', access_token:TOKEN || 'test'}));
    phase = 'authentication';
    return;
  }
  if (msg.type === 'auth_invalid') return fail('Home Assistant refused authentication');
  if (msg.type === 'auth_ok') {
    if (phase !== 'authentication') return fail('Unexpected auth success');
    phase = 'read';
    send('lovelace/resources/list');
    return;
  }
  if (msg.type !== 'result') return;
  if (!msg.success) {
    return fail('Home Assistant rejected the resource request' +
      (msg.error?.code ? ' (' + msg.error.code + ')' : ''));
  }
  if (msg.id !== sequence) return fail('Unexpected response identifier');
  if (phase === 'read') {
    const matches = getList(msg).filter(isPixar);
    if (matches.length !== 1) {
      return fail('Exactly one Pixar V2 resource required, found ' + matches.length +
        '. No changes made.');
    }
    resource = matches[0];
    if (!resource.id || !['module','js'].includes(resource.type || resource.res_type)) {
      return fail('Unknown Pixar resource type or id');
    }
    newURL = versioned(resource.url);
    if (newURL === resource.url) return succeed('Pixar resource already up to date');
    try { backupPath = saveBeforeUpdate(resource); }
    catch (_) { return fail('Resource URL backup failed; no changes made'); }
    phase = 'update';
    send('lovelace/resources/update', {
      resource_id:resource.id, res_type:resource.type || resource.res_type, url:newURL
    });
    return;
  }
  if (phase === 'update') {
    phase = 'verify';
    send('lovelace/resources/list');
    return;
  }
  if (phase === 'verify') {
    const matching = getList(msg).filter(x => x.id === resource.id);
    if (matching.length !== 1 || matching[0].url !== newURL) {
      return fail('Could not verify resource URL update. Backup: ' + backupPath);
    }
    return succeed('Pixar resource URL updated: ' + newURL);
  }
  fail('Unexpected API state');
});
