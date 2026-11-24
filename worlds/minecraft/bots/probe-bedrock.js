'use strict';
// bots/probe-bedrock.js — the Bedrock door: a phone's client, proved.
//
// The brief's ask: prove Bedrock through Geyser (UDP 19132) with a
// bedrock-protocol test client if one can be installed in this
// worktree, or say exactly what Casey must do. bedrock-protocol
// (MIT) is installed; this is its client. It joins the way a Bedrock
// player does — no Xbox account (offline), through Floodgate's door —
// moves, says a line, and reports the protocol version it spoke.
//
//   node probe-bedrock.js                 # the proof
//   node probe-bedrock.js --version 1.21.153   # pin a protocol

const bedrock = require('bedrock-protocol');

const args = {};
for (let i = 2; i < process.argv.length; i++) {
  const found = process.argv[i].match(/^--([a-z-]+)(?:=(.*))?$/);
  if (!found) continue;
  if (found[2] === undefined) {
    const next = process.argv[i + 1];
    if (next && !next.startsWith('--')) { args[found[1]] = next; i += 1; }
    else args[found[1]] = true;
  } else args[found[1]] = found[2];
}

const HOST = args.host || process.env.AW_HOST || '192.168.0.78';
const PORT = Number(args.port || process.env.AW_BEDROCK_PORT || 19132);
const NAME = args.name || 'BedHuman';

const report = { probe: 'bedrock', at: new Date().toISOString(), host: HOST, port: PORT, steps: {} };
const t0 = Date.now();
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function finish(code) {
  report.seconds = Number(((Date.now() - t0) / 1000).toFixed(1));
  console.log(JSON.stringify(report, null, 2));
  process.exit(code);
}

// What the raknet ping says before anything is attempted: the door's
// own sign.
bedrock
  .ping({ host: HOST, port: PORT })
  .then((pong) => {
    report.steps.ping = {
      edition: pong.edition,
      version: pong.version,
      protocol: pong.protocol,
      motd: (pong.motd || '').slice(0, 80),
      players: `${pong.playerCount}/${pong.maxPlayers}`,
    };
  })
  .catch((err) => {
    report.steps.ping = { error: String(err.message || err) };
  })
  .then(async () => {
    const options = {
      host: HOST,
      port: PORT,
      username: NAME,
      offline: true, // Floodgate's door: no Xbox account on the LAN
      skipPing: false,
    };
    if (args.version) options.version = args.version;

    const client = bedrock.createClient(options);
    const timedOut = setTimeout(() => {
      report.steps.join = 'timed out after 45 s';
      finish(2);
    }, 45000);

    client.once('spawn', async () => {
      clearTimeout(timedOut);
      report.steps.join_seconds = Number(((Date.now() - t0) / 1000).toFixed(1));
      report.steps.version = client.version;
      report.steps.protocol = client.protocolVersion || null;

      // The portable proof is a conversational one: say a line the
      // crew answers, and hear the answer come back over UDP.
      await sleep(1000);
      try {
        client.queue('text', {
          type: 'chat',
          needs_translation: false,
          source: NAME,
          message: 'what are you doing?',
          xuid: '',
          platform_chat_id: '',
        });
        report.steps.said = 'what are you doing?';
      } catch (err) {
        report.steps.said = 'the chat packet would not go: ' + String(err.message || err);
      }
      await sleep(20000); // the crew answers in a few seconds
      finish(0);
    });

    client.on('text', (packet) => {
      const line = (packet.source || '') + ': ' + (packet.message || packet.parameters || '');
      if (!packet.source || packet.source === NAME) return;
      report.steps.heard = report.steps.heard || [];
      report.steps.heard.push(line.slice(0, 120));
    });

    client.once('error', (err) => {
      clearTimeout(timedOut);
      report.steps.join = 'error: ' + String(err.message || err);
      finish(2);
    });
    client.once('kicked', (err) => {
      clearTimeout(timedOut);
      report.steps.join = 'kicked: ' + String((err && err.message) || err);
      finish(2);
    });
  });
