/**
 * 移动端排版取景台：按真机视口逐屏截图，供视觉检查。
 *
 * 本地起静态服务跑仓库里的 index.html，把 /api/** 用 page.route 转发到线上
 * （https://jinkuaicha.com），这样既有**真实数据**，又能秒级迭代 CSS，
 * 不必为了看一眼排版就部署一次。
 *
 * 用法
 * ----
 *   node scripts/mobile_shot.mjs <outDir> [baseUrl] [--tag=xxx] [--vp=390,360]
 *
 * 视口覆盖主流机型宽度：320（iPhone SE1）/ 360（安卓小屏）/ 390（iPhone 12-15）
 * / 430（iPhone Pro Max）/ 768（iPad 竖屏，正好落在断点外）。
 */
import { chromium } from 'playwright';
import fs from 'node:fs';
import path from 'node:path';

const OUT = process.argv[2] || '_shots';
// `?api=` 不是给后端用的（空值会被 config.js 忽略，请求仍走同源、由下面的
// route 转发），只是为了压掉 index.html 里"本地开发模式"那条黄色提示条 ——
// 那条横幅会盖住页头，不压掉的话每张图顶部都是它，看不出真实排版。
const BASE = (process.argv[3] && !process.argv[3].startsWith('--') ? process.argv[3] : 'http://127.0.0.1:5599') + '/?api=';
const UPSTREAM = process.env.SHOT_UPSTREAM || 'https://jinkuaicha.com';
const TAG = (process.argv.find(a => a.startsWith('--tag=')) || '').slice(6);
const ONLY_VP = (process.argv.find(a => a.startsWith('--vp=')) || '').slice(5).split(',').filter(Boolean);

fs.mkdirSync(OUT, { recursive: true });

const VIEWPORTS = [
    { name: '320', width: 320, height: 568, dpr: 2 },   // iPhone SE (1st)
    { name: '360', width: 360, height: 740, dpr: 3 },   // 安卓主流
    { name: '390', width: 390, height: 844, dpr: 3 },   // iPhone 12/13/14/15
    { name: '430', width: 430, height: 932, dpr: 3 },   // iPhone Pro Max
    { name: '768', width: 768, height: 1024, dpr: 2 },  // iPad 竖屏（断点边界）
    // 桌面视口：只用来确认移动端改动没有波及 PC 布局
    { name: '1024', width: 1024, height: 768, dpr: 1 },
    { name: '1440', width: 1440, height: 900, dpr: 1 },
].filter(v => !ONLY_VP.length || ONLY_VP.includes(v.name));

const browser = await chromium.launch();
const notes = [];

async function newPage(vp) {
    const ctx = await browser.newContext({
        viewport: { width: vp.width, height: vp.height },
        deviceScaleFactor: vp.dpr,
        isMobile: vp.width <= 430,
        hasTouch: vp.width <= 430,
        userAgent: vp.width <= 430
            ? 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1'
            : undefined,
        locale: 'zh-CN',
    });
    const page = await ctx.newPage();

    // 只在跑本地静态服务时转发 API；直接测线上站点时不要多绕一跳
    if (/127\.0\.0\.1|localhost/.test(BASE)) {
        await page.route('**/api/**', async route => {
            const u = new URL(route.request().url());
            try {
                const resp = await route.fetch({ url: UPSTREAM + u.pathname + u.search, timeout: 60000 });
                await route.fulfill({ response: resp });
            } catch (e) {
                if (!/has been closed/.test(e.message)) {
                    notes.push(`API 转发失败 ${u.pathname}${u.search}: ${e.message.split('\n')[0]}`);
                }
                await route.abort().catch(() => {});
            }
        });
    }

    // 跳过欢迎弹窗（本轮只关心数据页排版），并固定主题与筛选，保证每次取得同一画面
    await ctx.addInitScript(() => {
        try {
            sessionStorage.setItem('jkc_welcome_shown', '1');
            localStorage.setItem('lof_darkMode', 'light');
            localStorage.removeItem('lof_threshold');
            localStorage.removeItem('lof_avgThreshold');
            localStorage.removeItem('lof_minAmount');
        } catch (e) {}
    });

    return { ctx, page };
}

