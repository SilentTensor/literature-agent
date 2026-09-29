const localtunnel = require('localtunnel');
const fs = require('fs');
const PORT = Number(process.argv[2] || 8765);
const OUT = process.argv[3];
const LOG = process.argv[4];
const NAMES = ['litsurvey-sdu', 'wenxian-agent', 'paper-scout-sdu', null];
let idx = 0;

function log(m) {
  const line = new Date().toISOString().replace('T',' ').slice(0,19) + '  ' + m;
  console.log(line);
  try { fs.appendFileSync(LOG, line + '\n'); } catch (e) {}
}

function connect() {
  const name = NAMES[idx];
  if (idx < NAMES.length - 1) idx++;
  log('connecting' + (name ? ' (wanting ' + name + ')' : '') + ' ...');
  localtunnel({ port: PORT, subdomain: name || undefined })
    .then(t => {
      const got = t.url.replace('https://','').replace('.loca.lt','');
      fs.writeFileSync(OUT, t.url + '\n', 'utf8');
      log('public url: ' + t.url + (got === name ? '  [custom name OK]' : '  [random name]'));
      t.on('close', () => { log('closed, retry in 5s'); setTimeout(connect, 5000); });
      t.on('error', e => log('tunnel error: ' + e.message));
    })
    .catch(e => { log('connect failed: ' + (e.message||e) + ' - retry in 15s'); setTimeout(connect, 15000); });
}
connect();
