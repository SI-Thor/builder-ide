'use strict';
// bots/board-unstage.js — zero a project's staged materials on the
// board. The staged counts are the board's memory of deliveries; when
// the delivered items despawn before the owner picks them up (a toss
// that skids out of range lives five minutes), the memory lies and the
// supply loop believes a want is already served. This re-opens it.
//
//   node board-unstage.js b037 b044
//
// Appends one materials event per project (staged zeroed for every
// material the project names). Safe while the bots run; they replay
// the log on their next start.
const path = require('path');
const { Board } = require('./src/board');

const ids = process.argv.slice(2);
if (!ids.length) {
  console.error('usage: node board-unstage.js <project-id>...');
  process.exit(1);
}
const logPath = path.join(__dirname, '..', 'runtime', 'logs', 'board.jsonl');
const board = new Board(logPath);
for (const id of ids) {
  const project = board.get(id);
  if (!project) {
    console.error(`no project ${id} on the board`);
    continue;
  }
  const zeroed = {};
  for (const name of Object.keys(project.materials || {})) zeroed[name] = 0;
  board.stagedMaterials(id, zeroed);
  console.log(`unstaged ${id}:`, JSON.stringify(zeroed));
}
