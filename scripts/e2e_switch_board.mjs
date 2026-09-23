/**
 * 复现 / 验证「点击切换 ETF 板块没有立刻生效，必须等刷新才变」。
 *
 * 复现思路
 * --------
 * 把 **LOF** 的列表请求人为拖慢到 8 秒，然后在它**仍在途**时点击切换到 ETF。
 * 这正是用户遇到的情形：自动刷新每 90 秒发起一次，LOF 约 0.9 秒、ETF 约 2~3.5 秒，
 * 用户在这几秒里点切换，就会被 `loadFunds` 开头的并发保护静默丢弃。
 *
 * 判据
 * ----
 * 搜索框占位符里的"共 N 只"：LOF 411 / ETF 1669，量级差得远，是最好的区分器。
 *
 *   修复前：切换被丢弃 → 占位符停在 LOF 的 411 → FAIL
 *   修复后：切换立刻发起 → 5 秒内变成 1669 → PASS
 *           并且 8 秒后那个迟到的 LOF 响应不得把界面"闪回"到 LOF（代号丢弃）
 *
 * 用法
 * ----
 *   node scripts/e2e_switch_board.mjs [baseUrl]
 *   默认 https://jinkuaicha.com
 *
 * 依赖仓库根目录的 playwright（package.json 里已有）。
 */
import { chromium } from 'playwright';

const BASE = process.argv[2] || 'https://jinkuaicha.com';
const LOF_DELAY_MS = 8000;

const results = [];
function check(name, ok, detail) {
    results.push({ name, ok, detail });
    console.log(`  ${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? '  — ' + detail : ''}`);
}

function placeholderNum(s) {
    const m = /共(\d+)只/.exec(s || '');
    return m ? parseInt(m[1], 10) : null;
}

const browser = await chromium.launch();
const page = await browser.newPage();

let delayedLof = 0;
// 用正则而不是 glob：glob 里的 `?` 表示"任意一个字符"，
// 写成 '**/api/v1/funds?*' 匹配不到带查询串的 URL。
await page.route(/\/api\/v1\/funds\?/, async (route) => {
    if (route.request().url().includes('filter_mode=lof')) {
        delayedLof++;
        await new Promise((r) => setTimeout(r, LOF_DELAY_MS));
    }
    await route.continue();
});

/** 读到占位符里的"共N只"，直到满足 predicate 或超时 */
async function waitPlaceholder(predicate, timeoutMs) {
    const deadline = Date.now() + timeoutMs;
    let last = null;
    while (Date.now() < deadline) {
        last = placeholderNum(await page.getAttribute('#searchInput', 'placeholder'));
        if (predicate(last)) return last;
        await page.waitForTimeout(200);
    }
    return last;
}

try {
    console.log(`目标: ${BASE}\n`);

    await page.goto(`${BASE}/#/lof`, { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('#fundTypeSelect', { timeout: 30000 });

    // 首次访问会弹"同意并进入"，它会拦截所有点击
    try {
        const agree = page.locator('#welcomeAgreeBtn');
        if (await agree.isVisible({ timeout: 3000 })) {
            await agree.click({ timeout: 5000 });
            console.log('  (已关闭欢迎弹窗)');
        }
    } catch { /* 没弹窗就直接继续 */ }

    // 关键：等到"应用已创建且首屏 LOF 请求仍在途"。这就是用户点击时的真实状态，
    // 也是旧代码把切换丢掉的那一刻。等数据加载完再点就复现不出来了。
    await page.waitForFunction(
        () => !!(window.SPA && window.SPA._app && window.SPA._app._loadingFunds),
        null, { timeout: 40000 });

    const before = placeholderNum(await page.getAttribute('#searchInput', 'placeholder'));
    console.log(`  LOF 请求在途（被延迟 ${delayedLof} 次），当前占位符数字: ${before ?? '(未填)'}`);

    // ── 在途时切换到 ETF ──
    const t0 = Date.now();
    await page.click('#fundTypeSelect');
    await page.click('.ft-option[data-type="etf"]');

    const after = await waitPlaceholder((n) => n !== null && n > 1000, 5000);
    const elapsed = Date.now() - t0;
    console.log(`  点击后 ${elapsed}ms 占位符数字: ${after}`);

    check('切换后立刻加载 ETF（不等 90 秒自动刷新）',
        after !== null && after > 1000,
        `期望 >1000（ETF 约 1669），实际 ${after}`);
    check('切换在 5 秒内生效', elapsed < 5000, `${elapsed}ms`);

    // ── 迟到的 LOF 响应不得把界面闪回 LOF ──
    await page.waitForTimeout(LOF_DELAY_MS + 3000);
    const settled = placeholderNum(await page.getAttribute('#searchInput', 'placeholder'));
    check('迟到的 LOF 响应被丢弃（未闪回 LOF）',
        settled !== null && settled > 1000, `实际 ${settled}`);

    // ── URL / 标题 / 表格 ──
    const hash = await page.evaluate(() => location.hash);
    const title = await page.title();
    check('URL 变为 #/etf', hash === '#/etf', hash);
    check('标题反映 ETF', title.includes('ETF'), title);

    const rows = await page.evaluate(() =>
        Array.from(document.querySelectorAll('#fundTableBody tr.fund-row'))
            .map((tr) => tr.dataset.code));
    check('表格已渲染 ETF 行', rows.length > 0, `${rows.length} 行，首行 ${rows[0]}`);

    // ── 切回 LOF 同样要立刻生效 ──
    const t1 = Date.now();
    await page.click('#fundTypeSelect');
    await page.click('.ft-option[data-type="lof"]');
    const backNum = await waitPlaceholder((n) => n !== null && n < 1000, 5000);
    const backMs = Date.now() - t1;
    check('切回 LOF 同样立刻生效',
        backNum !== null && backNum < 1000, `实际 ${backNum}，耗时 ${backMs}ms`);
    check('切回在 5 秒内生效', backMs < 5000, `${backMs}ms`);
} catch (e) {
    console.error('运行出错:', e.message);
    results.push({ name: '执行', ok: false, detail: e.message });
} finally {
    await browser.close();
}

const failed = results.filter((r) => !r.ok);
console.log(`\n结果: ${results.length - failed.length}/${results.length} 通过`);
process.exit(failed.length ? 1 : 0);