/** 等基金列表真正渲染出来 */
async function waitBoard(page, timeout = 60000) {
    const ok = await page.waitForFunction(() => {
        const rows = document.querySelectorAll('#fundTableBody tr.fund-row, #mobileCardList .mobile-card');
        return rows.length > 0;
    }, { timeout }).catch(() => false);
    if (!ok) notes.push('等待基金列表渲染超时');
    await page.waitForTimeout(600);
}

async function shoot(page, vp, state, opts = {}) {
    const file = path.join(OUT, `${TAG ? TAG + '_' : ''}${vp.name}_${state}.png`);
    if (opts.selector) {
        const el = await page.$(opts.selector);
        if (!el) { notes.push(`选择器不存在，跳过 ${state}: ${opts.selector}`); return null; }
        try {
            await el.screenshot({ path: file, animations: 'disabled', timeout: 8000 });
        } catch (e) {
            notes.push(`元素截图失败，跳过 ${state}: ${e.message.split('\n')[0]}`);
            return null;
        }
    } else {
        await page.screenshot({ path: file, fullPage: !!opts.full, animations: 'disabled' });
    }

    // 量横向溢出 + 文字截断 + 溢出父容器的元素
    const m = await page.evaluate(() => {
        const de = document.documentElement;
        const vw = de.clientWidth;
        const clip = [], over = [];
        // 刻意为之、不算缺陷的两种情况，必须先排除，否则真问题会被误报淹掉：
        //   1) text-overflow: ellipsis —— 省略号就是设计本身
        //   2) 视觉小、用 ::after 撑到 44px 的命中区按钮（.mc-fav-btn 等），
        //      伪元素比自身盒子大会让 scrollWidth 虚高
        const bigPseudo = el => {
            for (const p of ['::after', '::before']) {
                const pcs = getComputedStyle(el, p);
                if (!pcs || pcs.content === 'none' || pcs.display === 'none') continue;
                const pw = parseFloat(pcs.width) || 0, ph = parseFloat(pcs.height) || 0;
                if (pcs.position === 'absolute' && (pw > el.clientWidth + 1 || ph > el.clientHeight + 1)) return true;
            }
            return false;
        };
        document.querySelectorAll('body *').forEach(el => {
            const cs = getComputedStyle(el);
            if (cs.display === 'none' || cs.visibility === 'hidden') return;
            const r = el.getBoundingClientRect();
            if (r.width === 0 || r.height === 0) return;
            const tag = el.tagName.toLowerCase();
            const cls = (typeof el.className === 'string' && el.className) ? '.' + el.className.trim().split(/\s+/).slice(0, 2).join('.') : '';
            const id = el.id ? '#' + el.id : '';
            const who = tag + id + cls;
            // 只对叶子元素判断裁剪：容器元素的 scrollWidth 会被子元素或
            // 子元素伪元素带偏，报出来多半是噪声
            const leaf = el.children.length === 0;
            if (!leaf || cs.textOverflow === 'ellipsis' || bigPseudo(el)) return;
            // 文字被裁剪（自身内容比盒子宽/高，且没有滚动条）
            if (el.scrollWidth > el.clientWidth + 1 && cs.overflowX !== 'auto' && cs.overflowX !== 'scroll') {
                clip.push(`${who} 文字超宽 ${el.scrollWidth - el.clientWidth}px`);
            }
            if (el.scrollHeight > el.clientHeight + 1 && cs.overflowY === 'hidden' && el.clientHeight > 0) {
                clip.push(`${who} 文字超高 ${el.scrollHeight - el.clientHeight}px`);
            }
        });

        // 溢出视口的元素：不限叶子（撑开网格列/整页的往往正是容器），
        // 但必须排除被祖先 overflow:hidden|clip 裁掉的 —— 那些元素的
        // getBoundingClientRect 依然报告原尺寸，直接采信会大量误报。
        const clippedByAncestor = el => {
            let c = el.parentElement;
            while (c && c !== document.documentElement) {
                const sx = getComputedStyle(c).overflowX;
                if (sx === 'hidden' || sx === 'clip') return true;
                c = c.parentElement;
            }
            return false;
        };
        document.querySelectorAll('body *').forEach(el => {
            const cs = getComputedStyle(el);
            if (cs.display === 'none' || cs.position === 'fixed') return;
            const r = el.getBoundingClientRect();
            if (r.width === 0 || r.right <= vw + 1) return;
            if (clippedByAncestor(el)) return;
            const tag = el.tagName.toLowerCase();
            const cls = (typeof el.className === 'string' && el.className) ? '.' + el.className.trim().split(/\s+/).slice(0, 2).join('.') : '';
            over.push(`${tag}${el.id ? '#' + el.id : ''}${cls} right=${Math.round(r.right)}>${vw} w=${Math.round(r.width)}`);
        });
        return {
            vw, scrollWidth: de.scrollWidth,
            overflowX: de.scrollWidth - de.clientWidth,
            clip: [...new Set(clip)].slice(0, 14),
            over: [...new Set(over)].slice(0, 14),
        };
    });

    const warn = m.overflowX > 0 ? `  ⚠ 文档横向溢出 ${m.overflowX}px` : '';
    console.log(`  ${path.basename(file)}${warn}`);
    m.clip.forEach(c => console.log(`      ✂ 裁剪: ${c}`));
    m.over.forEach(c => console.log(`      ➡ 越界: ${c}`));
    return m;
}

