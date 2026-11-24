'use strict';
// bots/src/reflex.js — the client for the decision seam.
//
// The bots do not choose for themselves. Each tick a builder sends its
// state to the reflex service and gets back one skill to do; the reflex
// batches every builder's request into one call to the decision model.
// This file is that conversation, and nothing more.

const http = require('node:http');

class Reflex {
  constructor({ host = '127.0.0.1', port = 8110, timeout = 8000 } = {}) {
    this.host = host;
    this.port = port;
    this.timeout = timeout;
  }

  post(pathname, payload) {
    const body = Buffer.from(JSON.stringify(payload));
    return new Promise((resolve, reject) => {
      const req = http.request(
        {
          host: this.host,
          port: this.port,
          path: pathname,
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Content-Length': body.length,
          },
          timeout: this.timeout,
        },
        (res) => {
          const chunks = [];
          res.on('data', (c) => chunks.push(c));
          res.on('end', () => {
            const text = Buffer.concat(chunks).toString('utf8');
            try {
              resolve(JSON.parse(text));
            } catch (err) {
              reject(new Error(`the reflex said something that is not JSON: ${text.slice(0, 200)}`));
            }
          });
        }
      );
      req.on('timeout', () => req.destroy(new Error('the reflex did not answer in time')));
      req.on('error', reject);
      req.end(body);
    });
  }

  /** One tick's question: what should this builder do next? A `family`
   *  narrows the question to one skill family — that is how a chat
   *  command ("gather wood") asks for its skill without any model
   *  parsing the words. */
  decide({ bot, role, context, state, family }) {
    const payload = { bot, role, context, state };
    if (family) payload.family = family;
    return this.post('/decide', payload);
  }

  /** The play record: what happened, and did the prediction hold? */
  play(record) {
    return this.post('/play', record);
  }
}

module.exports = { Reflex };
