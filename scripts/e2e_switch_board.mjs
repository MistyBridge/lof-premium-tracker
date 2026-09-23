/**
 * 复现 / 验证「点击切换 ETF 板块没有立刻生效，必须等刷新才变」。
 *
 * 复现思路
 * --------
 * 把 **首个 LOF** 列表请求人为拖慢到 8 秒，然后在它**仍在途**时点击切换到 ETF。
 * 这正是用户遇到的情形：自动刷新每 90 秒发起一次，LOF 约 0.9 秒、ETF 约 2~3.5 秒，
 * 用户在这几秒里点切换，就会被 `loadFunds` 开头的并发保护静默丢弃。
 *
 * 判据（关键的一条是"请求有没有立刻发出去"，而不是"多久收到响应"）
 * --------------------------------------------------------------
 *   修复前：点击后**根本没有** etf 请求发出，占位符停在 LOF 的 411
 *   修复后：点击后 1 秒内就发出 etf 请求，稍后渲染成 1669；
 *           且 8 秒后迟到的 LOF 响应被请求代号丢弃，界面不闪回 LOF
 *
 * 只延迟**第一个** LOF 请求：Playwright 的 route 处理器是串行的，若每个 LOF
 * 请求都睡 8 秒，后面切回 LOF 的那次也会被自己的延迟挡住，测出来的是测试的
 * 假象而不是产品行为（这一点是踩过一次才改的）。
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
const REQ_DEADLINE_MS = 1000;   // 点击后多久之内必须发出新板块的请求（真正的判据）
// 渲染完成的时间只用来兜底：ETF 荷载 1.65MB，实测 2~7 秒（受服务端与链路影响），
// 卡太紧会变成随机失败。真正能抓住回归的是上面那个"请求有没有立刻发出"。
const RENDER_DEADLINE_MS = 15000;

const FUNDS_RE = /\/api\/v1\/funds\?/;

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

let heldLofRoute = null;   // 被"挂住"的第一个 LOF 请求
let lofHeld = false;

// 用正则而不是 glob：glob 里的 `?` 是"任意一个字符"，
// 写成 '**/api/v1/funds?*' 匹配不到带查询串的 URL。
//
// 这里刻意**不 await 任何延迟**：Playwright 的 route 处理器是串行的，
// 一旦在处理器里 sleep，后面所有被拦截的请求都会排队等它 —— 那样测出来的
// 是测试自己的假象（曾把 ETF 响应硬生生拖到 8.3 秒）。
// 正确做法是保存 route 引用后**立刻返回**，让请求自然悬停在"在途"状态，
// 需要放行时再调 continue()。
await page.route(FUNDS_RE, async (route) => {
    const url = route.request().url();
    if (url.includes('filter_mode=lof') && !lofHeld) {
        lofHeld = true;
        heldLofRoute = route;
        return;                       // 挂起：不 continue 也不 fulfill
    }
    await route.continue();
});

