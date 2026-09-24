/**
 * 验证 `switched is not defined` 的影响面。
 *
 * 假设：loadFunds 的"Phase 1 渲染缓存"分支在这行抛 ReferenceError，
 * 于是 (a) Phase 2 的网络请求永不发出，(b) finally 永不执行 → _loadingFunds 卡死 true
 *      → 之后的非强制刷新全部在并发保护处被静默丢弃。
 *
 * 做法：同一个浏览器上下文里连续加载页面两次（第二次 localStorage 里已有缓存），
 * 分别记录：API 请求次数、控制台错误、自动刷新是否还活着。
 *
 *   node scripts/probe_cache_throw.mjs                          # 打线上
 *   node scripts/probe_cache_throw.mjs "http://127.0.0.1:5599/?api=https://jinkuaicha.com#/lof"
 *                                                              # 打本地（API 转发到线上）
 */
import { chromium } from 'playwright';

const TARGET = process.argv[2] || 'https://jinkuaicha.com/#/lof';
const origin = new URL(TARGET).origin;
const isLocal = /localhost|127\.0\.0\.1/.test(origin);

const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
await ctx.addInitScript(() => {
  try { sessionStorage.setItem('jkc_welcome_shown', '1'); } catch (e) {}
});

// 本地跑时把 /api/** 转发到线上后端：这样测的是本地这份 JS，数据是真的
if (isLocal) {
  await ctx.route('**/api/**', async (route) => {
    const u = new URL(route.request().url());
    const resp = await route.fetch({ url: 'https://jinkuaicha.com' + u.pathname + u.search });
    await route.fulfill({ response: resp });
  });
}

async function loadAndObserve(label, { pokeAutoRefresh } = {}) {
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push('pageerror: ' + e.message));
  page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });

  await page.addInitScript(() => {
    window.__apiLog = [];
    const orig = window.fetch;
    window.fetch = function (input) {
      const url = typeof input === 'string' ? input : (input && input.url) || '';
      const rec = { url, t0: performance.now() };
      window.__apiLog.push(rec);
      return orig.apply(this, arguments).then((res) => { rec.t1 = performance.now(); return res; });
    };
  });

  await page.goto(TARGET, { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(() => document.querySelectorAll('#fundTableBody tr.fund-row').length > 0,
    { timeout: 90000 }).catch(() => {});
  await page.waitForTimeout(4000);

  const state1 = await page.evaluate(() => {
    const app = window.SPA && window.SPA._app;
    return {
      apiCalls: window.__apiLog.map((r) => r.url.replace(location.origin, '')),
      rows: document.querySelectorAll('#fundTableBody tr.fund-row').length,
      funds: app ? app.funds.length : null,
      loadingFunds: app ? app._loadingFunds : null,   // ← 卡死的话这里会是 true
      fundsMode: app ? app._fundsMode : null,
      toolbarTs: (document.getElementById('toolbarTimestamp') || {}).textContent,
      errVisible: (() => {
        const el = document.getElementById('errorContainer');
        return el ? getComputedStyle(el).display !== 'none' : null;
      })(),
    };
  });

  let afterRefresh = null;
  if (pokeAutoRefresh) {
    // 手动触发一次"非强制"刷新 —— 自动刷新走的正是这条路。
    // 如果 _loadingFunds 卡在 true，它会在并发保护处直接 return，一个请求都不发。
    const before = await page.evaluate(() => window.__apiLog.length);
    await page.evaluate(async () => { await window.SPA._app.loadFunds(); });
    await page.waitForTimeout(3000);
    afterRefresh = await page.evaluate((n) => ({
      newCalls: window.__apiLog.length - n,
      loadingFunds: window.SPA._app._loadingFunds,
    }), before);
  }

  console.log(`--- ${label} ---`);
  console.log(`  首屏 API 请求      : ${state1.apiCalls.length} 次 ${state1.apiCalls.length ? '' : '（← 一次都没发）'}`);
  state1.apiCalls.forEach((u) => console.log(`                       ${u.replace(/^https?:\/\/[^/]+/, '')}`));
  console.log(`  表格行数           : ${state1.rows}     funds=${state1.funds}   _fundsMode=${state1.fundsMode}`);
  console.log(`  _loadingFunds 卡死 : ${state1.loadingFunds === true ? '是 ← 致命' : '否'}`);
  console.log(`  工具栏时间戳       : ${state1.toolbarTs}`);
  console.log(`  错误框可见         : ${state1.errVisible}`);
  if (afterRefresh) {
    console.log(`  触发一次普通刷新   : 新发请求 ${afterRefresh.newCalls} 次` +
      (afterRefresh.newCalls === 0 ? '  ← 刷新已失效' : '') +
      `   _loadingFunds=${afterRefresh.loadingFunds}`);
  }
  console.log(`  控制台错误         : ${errors.length ? [...new Set(errors)].join(' | ') : '无'}`);
  console.log('');

  await page.close();
  return state1;
}

console.log(`目标：${TARGET}`);
console.log('');
console.log('=== 第 1 次加载（localStorage 无缓存）===');
await loadAndObserve('冷缓存', { pokeAutoRefresh: true });
console.log('=== 第 2 次加载（localStorage 已有上一轮写入的缓存）===');
const hot = await loadAndObserve('热缓存', { pokeAutoRefresh: true });

await browser.close();

// 退出码：热缓存下必须真的发出了请求，且 loading 不能卡死
const ok = hot.apiCalls.length > 0 && hot.loadingFunds !== true && hot.errVisible === false;
console.log(ok ? '结论：修复生效 —— 缓存命中不再中断加载，自动刷新可用'
               : '结论：仍然失败');
process.exit(ok ? 0 : 1);
