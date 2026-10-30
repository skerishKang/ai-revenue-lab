#!/usr/bin/env node
/*
 * #4139 read-only probe: can the agent's own process lane be reached, and what
 * fields does it answer with?
 *
 * This is the observation that closes the open items of
 * docs/architecture/PADIEM_CONNECTOR_NATIVE_PROCESS_LANE_4139_20261029.md section 5.
 * It sends TWO frames and nothing else:
 *
 *   {action:'msg', type:'ps',     nodeid, responseid}   agents/meshcore.js:1498-1504
 *   {action:'msg', type:'psinfo', nodeid, pid, ...}     agents/meshcore.js:1505-1539
 *
 * It has no code path that sends `pskill` (`agents/meshcore.js:1542`) and no option
 * that would add one. Nothing on the PC is started, stopped or changed.
 *
 * What it prints is deliberately narrow: counts and FIELD NAMES. Process command
 * lines and user names are the two fields a customer's machine has most of, and they
 * are never copied to a terminal, a log or this script's output - only the key names
 * of the records are, because the question is "what shape is the answer", not "what
 * is running".
 *
 * Credential: the operator password is read from the first line of standard input,
 * the same way the executor hands it to the official client
 * (local_agent_meshcentral_private_reader.py, _MESHCTRL_STDIN_LINE_BOOTSTRAP). It is
 * used to build one header value and is never printed, logged or kept.
 *
 * TLS: this asks the server on this host, over the loopback address that the tunnel
 * binds, with certificate verification off - the same choice the official client makes
 * for this exact socket (meshctrl.js:1381, `rejectUnauthorized: false`), because that
 * certificate is the server's own. A non-loopback url is refused unless
 * `--allow-remote-unverified` is given, so this script cannot quietly become a way to
 * send an operator credential across a network path it was not written for.
 */
'use strict';

const crypto = require('crypto');
const fs = require('fs');
const path = require('path');

const USAGE = `usage: node mesh_process_lane_probe.js --id <nodeRef> [options]
  password is read from the first line of stdin; never an argument

  --id <ref>            device the way meshctrl names it: node/<domain>/<hex>
                        or <hex>@<mesh> (required)
  --url <wss://host>    default wss://127.0.0.1:4443
  --loginuser <name>    operator account, default admin (meshctrl.js:1391)
  --token <value>       optional second factor in the x-meshauth header
  --ws-module <dir>     directory holding MeshCentral's node_modules/ws,
                        default /opt/meshcentral/node_modules/ws
  --wait-seconds <n>    bound on each answer, default 20 (communication only)
  --pid <n>             pid to ask psinfo about; default: the lowest one in ps
  --dry-run             print the frames that WOULD be sent and exit (sends nothing)
`;

function fail(message) {
  process.stderr.write('PROBE_ABORT ' + message + '\n');
  process.exit(2);
}

function argument(name, fallback) {
  const i = process.argv.indexOf(name);
  if (i < 0) return fallback;
  if (i + 1 >= process.argv.length) fail(name + ' needs a value');
  return process.argv[i + 1];
}

function loadWebSocket() {
  const candidates = [];
  const given = argument('--ws-module', null);
  if (given != null) candidates.push(given);
  candidates.push('/opt/meshcentral/node_modules/ws');
  candidates.push(path.join(process.cwd(), 'node_modules', 'ws'));
  for (const candidate of candidates) {
    try { return require(candidate); } catch (ex) { /* try the next one */ }
  }
  try { return require('ws'); } catch (ex) { /* fall through to the message below */ }
  fail('the ws module MeshCentral already ships could not be loaded; pass --ws-module');
}

function readPassword() {
  // One line, no trailing newline, and never echoed. A pipe with nothing in it is a
  // refusal, not an empty password.
  try {
    const input = fs.readFileSync(0, 'utf8');
    const first = input.split(/\r?\n/)[0];
    if (!first) fail('no credential on standard input');
    return first;
  } catch (ex) {
    fail('the credential could not be read from standard input');
  }
}

function nodeRef(id) {
  const trimmed = String(id).trim();
  if (!trimmed) fail('--id is required');
  // The server completes a bare id into the current domain (meshuser.js:1033); a
  // meshctrl-style "<hex>@<mesh>" is the node's own id, so hand it over unchanged and
  // let the route answer for itself.
  return trimmed;
}

function fieldNames(records, limit) {
  const names = new Set();
  let counted = 0;
  for (const record of records) {
    if (record == null || typeof record !== 'object') continue;
    for (const key of Object.keys(record)) names.add(String(key));
    counted++;
    if (counted >= limit) break;
  }
  return Array.from(names).sort();
}

