#!/usr/bin/env node
// Applies the Pixar dashboard configuration kept in GitHub to the single
// storage-mode dashboard "pixar-board-v2", through HA's Lovelace WebSocket API.
// No other dashboard, resource, YAML file or .storage file is modified.
// Refuses to overwrite a dashboard edited by hand since the last sync.
'use strict';
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const URL_PATH = 'pixar-board-v2';
const HASH = process.argv[2] || '';
const CONFIG_FILE = process.argv[3] || '';
const TOKEN = process.env.SUPERVISOR_TOKEN;
const TEST_ONLY = Boolean(process.env.PIXAR_TEST_WS_URL);
const WS_URL = process.env.PIXAR_TEST_WS_URL || 'ws://supervisor/core/websocket';
const DATA = process.env.PIXAR_DASHBOARD_DATA_ROOT || '/data';
const BACKUPS = path.join(DATA, 'dashboard-backups');
const STATE_FILE = path.join(DATA, 'dashboard-sync-state.json');
function fail(reason) {
  process.stderr.write('[pixar-dashboard] ' + String(reason) + '\n');
  process.exit(1);
}
function canonical(value) {
  if (Array.isArray(value)) return '[' + value.map(canonical).join(',') + ']';
  if (value && typeof value === 'object') {
    return '{' + Object.keys(value).sort().map(k => JSON.stringify(k) + ':' + canonical(value[k])).join(',') + '}';
  }
  return JSON.stringify(value);
}
function digest(value) {
  return crypto.createHash('sha256').update(canonical(value), 'utf8').digest('hex');
}
function viewPaths(config) {
  return (config.views || []).map(v => v && v.path).filter(p => typeof p === 'string');
}
function validate(config) {
  if (!config || typeof config !== 'object' || Array.isArray(config)) throw new Error('Dashboard must be a mapping');
  if (!Array.isArray(config.views) || config.views.length < 1 || config.views.length > 40) throw new Error('Unexpected views list');
  const paths = viewPaths(config);
  if (paths.length !== config.views.length) throw new Error('Every view needs a path');
  if (new Set(paths).size !== paths.length) throw new Error('Duplicate view path');
  const home = config.views.find(v => v.path === 'accueil');
  if (!home || home.strategy?.type !== 'custom:pixar-board-v2') throw new Error('Pixar home view missing');
  if (canonical(config).length > 2_000_000) throw new Error('Dashboard too large');
}
function loadState() {
  if (!fs.existsSync(STATE_FILE)) return null;
  const state = JSON.parse(fs.readFileSync(STATE_FILE, 'utf8'));
  if (!state || state.url_path !== URL_PATH) throw new Error('Unexpected dashboard sync state; no changes made');
  return state;
}
function saveState(remote) {
  const tmp = STATE_FILE + '.tmp';
  fs.writeFileSync(tmp, JSON.stringify({url_path: URL_PATH, source_sha256: HASH,
    remote_sha256: digest(remote), synced_at: new Date().toISOString()}, null, 2),
    {encoding: 'utf8', mode: 0o600});
  fs.renameSync(tmp, STATE_FILE);
}
function saveBackup(remote) {
  fs.mkdirSync(BACKUPS, {recursive: true, mode: 0o700});
  const name = new Date().toISOString().replace(/[:.]/g, '-') + '-' + process.pid + '.json';
  const destination = path.join(BACKUPS, name);
  fs.writeFileSync(destination, JSON.stringify({url_path: URL_PATH, previous: remote}, null, 2),
    {encoding: 'utf8', flag: 'wx', mode: 0o600});
  const all = fs.readdirSync(BACKUPS).filter(f => f.endsWith('.json')).sort();
  for (const old of all.slice(0, -10)) fs.unlinkSync(path.join(BACKUPS, old));
  return destination;
}

if (!/^[a-f0-9]{64}$/i.test(HASH)) fail('Invalid dashboard SHA-256');
if (!TOKEN && !TEST_ONLY) fail('Supervisor token unavailable');
if (!TEST_ONLY && WS_URL !== 'ws://supervisor/core/websocket') fail('Invalid WebSocket address');
if (typeof WebSocket !== 'function') fail('Node WebSocket unavailable');
let wanted;
try { wanted = JSON.parse(fs.readFileSync(CONFIG_FILE, 'utf8')); validate(wanted); }
catch (error) { fail('Dashboard file refused: ' + error.message); }
let state;
try { state = loadState(); } catch (error) { fail(error.message); }

