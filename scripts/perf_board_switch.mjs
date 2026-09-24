/**
 * 板块切换性能探针
 *
 * 度量"点击 LOF基金 ⇄ ETF基金"从点击到新板块数据真正上屏的耗时，
 * 并把这段时间拆成：网络（API 往返）+ 解析/渲染。
 * 同时收集控制台错误 —— 切换路径上如果有异常被吞掉，这里必须看得见。
 *
 * 只读探针：不改产品代码，只包一层 fetch 记时间。
 *
 *   node scripts/perf_board_switch.mjs [url]
 */
import { chromium } from 'playwright';

const TARGET = process.argv[2] || 'https://jinkuaicha.com/#/lof';
const ROUNDS = Number(process.env.ROUNDS || 2);

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });

const consoleErrors = [];
page.on('console', (m) => {
  if (m.type() === 'error') consoleErrors.push(m.text());
});
page.on('pageerror', (e) => consoleErrors.push('pageerror: ' + e.message));

// 欢迎弹窗会盖住工具栏，先关掉它
await page.addInitScript(() => {
  try { sessionStorage.setItem('jkc_welcome_shown', '1'); } catch (e) {}
});

// 本地跑时把 /api/** 转发到线上后端：测的是本地这份 JS，数据是真的
{
  const origin = new URL(TARGET).origin;
  if (/localhost|127\.0\.0\.1/.test(origin)) {
    await page.route('**/api/**', async (route) => {
      const u = new URL(route.request().url());
      const resp = await route.fetch({ url: 'https://jinkuaicha.com' + u.pathname + u.search });
      await route.fulfill({ response: resp });
    });
  }
}

// 包一层 fetch，记录每次 /api/ 请求的起止与字节数
await page.addInitScript(() => {
  window.__apiLog = [];
  const orig = window.fetch;
  window.fetch = function (input, init) {
    const url = typeof input === 'string' ? input : (input && input.url) || '';
    const t0 = performance.now();
    const rec = { url, t0 };
    window.__apiLog.push(rec);
    return orig.apply(this, arguments).then(async (res) => {
      rec.t1 = performance.now();
      // 读 body 的耗时单独记：大响应体的解压+传输都发生在这里，
      // 只测到 response 头返回会严重低估真实耗时。
      try {
        const clone = res.clone();
        const text = await clone.text();
        rec.t2 = performance.now();
        rec.bytes = text.length;
      } catch (e) { rec.t2 = performance.now(); }
      rec.status = res.status;
      return res;
    }, (err) => { rec.t1 = performance.now(); rec.err = String(err); throw err; });
  };
});

await page.goto(TARGET, { waitUntil: 'domcontentloaded' });
// 等首屏板块数据上屏
await page.waitForFunction(() => {
  const cards = document.querySelectorAll('#fundTableBody tr.fund-row');
  return cards.length > 0;
}, { timeout: 90000 });
await page.waitForTimeout(2500);

const readLabel = () => page.$eval('#fundTypeSelect .ft-select-label, #fundTypeSelect .ft-current-label',
  (el) => el.textContent.trim()).catch(() => '?');
const rowCount = () => page.$$eval('#fundTableBody tr.fund-row', (n) => n.length);
const firstCode = () => page.$eval('#fundTableBody tr.fund-row td:nth-child(2)', (el) => el.textContent.trim())
  .catch(() => '?');

// 覆盖层（欢迎弹窗 / 错误框 / 遮罩）会拦住真实点击。这里用 evaluate 直接派发
// click：监听器还是产品自己的监听器，只是绕过命中测试。同时把覆盖层状态报出来 ——
// 它本身可能就是问题（页面上挂着错误提示却没人发现）。
async function probeOverlays() {
  return page.evaluate(() => {
    const out = {};
    for (const id of ['errorContainer', 'welcomeOverlay', 'loader', 'loadingOverlay']) {
      const el = document.getElementById(id);
      if (!el) continue;
      const cs = getComputedStyle(el);
      out[id] = { display: cs.display, pointerEvents: cs.pointerEvents, visible: el.offsetWidth > 0 || el.offsetHeight > 0 };
    }
    const msg = document.getElementById('errorMessage');
    if (msg) out.errorText = msg.textContent;
    return out;
  });
}