function main() {
  if (process.argv.includes('--help')) { process.stdout.write(USAGE); return; }

  const id = argument('--id', null);
  const url = argument('--url', 'wss://127.0.0.1:4443');
  const loginuser = argument('--loginuser', 'admin');
  const token = argument('--token', null);
  const waitSeconds = Number(argument('--wait-seconds', '20'));
  const askedPid = argument('--pid', null);
  if (!Number.isFinite(waitSeconds) || waitSeconds <= 0) fail('--wait-seconds must be a positive number');

  const target = nodeRef(id);
  const psFrame = { action: 'msg', type: 'ps', nodeid: target, responseid: 'padiem-probe-' + crypto.randomBytes(6).toString('hex') };
  const responseId = psFrame.responseid;

  if (process.argv.includes('--dry-run')) {
    // The frames carry no secret; this is what the operator reads before trusting it.
    process.stdout.write(JSON.stringify(psFrame) + '\n');
    process.stdout.write(JSON.stringify({ action: 'msg', type: 'psinfo', nodeid: target, pid: askedPid || '<lowest from ps>', responseid: responseId + '-info' }) + '\n');
    process.stdout.write('DRY_RUN sent=0 (nothing was connected, nothing was asked)\n');
    return;
  }

  // The credential is only ever handed to this host's own server. Anything else needs
  // to be said out loud, and even then verification stays off because that is how this
  // socket is served - see the header note. The route is checked before the credential
  // is read, so a wrong target is refused without touching the secret file.
  let endpoint = null;
  try { endpoint = new URL(url); } catch (ex) { fail('the url is not parseable'); }
  const host = endpoint.hostname.replace(/^\[|\]$/g, '');
  const loopback = host === '127.0.0.1' || host === 'localhost' || host === '::1'
    || host.startsWith('127.');
  if (!loopback && !process.argv.includes('--allow-remote-unverified')) {
    fail('this probe asks this host only; pass --allow-remote-unverified if that is really intended');
  }

  const password = readPassword();
  const WebSocket = loadWebSocket();

  // The same header the official client builds for this socket (meshctrl.js:1395):
  // base64(user),base64(pass)[,base64(token)]. One value, in memory, never printed.
  const meshauth = Buffer.from(String(loginuser)).toString('base64') + ',' + Buffer.from(password).toString('base64')
    + (token == null ? '' : ',' + Buffer.from(String(token)).toString('base64'));

  const controlUrl = url.replace(/\/$/, '') + '/control.ashx';
  const socket = new WebSocket(controlUrl, { rejectUnauthorized: false, headers: { 'x-meshauth': meshauth } });

  const result = { ps_reply: false, ps_count: 0, ps_fields: [], ps_parent_like: [], psinfo_reply: false, psinfo_fields: [], routed_error: false, notes: [] };
  let psRecords = null;
  let asked = { ps: false, psinfo: false };
  let finished = false;

  const deadline = setTimeout(() => close('the bound ended before every answer arrived'), waitSeconds * 1000 + 5000);

  function close(reason) {
    if (finished) return;
    finished = true;
    clearTimeout(deadline);
    result.notes.push(reason);
    try { socket.close(); } catch (ex) { }
    report();
  }

  function report() {
    // Only counts, key names and booleans leave this function.
    process.stdout.write('PROBE_RESULT ' + JSON.stringify(result) + '\n');
    const code = result.ps_reply ? 0 : 3;
    process.exit(code);
  }

  function askPsInfo(pid) {
    asked.psinfo = true;
    socket.send(JSON.stringify({ action: 'msg', type: 'psinfo', nodeid: target, pid: pid, responseid: responseId + '-info' }));
  }

  socket.on('open', () => {
    asked.ps = true;
    socket.send(JSON.stringify(psFrame));
  });

  socket.on('message', (raw) => {
    if (finished) return;
    let message = null;
    try { message = JSON.parse(raw.toString()); } catch (ex) { return; }
    if (message == null || typeof message !== 'object') return;

    if (message.action === 'msg' && message.type === 'ps') {
      result.ps_reply = true;
      result.nodeid_echoed = typeof message.nodeid === 'string';
      let records = null;
      try { records = JSON.parse(message.value); } catch (ex) { result.notes.push('the ps value was not parseable JSON'); }
      if (records != null && typeof records === 'object') {
        const keys = Object.keys(records);
        result.ps_count = keys.length;
        const list = [];
        for (const key of keys) {
          const record = records[key];
          if (record == null || typeof record !== 'object') continue;
          list.push(record);
          // pid keys are numbers in the table; note the key form only.
        }
        result.ps_fields = fieldNames(list, 8);
        result.ps_parent_like = result.ps_fields.filter((name) => /parent|ppid/i.test(name));
        result.ps_pid_key_is_numeric = keys.length > 0 && keys.every((key) => /^\d+$/.test(key));
        const pids = keys.filter((key) => /^\d+$/.test(key)).map(Number).sort((a, b) => a - b);
        if (pids.length === 0) {
          result.notes.push('no numeric pid keys, so psinfo was not asked');
          close('done');
          return;
        }
        askPsInfo(askedPid == null ? pids[0] : Number(askedPid));
      } else {
        close('done');
      }
      return;
    }

    if (message.action === 'msg' && message.type === 'psinfo') {
      result.psinfo_reply = true;
      if (message.value != null && typeof message.value === 'object') {
        result.psinfo_fields = Object.keys(message.value).sort();
        result.psinfo_parent_like = result.psinfo_fields.filter((name) => /parent|ppid/i.test(name));
      } else {
        result.notes.push('psinfo answered without an object value (the agent may return an empty detail set)');
      }
      close('done');
      return;
    }

    if (message.action === 'msg' && typeof message.result === 'string') {
      // "Unable to route" and friends (meshuser.js:1025) - a name, no content.
      result.routed_error = true;
      result.routed_error_kind = message.result === 'Unable to route' ? 'unable_to_route' : 'other';
      return;
    }

    if (message.action === 'serverinfo' || message.action === 'userinfo') return; // the socket's own welcome
  });

  socket.on('error', (ex) => {
    result.notes.push('the socket reported an error of kind ' + (ex && ex.code ? ex.code : 'unnamed'));
    close('stopped');
  });
  socket.on('close', () => {
    if (!finished) close('the server closed the socket before every answer arrived');
  });
}

main();
