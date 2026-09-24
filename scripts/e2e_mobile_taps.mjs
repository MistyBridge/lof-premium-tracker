/**
 * 移动端可点区域回归测试。
 *
 * 背景
 * ----
 * 卡片上的收藏星标（视觉 16.5×15.2px）和"千元可赚"问号（18×18px）远小于
 * 移动端 44px 的可点下限，但直接把它们做大又会顶高行。做法是保留视觉尺寸，
 * 用 ::after 伪元素把可点区域撑到 44×44。
 *
 * 伪元素不参与布局，所以"算术上应该是 44px"并不等于"真的能点到"。
 * 本测试就在**视觉盒子之外、命中区之内**的位置真点一下：
 *   1. 星标：点它应切换收藏，且**不能**弹出基金详情
 *   2. 问号：点它应弹出收益构成，且**不能**弹出基金详情
 *   3. 顺带确认视觉盒子没被撑大（否则等于没做布局隔离）
 *
 * 用法：node scripts/e2e_mobile_taps.mjs [baseUrl]
 */
import { chromium } from 'playwright';

const BASE = (process.argv[2] && !process.argv[2].startsWith('--') ? process.argv[2] : 'https://jinkuaicha.com') + '/?api=';
const UPSTREAM = process.env.SHOT_UPSTREAM || 'https://jinkuaicha.com';
const LOCAL = /127\.0\.0\.1|localhost/.test(BASE);
const W = 390, H = 844;

const results = [];
function check(name, ok, detail) {
    results.push({ name, ok });
    console.log(`  ${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? '  — ' + detail : ''}`);
}

const browser = await chromium.launch();
const ctx = await browser.newContext({
    viewport: { width: W, height: H }, deviceScaleFactor: 3, isMobile: true, hasTouch: true, locale: 'zh-CN',
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
        localStorage.removeItem('lof_favorites');
        localStorage.setItem('lof_darkMode', 'light');
    } catch (e) {}
});

await page.goto(BASE + '#/lof', { waitUntil: 'domcontentloaded' });
await page.waitForFunction(() => document.querySelectorAll('#mobileCardList .mobile-card').length > 0, { timeout: 60000 });
await page.waitForTimeout(2500);   // 等 soft-toast 退场，避免挡住点击

const detailOpen = () => page.evaluate(() => {
    const el = document.querySelector('.fund-detail-overlay');
    return !!el && getComputedStyle(el).display !== 'none' && el.getBoundingClientRect().height > 0;
});
const popoverOpen = () => page.evaluate(() => {
    const el = document.querySelector('.profit-popover-overlay');
    return !!el && el.getBoundingClientRect().height > 0;
});

// ── 1. 星标：在视觉盒子之外、命中区之内点击
{
    const star = page.locator('#mobileCardList .mobile-card').first().locator('.mc-fav-btn');
    const box = await star.boundingBox();
    check('星标视觉尺寸仍然很小（未被撑大而顶高行）',
        box.width < 24 && box.height < 24,
        `${box.width.toFixed(1)}×${box.height.toFixed(1)}px`);

    // 命中区中心向左 18px：已在 16.5px 宽的视觉盒子之外，仍在 44px 命中区之内
    const cx = box.x + box.width / 2 - 18;
    const cy = box.y + box.height / 2;
    const before = await star.textContent();
    await page.mouse.click(cx, cy);
    await page.waitForTimeout(500);
    const after = await star.textContent();
    check('点星标命中区边缘（视觉盒子之外）能切换收藏',
        before.trim() !== after.trim(),
        `${before.trim()} → ${after.trim()}`);
    check('点星标不会误开基金详情', !(await detailOpen()));

    // 复原
    await page.mouse.click(cx, cy);
    await page.waitForTimeout(400);
}

// ── 2. 问号：同样在视觉盒子之外点击
{
    const help = page.locator('#mobileCardList .mobile-card').first().locator('.mc-profit-help');
    const box = await help.boundingBox();
    check('问号视觉尺寸仍然很小',
        box.width < 24 && box.height < 24,
        `${box.width.toFixed(1)}×${box.height.toFixed(1)}px`);

    const cx = box.x + box.width / 2;
    const cy = box.y + box.height / 2 - 18;   // 视觉盒子正上方 18px，仍在 44px 命中区里
    await page.mouse.click(cx, cy);
    await page.waitForTimeout(700);
    check('点问号命中区边缘（视觉盒子之外）能弹出收益构成', await popoverOpen());
    check('点问号不会误开基金详情', !(await detailOpen()));

    // 关闭弹出层
    await page.evaluate(() => {
        const b = document.querySelector('.profit-popover-close') || document.querySelector('.profit-popover-overlay');
        if (b) b.click();
    });
    await page.waitForTimeout(400);
}

// ── 3. 卡片空白处仍应打开详情（确认没有因为扩大命中区而挡住整卡点击）
{
    const card = page.locator('#mobileCardList .mobile-card').first();
    const box = await card.boundingBox();
    await page.mouse.click(box.x + box.width / 2, box.y + box.height - 8);
    await page.waitForTimeout(3000);
    check('点卡片空白处仍能打开基金详情', await detailOpen());
}

await browser.close();

const failed = results.filter(r => !r.ok);
console.log(`\n${results.length - failed.length}/${results.length} 通过`);
process.exit(failed.length ? 1 : 0);