const report = [];

for (const vp of VIEWPORTS) {
    console.log(`\n=== ${vp.width}x${vp.height} (dpr ${vp.dpr}) ===`);
    const { ctx, page } = await newPage(vp);

    // ── 欢迎弹窗（首次访问，独立捕获）
    {
        const { ctx: c2, page: p2 } = await newPage(vp);
        await p2.addInitScript(() => { try { sessionStorage.removeItem('jkc_welcome_shown'); } catch (e) {} });
        await p2.goto(BASE + '#/', { waitUntil: 'domcontentloaded' });
        await p2.waitForTimeout(1000);
        await shoot(p2, vp, 'welcome');
        await c2.close();
    }

    // ── 首页
    await page.goto(BASE + '#/', { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(1200);
    await shoot(page, vp, 'landing');
    report.push({ vp: vp.name, state: 'landing', ...(await shoot(page, vp, 'landing_full', { full: true })) });

    // ── LOF 板块
    await page.goto(BASE + '#/lof', { waitUntil: 'domcontentloaded' });
    await waitBoard(page);
    report.push({ vp: vp.name, state: 'lof', ...(await shoot(page, vp, 'lof')) });
    await shoot(page, vp, 'lof_toolbar', { selector: '.toolbar' });
    await shoot(page, vp, 'lof_header', { selector: '#view-data .header' });

    // 滚到中段：看列表节奏
    await page.evaluate(() => window.scrollTo(0, 700));
    await page.waitForTimeout(400);
    await shoot(page, vp, 'lof_scroll');

    // 滚到底：看分页条 + 页脚
    await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
    await page.waitForTimeout(400);
    await shoot(page, vp, 'lof_bottom');
    await shoot(page, vp, 'lof_pagination', { selector: '#paginationBar' });
    report.push({ vp: vp.name, state: 'lof_bottom', ...(await shoot(page, vp, 'lof_bottom_full', { full: true })) });
    await shoot(page, vp, 'lof_footer', { selector: '#view-data .footer' });

    // ── 基金详情弹窗
    await shoot(page, vp, 'detail_0_before');
    // 必须挑**可见**的那个：移动卡片在桌面端只是 display:none，元素依然存在，
    // 用 `a || b` 选会拿到隐藏的卡片，点它一直等"元素可见"直到超时。
    let card = await page.$('#mobileCardList .mobile-card');
    if (card && !(await card.isVisible())) card = null;
    if (!card) card = await page.$('#fundTableBody tr.fund-row');
    if (card) {
        try {
            await card.click({ timeout: 8000 });
        } catch (e) {
            notes.push(`点击基金行失败：${e.message.split('\n')[0]}`);
        }
        await page.waitForTimeout(3500);
        await shoot(page, vp, 'detail_top');
        await shoot(page, vp, 'detail_full', { full: true });
        // 滚到详情内部中段
        await page.evaluate(() => {
            const el = document.querySelector('.fund-detail-modal');
            if (el) el.scrollTop = 600;
        });
        await page.waitForTimeout(700);
        await shoot(page, vp, 'detail_scroll');
        await shoot(page, vp, 'detail_scroll_full', { full: true });
        await page.keyboard.press('Escape').catch(() => {});
        await page.evaluate(() => { const b = document.querySelector('.fd-close'); if (b) b.click(); });
        await page.waitForTimeout(500);
    } else {
        notes.push('未找到可点击的基金行/卡片');
    }

    // ── 设置弹窗
    await page.evaluate(() => { const b = document.getElementById('settingsBtn'); if (b) b.click(); });
    await page.waitForTimeout(800);
    await shoot(page, vp, 'settings');
    await shoot(page, vp, 'settings_full', { full: true });
    await page.evaluate(() => { const b = document.getElementById('closeSettingsBtn'); if (b) b.click(); });
    await page.waitForTimeout(400);

    // ── 基金类型下拉
    await page.evaluate(() => { const b = document.getElementById('fundTypeSelect'); if (b) b.click(); });
    await page.waitForTimeout(500);
    await shoot(page, vp, 'typedropdown');

    await ctx.close();

    // ── ETF 板块 + 深色（只跑一次，避免耗时翻倍）
    if (vp.name === '390') {
        const { ctx: c3, page: p3 } = await newPage(vp);
        await p3.goto(BASE + '#/etf', { waitUntil: 'domcontentloaded' });
        await waitBoard(p3);
        await shoot(p3, vp, 'etf');
        await p3.evaluate(() => window.scrollTo(0, 700));
        await p3.waitForTimeout(400);
        await shoot(p3, vp, 'etf_scroll');
        await c3.close();

        const { ctx: c4, page: p4 } = await newPage(vp);
        await p4.addInitScript(() => { try { localStorage.setItem('lof_darkMode', 'dark'); } catch (e) {} });
        await p4.goto(BASE + '#/lof', { waitUntil: 'domcontentloaded' });
        await waitBoard(p4);
        await shoot(p4, vp, 'lof_dark');
        await p4.evaluate(() => window.scrollTo(0, 700));
        await p4.waitForTimeout(400);
        await shoot(p4, vp, 'lof_dark_scroll');
        await c4.close();
    }
}

await browser.close();

console.log('\n=== 横向溢出 / 裁剪汇总 ===');
const bad = report.filter(r => r.overflowX > 0 || r.clip.length || r.over.length);
if (!bad.length) console.log('  无');
bad.forEach(r => {
    console.log(`  ${r.vp}px ${r.state}:` + (r.overflowX > 0 ? ` 文档溢出 +${r.overflowX}px` : ''));
    r.clip.forEach(c => console.log(`      ✂ ${c}`));
    r.over.forEach(c => console.log(`      ➡ ${c}`));
});
if (notes.length) {
    console.log('\n=== 备注 ===');
    [...new Set(notes)].forEach(n => console.log('  ' + n));
}
