const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../static/app.js'), 'utf8');
const init = source.slice(source.indexOf('const normalSpeedInputs'), source.indexOf('function saveNormalSpeed'));
for (const [saved, expected] of [[null, 0.5], ['', 0.5], ['0', 0.5], ['-1', 0.5], ['NaN', 0.5], ['Infinity', 0.5], ['0.3', 0.3]]) {
  const inputs = Object.fromEntries([['#normal-vx', '0.50'], ['#normal-vyaw', '1.00']].map(([id, value]) => [id, {
    value, get valueAsNumber() { return Number(this.value); },
  }]));
  const profiles = { normal: {} };
  vm.runInNewContext(init, { $: id => inputs[id], profiles, localStorage: { getItem: () => saved } });
  assert.equal(profiles.normal.vx, expected);
  assert.equal(profiles.normal.vyaw, saved === '0.3' ? 0.3 : 1);
}
const html = fs.readFileSync(path.join(__dirname, '../templates/index.html'), 'utf8');
for (const [, id] of source.matchAll(/\$\("#([\w-]+)"\)/g)) {
  assert.ok(html.includes(`id="${id}"`), `missing element: ${id}`);
}
assert.ok(!/slam|d435i/i.test(source + html));
const radar = source.slice(source.indexOf('  const radarValues'), source.indexOf('  $("#foot-force")'));
for (const [ranges, expected] of [
  [[0, 0, 0, 0], '未提供有效距离（不影响巡逻）'],
  [[0.1], '0.10 m（仅显示）'],
]) {
  const output = {};
  vm.runInNewContext(radar, { state: { range_obstacle: ranges },
    $: () => output, value: n => n.toFixed(2) });
  assert.equal(output.textContent, expected);
}
assert.ok(!/state\.lidar|LIDAR_TO_BODY/.test(source));
const actionHandler = source.slice(source.indexOf('document.querySelectorAll("[data-action]")'), source.indexOf('const patrolActions'));
assert.match(actionHandler, /hardStop\(false\)/);
assert.doesNotMatch(actionHandler, /await hardStop/);
async function checkPatrolAudio() {
  const start = source.slice(source.indexOf('async function startPatrol('), source.indexOf('$("#start-patrol").addEventListener'));
  for (const savePath of [false, true]) {
    for (const failure of ['', 'save', 'start', 'audio']) {
      const calls = [];
      const context = {
        handstandExiting: false, patrolRunning: false,
        profiles: { normal: { vx: 0.5, vyaw: 1 } },
        hardStop: send => { calls.push(`stop:${send}`); return true; },
        savePatrolPath: async () => { calls.push('save'); return failure !== 'save'; },
        post: async url => { calls.push(url); return failure === 'start' ? null : { code: 0 }; },
        updatePatrolButton() {}, audioStatus: {}, commandStatus: {},
        audioRequest: async (url, options) => {
          calls.push(url);
          assert.equal(options.method, 'POST');
          assert.equal(options.headers['Content-Type'], 'application/json');
          assert.deepEqual(JSON.parse(options.body), { unique_id: 'bf87bbfc-c62b-4e22-9393-f81b408552ab' });
          if (failure === 'audio') throw new Error('offline');
        },
      };
      await vm.runInNewContext(`${start}\nstartPatrol(${savePath})`, context);
      const started = failure !== 'start' && !(savePath && failure === 'save');
      assert.equal(calls.includes('/api/audio/play'), started);
      assert.equal(context.patrolRunning, started);
      if (started) assert.ok(calls.indexOf('/api/patrol/start') < calls.indexOf('/api/audio/play'));
      if (failure === 'audio') assert.match(context.commandStatus.textContent, /offline/);
    }
  }
}
checkPatrolAudio().then(() => console.log('frontend regression checks passed')).catch(error => {
  console.error(error);
  process.exitCode = 1;
});
