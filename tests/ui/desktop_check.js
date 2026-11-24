// Runs inside the native desktop window (python -m nexus.desktop --script ...). Returns a dict of checks.
const sl = ms => new Promise(r => setTimeout(r, ms));
const $ = s => document.querySelector(s), $$ = s => [...document.querySelectorAll(s)];
const until = async (f, ms, what) => { const t = Date.now(); while (Date.now() - t < ms) { if (f()) return true; await sl(250); } throw new Error("timeout: " + what); };
const R = {};
R.desktopApi = !!window.pywebview && !!window.pywebview.api && __probe().desktop;

// 1) frozen picture: Observer -> My Worker (connect, disconnect) -> Observer -> Demo Mode
$('[data-mode=worker]').click(); await sl(600);
$('#c-btn').click(); await until(() => $('#c-badge').textContent.startsWith('Online'), 15000, 'local worker online');
$('#c-btn').click(); await until(() => $('#c-badge').textContent === 'Offline', 10000, 'local worker offline');
$('[data-mode=observer]').click(); await sl(700);
R.graphWidthAfterReturn = $('#graph').clientWidth;
$('#demo-btn').click();
await until(() => $$('.tile.done').length > 5, 30000, 'tiles after demo');
const d0 = $$('.tile.done').length, poly0 = $$('#charts polyline').map(e => e.getAttribute('points')).join('|'); await sl(3000);
R.tilesAdvanced = $$('.tile.done').length > d0;
R.chartsChanged = $$('#charts polyline').map(e => e.getAttribute('points')).join('|') !== poly0;
R.nodes = $$('#nodes .node').length;

// 2) kill a demo worker by clicking its node
const target = $('#nodes .node.demo'); R.demoNodes = $$('#nodes .node.demo').length; const tid = target.id;
target.querySelector('.pill').click();
await until(() => $('#' + tid).classList.contains('dead'), 10000, 'node dead after click');
R.killed = true;

// 3) downloads through the native save path (Python writes into --save-dir)
await until(() => !$('#download').disabled, 90000, 'job done');
$('#download').click(); await sl(1500); R.toastPng = $('#toast').textContent;
const png = atob('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==');
const r = await fetch(__probe().base + '/api/jobs', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ type: 'image', params: { images: [{ name: 'a.png', data: btoa(png) }], format: 'WEBP', max_side: 64 } }) });
R.imageJobStatus = r.status;
await until(() => __probe().job && __probe().job.total === 1 && !$('#download').disabled, 60000, 'image job done');
$('#download').click(); await sl(2000); R.toastZip = $('#toast').textContent;
R.maximize = await new Promise(res => { try { $('#w-max').click(); setTimeout(() => { $('#w-max').click(); res(true); }, 600); } catch (e) { res(false); } });
R.banner = __probe().banner;
return R;