/** 轮询占位符里的"共N只"，直到满足 predicate 或超时 */
async function waitPlaceholder(predicate, timeoutMs) {
    const deadline = Date.now() + timeoutMs;
    let last = null;
    while (Date.now() < deadline) {
        last = placeholderNum(await page.getAttribute('#searchInput', 'placeholder'));
        if (predicate(last)) return last;
        await page.waitForTimeout(150);
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

    // 关键：等到"应用已创建、首屏 LOF 请求仍在途"。这就是用户点下去那一刻的
    // 真实状态，也是旧代码把切换丢掉的那一刻。等数据加载完再点就复现不出来。
    await page.waitForFunction(
        () => !!(window.SPA && window.SPA._app && window.SPA._app._loadingFunds),
        null, { timeout: 40000 });

    const before = placeholderNum(await page.getAttribute('#searchInput', 'placeholder'));
    console.log(`  LOF 请求在途，当前占位符数字: ${before ?? '(未填)'}\n`);

    // ══ 场景 1：在 LOF 请求在途时切到 ETF ══
    const t0 = Date.now();
    const mark = (s) => console.log(`  [+${String(Date.now() - t0).padStart(5)}ms] ${s}`);
    let etfReqAt = null;
    page.on('request', (r) => {
        if (!FUNDS_RE.test(r.url())) return;
        const tag = r.url().includes('filter_mode=etf') ? 'etf' : 'lof';
        if (tag === 'etf' && etfReqAt === null) etfReqAt = Date.now() - t0;
        mark(`REQ  ${tag}`);
    });
    page.on('response', (r) => {
        if (FUNDS_RE.test(r.url())) {
            mark(`RES  ${r.url().includes('filter_mode=etf') ? 'etf' : 'lof'}  ${r.status()}`);
        }
    });

    await page.click('#fundTypeSelect');
    await page.click('.ft-option[data-type="etf"]');
    mark('已点 ETF 选项');

    const after = await waitPlaceholder((n) => n !== null && n > 1000, RENDER_DEADLINE_MS);
    const elapsed = Date.now() - t0;
    console.log(`  点击后 ${elapsed}ms 占位符数字: ${after}\n`);

    // ── 核心判据：请求有没有立刻发出去 ──
    // 旧代码在这里是**根本没发请求**（被并发保护 return 掉了），
    // 所以这条比"响应多快"更能说明问题。
    check(`点击后 ${REQ_DEADLINE_MS}ms 内发出 ETF 请求`,
        etfReqAt !== null && etfReqAt <= REQ_DEADLINE_MS,
        etfReqAt === null ? '压根没发请求' : `${etfReqAt}ms`);
    check('ETF 数据渲染完成',
        after !== null && after > 1000,
        `期望 >1000（ETF 约 1669），实际 ${after}`);
    check(`渲染在 ${RENDER_DEADLINE_MS}ms 内`, elapsed < RENDER_DEADLINE_MS, `${elapsed}ms`);

    // ── 放行那个被挂住的 LOF 响应：迟到的响应必须被丢弃 ──
    const holdMs = Date.now() - t0;
    if (heldLofRoute) {
        mark('放行被挂住的 LOF 响应');
        heldLofRoute.continue().catch(() => {});
        heldLofRoute = null;
    }
    await page.waitForTimeout(3000);
    const settled = placeholderNum(await page.getAttribute('#searchInput', 'placeholder'));
    check('迟到的 LOF 响应被丢弃（未闪回 LOF）',
        settled !== null && settled > 1000,
        `LOF 被挂住 ${holdMs}ms 后放行，界面仍为 ${settled}`);

    // ── URL / 标题 / 表格内容 ──
    const hash = await page.evaluate(() => location.hash);
    const title = await page.title();
    check('URL 变为 #/etf', hash === '#/etf', hash);
    check('标题反映 ETF', title.includes('ETF'), title);

    const rows = await page.evaluate(() =>
        Array.from(document.querySelectorAll('#fundTableBody tr.fund-row'))
            .map((tr) => tr.dataset.code));
    // LOF 是 16xxxx/50xxxx，ETF 是 15xxxx/51xxxx-58xxxx。
    // 旧代码复现时首行是 162307（LOF），正是"标题是 ETF、内容是 LOF"。
    check('表格内容确实是 ETF（不是残留的 LOF 行）',
        rows.length > 0 && !rows.every((c) => c.startsWith('16') || c.startsWith('50')),
        `${rows.length} 行，首行 ${rows[0]}`);

    // ══ 场景 2：切回 LOF 同样要立刻生效 ══
    const t1 = Date.now();
    let lofReqAt = null;
    const onReq = (r) => {
        if (FUNDS_RE.test(r.url()) && r.url().includes('filter_mode=lof') && lofReqAt === null) {
            lofReqAt = Date.now() - t1;
        }
    };
    page.on('request', onReq);
    await page.click('#fundTypeSelect');
    await page.click('.ft-option[data-type="lof"]');
    const backNum = await waitPlaceholder((n) => n !== null && n < 1000, RENDER_DEADLINE_MS);
    const backMs = Date.now() - t1;
    page.off('request', onReq);

    check(`切回 LOF：${REQ_DEADLINE_MS}ms 内发出请求`,
        lofReqAt !== null && lofReqAt <= REQ_DEADLINE_MS,
        lofReqAt === null ? '压根没发请求' : `${lofReqAt}ms`);
    check('切回 LOF 数据渲染完成', backNum !== null && backNum < 1000,
        `实际 ${backNum}，耗时 ${backMs}ms`);
} catch (e) {
    console.error('运行出错:', e.message);
    results.push({ name: '执行', ok: false, detail: e.message });
} finally {
    await browser.close();
}

const failed = results.filter((r) => !r.ok);
console.log(`\n结果: ${results.length - failed.length}/${results.length} 通过`);
process.exit(failed.length ? 1 : 0);
