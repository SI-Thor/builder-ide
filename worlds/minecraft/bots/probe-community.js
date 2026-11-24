'use strict';
// bots/probe-community.js — the community doors, from a person's seat.
//
// The brief's community round adds three doors a returning human
// meets: the greeting that names the work in hand, "what are you
// building?" answered from the board, and a request ("build a farm")
// becoming a project proposal through the validator. This probe is
// that human: it joins, listens for the greeting, asks, and prints
// what came back, with times.
//
//   node probe-community.js
//
// Exits by itself in ~90 s.

const mineflayer = require('mineflayer');

const host = process.env.AW_HOST || '192.168.0.78';
const port = Number(process.env.AW_PAPER_PORT || 25565);

const bot = mineflayer.createBot({
  host, port, username: 'TestHumanC', auth: 'offline', version: '26.1',
});

const t0 = Date.now();
const heard = [];
bot.on('chat', (from, message) => {
  if (from === bot.username) return;
  if (/^TestHumanC/.test(from)) return; // the server echoes our own line with our name
  heard.push({ at: Date.now() - t0, from, message });
  console.log(`[+${((Date.now() - t0) / 1000).toFixed(1)}s] ${from}: ${message}`);
});

const ask = (line) => {
  console.log(`[ask] ${line}`);
  bot.chat(line);
};

bot.once('spawn', () => {
  console.log('joined');
  // the greeting arrives within a few seconds of the join
  setTimeout(() => ask('what are you building?'), 8000);
  setTimeout(() => ask('build a farm'), 30000);
  setTimeout(() => ask('what are you building?'), 60000);
  setTimeout(() => {
    const said = heard.map((h) => h.message).join(' | ');
    const greeted = /Welcome, TestHumanC/.test(said);
    const board = /the community is building/.test(said);
    const proposal = /on the board|already on the board|not that one|no ground/.test(said);
    console.log(JSON.stringify({ greeted, board, proposal, lines: heard.length }, null, 1));
    bot.quit();
    process.exit(0);
  }, 80000);
});

bot.once('error', (err) => {
  console.error('probe failed:', err.message);
  process.exit(1);
});