const ws = new WebSocket(WS_URL);
let phase = 'handshake', sequence = 0, remote = null, backupPath = '';
const timeout = setTimeout(() => fail('Timed out; check dashboard, backup: ' + (backupPath || 'none')), 25000);
function send(type, props = {}) { ws.send(JSON.stringify({id: ++sequence, type, ...props})); }
function succeed(message) {
  clearTimeout(timeout);
  console.log('[pixar-dashboard] ' + message);
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
  try { msg = JSON.parse(event.data); } catch (_) { return fail('Invalid API response'); }
  if (msg.type === 'auth_required') {
    if (phase !== 'handshake') return fail('Unexpected authentication request');
    ws.send(JSON.stringify({type: 'auth', access_token: TOKEN || 'test'}));
    phase = 'authentication';
    return;
  }
  if (msg.type === 'auth_invalid') return fail('Home Assistant refused authentication');
  if (msg.type === 'auth_ok') {
    if (phase !== 'authentication') return fail('Unexpected auth success');
    phase = 'dashboards';
    send('lovelace/dashboards/list');
    return;
  }
  if (msg.type !== 'result') return;
  if (msg.id !== sequence) return fail('Unexpected response identifier');
  if (!msg.success) {
    if (phase === 'restore') return fail('Restore refused; restore manually from ' + backupPath);
    if (phase === 'save' || phase === 'verify') {
      phase = 'restore';
      return send('lovelace/config/save', {url_path: URL_PATH, config: remote});
    }
    return fail('Home Assistant rejected the dashboard request' +
      (msg.error?.code ? ' (' + msg.error.code + ')' : '') + '. No changes made.');
  }
  if (phase === 'dashboards') {
    const list = Array.isArray(msg.result) ? msg.result : [];
    const board = list.filter(d => d && d.url_path === URL_PATH);
    if (board.length !== 1 || board[0].mode !== 'storage') {
      return fail('Exactly one storage dashboard "' + URL_PATH + '" required. No changes made.');
    }
    phase = 'read';
    send('lovelace/config', {url_path: URL_PATH});
    return;
  }
  if (phase === 'read') {
    remote = msg.result;
    if (!remote || !Array.isArray(remote.views)) return fail('Current dashboard unreadable. No changes made.');
    if (state) {
      if (digest(remote) !== state.remote_sha256) {
        return fail('Dashboard edited by hand in Home Assistant since the last sync; refusing to overwrite. ' +
          'Copy the current raw configuration into GitHub, then delete ' + STATE_FILE + ' to resume.');
      }
      if (state.source_sha256 === HASH) return succeed('Dashboard already up to date');
    }
    const missing = viewPaths(remote).filter(p => !viewPaths(wanted).includes(p));
    if (missing.length) return fail('GitHub file would remove views (' + missing.join(', ') + '). No changes made.');
    if (digest(remote) === digest(wanted)) {
      try { saveState(remote); } catch (_) { return fail('Could not record sync state'); }
      return succeed('Dashboard already matches GitHub');
    }
    try { backupPath = saveBackup(remote); } catch (_) { return fail('Dashboard backup failed; no changes made'); }
    phase = 'save';
    send('lovelace/config/save', {url_path: URL_PATH, config: wanted});
    return;
  }
  if (phase === 'save') {
    phase = 'verify';
    send('lovelace/config', {url_path: URL_PATH});
    return;
  }
  if (phase === 'verify') {
    if (digest(msg.result) !== digest(wanted)) {
      phase = 'restore';
      send('lovelace/config/save', {url_path: URL_PATH, config: remote});
      return;
    }
    try { saveState(msg.result); } catch (_) { return fail('Dashboard updated but sync state not recorded'); }
    return succeed('Dashboard updated and verified. Backup: ' + backupPath);
  }
  if (phase === 'restore') return fail('Update could not be verified; previous dashboard restored. Backup: ' + backupPath);
  fail('Unexpected API state');
});
