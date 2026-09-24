/**
 * 深色模式切换的端到端测试（移动端入口 + 双处理器相互抵消的排查）。
 *
 * 背景
 * ----
 * 深色模式有两套实现：
 *   1. index.html 里的内联 IIFE：在 document 上做点击委托，同时处理
 *      #darkModeBtn 与 #darkModeBtnLanding，负责切类、换图标、写 localStorage
 *   2. app.js 的 LofFundMonitor.toggleDarkMode()：又给 #darkModeBtn 单独绑了一个 click
 * 两次点击都会触发，app.js 先跑（target 阶段），内联的随后跑（bubble 阶段）。
 * 内联那个读的是**当前 DOM 类**，于是很可能把刚切好的状态又切回去。
 *
 * 本测试在真实点击后断言：DOM 类、localStorage、按钮图标三者必须一致且都改变。
 *
 * 用法：node scripts/e2e_darkmode.mjs [baseUrl]
 */
import { chromium } from 'playwright';

const BASE = (process.argv[2] && !process.argv[2].startsWith('--') ? process.argv[2] : 'http://127.0.0.1:5599') + '/?api=';
const UPSTREAM = process.env.SHOT_UPSTREAM || 'https://jinkuaicha.com';
const LOCAL = /127\.0\.0\.1|localhost/.test(BASE);

const results = [];
function check(name, ok, detail) {
    results.push({ name, ok });
    console.log(`  ${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? '  — ' + detail : ''}`);
}

const browser = await chromium.launch();
const ctx = await browser.newContext({
    viewport: { width: 390, height: 844 }, deviceScaleFactor: 3, isMobile: true, hasTouch: true, locale: 'zh-CN',
    userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1',
});
const page = await ctx.newPage();
if (LOCAL) {
    await page.route('**/api/**', async route => {
        const u = new URL(route.request().url());
        try { await route.fulfill({ response: await route.fetch({ url: UPSTREAM + u.pathname + u.search, timeout: 60000 }) }); }
        catch { await route.abort().catch(() => {}); }
    });
}
await ctx.addInitScript(() => {
    try {
        sessionStorage.setItem('jkc_welcome_shown', '1');
        localStorage.removeItem('lof_threshold');
        // 刻意**不**在这里写 lof_darkMode：addInitScript 每次导航（含 reload）
        // 都会执行，写死就会把"刷新后是否保持"这一项自己擦掉 —— 那是测试的
        // 假象，不是产品行为。新 context 的 localStorage 本来就是空的，
        // 应用默认浅色，够用了。
    } catch (e) {}
});

const state = () => page.evaluate(() => ({
    cls: document.documentElement.classList.contains('dark-mode') ? 'dark' : 'light',
    ls: localStorage.getItem('lof_darkMode'),
    icon: (document.getElementById('darkModeBtn') || {}).textContent,
    iconLanding: (document.getElementById('darkModeBtnLanding') || {}).textContent,
}));

// ── 1. 数据页：按钮是否可见可点
await page.goto(BASE + '#/lof', { waitUntil: 'domcontentloaded' });
await page.waitForFunction(() => document.querySelectorAll('#mobileCardList .mobile-card').length > 0, { timeout: 60000 }).catch(() => {});
await page.waitForTimeout(2000);

const btnInfo = await page.evaluate(() => {
    const b = document.getElementById('darkModeBtn');
    if (!b) return null;
    const r = b.getBoundingClientRect();
    const cs = getComputedStyle(b);
    return { w: +r.width.toFixed(1), h: +r.height.toFixed(1), display: cs.display, visibility: cs.visibility };
});
check('数据页深色模式按钮在移动端可见',
    !!btnInfo && btnInfo.display !== 'none' && btnInfo.w > 0,
    btnInfo ? `${btnInfo.w}×${btnInfo.h} display=${btnInfo.display}` : '元素不存在');
check('数据页深色模式按钮达到可点尺寸（≥40px）',
    !!btnInfo && btnInfo.w >= 40 && btnInfo.h >= 40,
    btnInfo ? `${btnInfo.w}×${btnInfo.h}` : '-');

const s0 = await state();
check('初始为浅色', s0.cls === 'light' && (s0.ls === 'light' || s0.ls === null), JSON.stringify(s0));

// 真点一下
await page.locator('#darkModeBtn').click({ timeout: 8000 });
await page.waitForTimeout(500);
const s1 = await state();
check('点一次：DOM 变为深色', s1.cls === 'dark', `cls=${s1.cls}`);
check('点一次：localStorage 变为 dark', s1.ls === 'dark', `ls=${s1.ls}`);
check('点一次：图标变为 ☀️', s1.icon === '☀️', `icon=${s1.icon}`);
check('DOM / localStorage / 图标三者一致',
    s1.cls === s1.ls && (s1.cls === 'dark') === (s1.icon === '☀️'),
    JSON.stringify(s1));

// 再点一下应回到浅色
await page.locator('#darkModeBtn').click({ timeout: 8000 });
await page.waitForTimeout(500);
const s2 = await state();
check('点两次：回到浅色且状态一致',
    s2.cls === 'light' && s2.ls === 'light' && s2.icon === '🌙',
    JSON.stringify(s2));

// 切到深色后刷新，应保持深色（持久化）
await page.locator('#darkModeBtn').click({ timeout: 8000 });
await page.waitForTimeout(400);
await page.reload({ waitUntil: 'domcontentloaded' });
await page.waitForTimeout(1500);
const s3 = await state();
check('刷新后保持深色（持久化）', s3.cls === 'dark' && s3.ls === 'dark', JSON.stringify(s3));

// ── 2. 首页：落地页按钮
await page.goto(BASE + '#/', { waitUntil: 'domcontentloaded' });
await page.waitForTimeout(1200);
const lb = await page.evaluate(() => {
    const b = document.getElementById('darkModeBtnLanding');
    if (!b) return null;
    const r = b.getBoundingClientRect();
    return { w: +r.width.toFixed(1), h: +r.height.toFixed(1), display: getComputedStyle(b).display };
});
check('首页深色模式按钮在移动端可见',
    !!lb && lb.display !== 'none' && lb.w > 0,
    lb ? `${lb.w}×${lb.h} display=${lb.display}` : '元素不存在');
check('首页深色模式按钮达到可点尺寸（≥40px）',
    !!lb && lb.w >= 40 && lb.h >= 40,
    lb ? `${lb.w}×${lb.h}` : '-');

if (lb && lb.display !== 'none') {
    const before = await state();
    await page.locator('#darkModeBtnLanding').click({ timeout: 8000 });
    await page.waitForTimeout(500);
    const after = await state();
    check('点首页按钮能切换主题',
        after.cls !== before.cls && after.ls === after.cls,
        `${before.cls} → ${after.cls} (ls=${after.ls})`);
}

await browser.close();
const failed = results.filter(r => !r.ok);
console.log(`\n${results.length - failed.length}/${results.length} 通过`);
process.exit(failed.length ? 1 : 0);