async function switchTo(target) {
  // target: 'etf' | 'lof'
  await page.evaluate(() => { window.__apiLog.length = 0; });
  const t0 = Date.now();
  await page.evaluate(() => document.getElementById('fundTypeSelect').click());
  await page.waitForTimeout(120);

  await page.evaluate((t) => {
    document.querySelector(`#fundTypeDropdown .ft-option[data-type="${t}"]`).click();
  }, target);

  const label = await readLabel();
  // 等新数据真的上屏：等一次 API 完成且表格非空。
  // 注意 API 可能压根不发（走了缓存 / 抛异常），所以这里超时后继续往下走，
  // 让"没有请求"这件事作为一个结果被报出来，而不是让脚本崩掉。
  let waited = 'api+rows';
  try {
    await page.waitForFunction(() => {
      const done = window.__apiLog.some((r) => r.t2 || r.err);
      const rows = document.querySelectorAll('#fundTableBody tr.fund-row').length;
      return done && rows > 0;
    }, { timeout: 45000 });
  } catch (e) {
    waited = 'timeout';
  }
  const tData = Date.now() - t0;
  await page.waitForTimeout(400);
  const tPaint = Date.now() - t0;

  const apiLog = await page.evaluate(() => window.__apiLog.map((r) => ({
    url: r.url.replace(location.origin, ''),
    ttfb: r.t1 ? Math.round(r.t1 - r.t0) : null,
    body: r.t2 ? Math.round(r.t2 - r.t0) : null,
    bytes: r.bytes || 0,
    status: r.status || null,
    err: r.err || null,
  })));

  return {
    target, label, waited,
    dataMs: tData,
    paintMs: tPaint,
    rows: await rowCount(),
    firstCode: await firstCode(),
    api: apiLog,
    overlays: await probeOverlays(),
  };
}

const results = [];
for (let i = 0; i < ROUNDS; i++) {
  results.push(await switchTo('etf'));
  await page.waitForTimeout(1500);
  results.push(await switchTo('lof'));
  await page.waitForTimeout(1500);
}

await browser.close();

console.log('=== 板块切换耗时（点击 → 新数据上屏）===');
console.log('目标    下拉文字   数据上屏     含渲染      行数   首行代码   等待条件');
for (const r of results) {
  console.log(
    `${r.target.padEnd(6)}  ${String(r.label).padEnd(9)}  ${String(r.dataMs + 'ms').padStart(9)}  ` +
    `${String(r.paintMs + 'ms').padStart(9)}  ${String(r.rows).padStart(5)}   ${String(r.firstCode).padEnd(9)}  ${r.waited}`
  );
}
console.log('');
console.log('=== 每次切换触发的 API 请求 ===');
for (const r of results) {
  for (const a of r.api) {
    console.log(`  [${r.target}] ttfb=${a.ttfb}ms  body读完=${a.body}ms  ${(a.bytes / 1024).toFixed(0)}KB  ${a.status}  ${a.url.slice(0, 60)}`);
  }
  if (r.api.length === 0) console.log(`  [${r.target}] 无 API 请求 —— 完全走缓存，没有拉新数据`);
}
console.log('');
console.log('=== 覆盖层状态（切换后）===');
for (const r of results) {
  console.log(`  [${r.target}] ` + JSON.stringify(r.overlays));
}
console.log('');
console.log('=== 控制台错误 ===');
if (consoleErrors.length === 0) console.log('  无');
else [...new Set(consoleErrors)].forEach((e) => console.log('  ' + e));
