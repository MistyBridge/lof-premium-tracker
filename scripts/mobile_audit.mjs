/**
 * 移动端排版几何审计：把"看起来歪"变成可比的数字。
 *
 * 视觉检查能看出"不对劲"，但要说清"左边缘差了几像素、两个按钮宽度差多少、
 * 点击区是否小于 44px"，只能量。本脚本按真机视口打开数据页，量出：
 *   1. 工具栏各控件的位置/尺寸 —— 成对控件是否等宽、是否对齐
 *   2. 卡片内部元素的左/右边缘在**多张卡片之间**是否一致（错位的直接来源）
 *   3. 字号、行高在同类元素间是否统一
 *   4. 可点区域是否达到移动端 44×44 的最小值
 *
 * 用法：node scripts/mobile_audit.mjs [baseUrl] [--vp=390]
 */
import { chromium } from 'playwright';

const BASE = (process.argv[2] && !process.argv[2].startsWith('--') ? process.argv[2] : 'http://127.0.0.1:5599') + '/?api=';
const UPSTREAM = process.env.SHOT_UPSTREAM || 'https://jinkuaicha.com';
const ONLY_VP = (process.argv.find(a => a.startsWith('--vp=')) || '').slice(5).split(',').filter(Boolean);

const VIEWPORTS = [
    { name: '320', width: 320, height: 568, dpr: 2 },
    { name: '360', width: 360, height: 740, dpr: 3 },
    { name: '390', width: 390, height: 844, dpr: 3 },
    { name: '430', width: 430, height: 932, dpr: 3 },
].filter(v => !ONLY_VP.length || ONLY_VP.includes(v.name));

const browser = await chromium.launch();

const MEASURE = () => {
    const r = el => { const b = el.getBoundingClientRect(); return { l: +b.left.toFixed(1), r: +b.right.toFixed(1), t: +b.top.toFixed(1), b: +b.bottom.toFixed(1), w: +b.width.toFixed(1), h: +b.height.toFixed(1) }; };
    const cs = el => getComputedStyle(el);
    const out = {};

    // ── 1. 工具栏
    const tb = document.querySelector('.toolbar');
    if (tb) {
        const parts = {};
        const add = (sel, key) => {
            const el = tb.querySelector(sel);
            if (el && el.offsetParent !== null) {
                const b = r(el);
                parts[key] = { ...b, fs: cs(el).fontSize, txt: (el.textContent || '').trim().slice(0, 14) };
            }
        };
        add('.search-box', 'searchBox');
        add('.fund-type-select', 'typeSelect');
        add('.search-input-wrap', 'searchInput');
        add('#settingsBtn', 'settingsBtn');
        add('#colConfigBtn', 'colConfigBtn');
        add('.mobile-sort-btns', 'sortWrap');
        add('.pagination-info', 'pageInfo');
        add('.market-status', 'marketStatus');
        add('.toolbar-timestamp', 'timestamp');
        const modes = [...tb.querySelectorAll('.btn-sort-mode')].map(el => ({ ...r(el), txt: el.textContent.trim(), fs: cs(el).fontSize }));
        const helps = [...tb.querySelectorAll('.btn-arb-help')].map(el => ({ ...r(el) }));
        const rows = [...tb.querySelectorAll('.sort-btn-row')].map(el => ({ ...r(el) }));
        out.toolbar = {
            box: r(tb),
            parts, modes, helps, rows,
            childCount: tb.children.length,
            // 工具栏自身是否换行成多行
            topValues: [...new Set([...tb.children].filter(e => e.offsetParent !== null).map(e => +e.getBoundingClientRect().top.toFixed(0)))],
        };
    }

    // ── 2. 卡片内部（跨 6 张卡片比较边缘一致性）
    const cards = [...document.querySelectorAll('#mobileCardList .mobile-card')].slice(0, 6);
    out.cards = cards.map(card => {
        const g = sel => { const el = card.querySelector(sel); return el ? r(el) : null; };
        const gfs = sel => { const el = card.querySelector(sel); return el ? cs(el).fontSize : null; };
        return {
            box: r(card),
            code: g('.mc-code'), name: g('.mc-name'), fav: g('.mc-fav-btn'),
            topRow: g('.mc-top-row'), right: g('.mc-right'), premium: g('.mc-premium'),
            profitRow: g('.mc-profit-row'), profitLabel: g('.mc-profit-label'),
            profitVal: g('.mc-profit-val'), profitHelp: g('.mc-profit-help'),
            fs: {
                code: gfs('.mc-code'), name: gfs('.mc-name'), premium: gfs('.mc-premium'),
                profitLabel: gfs('.mc-profit-label'), profitVal: gfs('.mc-profit-val'),
            },
            premiumText: (card.querySelector('.mc-premium') || {}).textContent,
            nameText: (card.querySelector('.mc-name') || {}).textContent,
        };
    });

    // ── 3. 可点区域 < 44px
    const small = [];
    document.querySelectorAll('#view-data button, #view-data a, #view-data select, .mobile-card button').forEach(el => {
        if (el.offsetParent === null) return;
        const b = r(el);
        if (b.w < 44 || b.h < 44) {
            const cls = typeof el.className === 'string' ? el.className.trim().split(/\s+/).slice(0, 2).join('.') : '';
            small.push(`${el.tagName.toLowerCase()}${el.id ? '#' + el.id : ''}${cls ? '.' + cls : ''} ${b.w}x${b.h}`);
        }
    });
    out.smallTargets = [...new Set(small)];

    // ── 4. 分页条
    const pb = document.getElementById('paginationBar');
    if (pb) {
        out.pagination = {
            box: r(pb),
            children: [...pb.children].filter(e => e.offsetParent !== null).map(e => ({
                tag: e.tagName.toLowerCase() + (e.id ? '#' + e.id : '') + (typeof e.className === 'string' && e.className ? '.' + e.className.trim().split(/\s+/)[0] : ''),
                ...r(e), txt: (e.textContent || '').trim().slice(0, 10),
            })),
        };
    }

    // ── 5. 页头
    const hd = document.querySelector('#view-data .header');
    if (hd) {
        out.header = {
            box: r(hd),
            brand: hd.querySelector('.header-brand') ? r(hd.querySelector('.header-brand')) : null,
            info: hd.querySelector('.header-info') ? r(hd.querySelector('.header-info')) : null,
            children: [...hd.querySelectorAll('.header-info > *')].filter(e => e.offsetParent !== null).map(e => ({
                tag: e.tagName.toLowerCase() + (e.id ? '#' + e.id : '') + (typeof e.className === 'string' && e.className ? '.' + e.className.trim().split(/\s+/)[0] : ''),
                ...r(e), txt: (e.textContent || '').trim().slice(0, 10),
            })),
        };
    }

    // ── 6. SPA 导航
    const nav = document.getElementById('spaNav');
    if (nav) {
        out.spaNav = {
            box: r(nav),
            children: [...nav.querySelectorAll(':scope > *')].filter(e => e.offsetParent !== null).map(e => ({
                tag: e.tagName.toLowerCase() + (typeof e.className === 'string' && e.className ? '.' + e.className.trim().split(/\s+/)[0] : ''),
                ...r(e), txt: (e.textContent || '').trim().slice(0, 10),
            })),
        };
    }

    out.doc = { scrollW: document.documentElement.scrollWidth, clientW: document.documentElement.clientWidth };
    return out;
};

for (const vp of VIEWPORTS) {
    const ctx = await browser.newContext({
        viewport: { width: vp.width, height: vp.height }, deviceScaleFactor: 1,
        isMobile: true, hasTouch: true, locale: 'zh-CN',
    });
    const page = await ctx.newPage();
    await page.route('**/api/**', async route => {
        const u = new URL(route.request().url());
        try { await route.fulfill({ response: await route.fetch({ url: UPSTREAM + u.pathname + u.search, timeout: 60000 }) }); }
        catch { await route.abort().catch(() => {}); }
    });
    await ctx.addInitScript(() => { try { sessionStorage.setItem('jkc_welcome_shown', '1'); localStorage.setItem('lof_darkMode', 'light'); } catch (e) {} });

    console.log(`\n${'='.repeat(72)}\n=== ${vp.width}x${vp.height} ===\n${'='.repeat(72)}`);
    await page.goto(BASE + '#/lof', { waitUntil: 'domcontentloaded' });
    await page.waitForFunction(() => document.querySelectorAll('#mobileCardList .mobile-card').length > 0, { timeout: 60000 }).catch(() => {});
    await page.waitForTimeout(800);

    const m = await page.evaluate(MEASURE);

    console.log(`\n[文档] 宽 ${m.doc.clientW}  scrollWidth ${m.doc.scrollW}` + (m.doc.scrollW > m.doc.clientW ? `  ⚠ 横向溢出 ${m.doc.scrollW - m.doc.clientW}px` : ''));

    if (m.header) {
        console.log('\n[页头]', JSON.stringify(m.header.box));
        m.header.children.forEach(c => console.log(`   ${c.tag.padEnd(28)} l=${String(c.l).padStart(6)} r=${String(c.r).padStart(6)} w=${String(c.w).padStart(6)} h=${String(c.h).padStart(5)}  ${c.txt}`));
    }

    if (m.spaNav) {
        console.log('\n[SPA 导航]', JSON.stringify(m.spaNav.box));
        m.spaNav.children.forEach(c => console.log(`   ${c.tag.padEnd(28)} l=${String(c.l).padStart(6)} r=${String(c.r).padStart(6)} w=${String(c.w).padStart(6)} h=${String(c.h).padStart(5)}  ${c.txt}`));
    }

    if (m.toolbar) {
        console.log(`\n[工具栏] box=${JSON.stringify(m.toolbar.box)}  直接子元素行数=${m.toolbar.topValues.length} (top: ${m.toolbar.topValues.join(', ')})`);
        Object.entries(m.toolbar.parts).forEach(([k, v]) => {
            console.log(`   ${k.padEnd(14)} l=${String(v.l).padStart(6)} r=${String(v.r).padStart(6)} w=${String(v.w).padStart(6)} h=${String(v.h).padStart(5)} fs=${v.fs.padStart(7)}  ${v.txt}`);
        });
        console.log('   排序按钮:');
        m.toolbar.modes.forEach(v => console.log(`      ${v.txt.padEnd(10)} l=${String(v.l).padStart(6)} r=${String(v.r).padStart(6)} w=${String(v.w).padStart(6)} h=${String(v.h).padStart(5)} fs=${v.fs}`));
        console.log('   帮助按钮: ' + m.toolbar.helps.map(v => `${v.w}x${v.h}@l${v.l}`).join('  '));
        console.log('   排序行:   ' + m.toolbar.rows.map(v => `l=${v.l} r=${v.r} w=${v.w}`).join('  |  '));
        // 成对控件等宽判断
        if (m.toolbar.modes.length === 2) {
            const dw = Math.abs(m.toolbar.modes[0].w - m.toolbar.modes[1].w);
            const dl = Math.abs(m.toolbar.modes[0].l - m.toolbar.modes[1].l);
            console.log(`   ⚖ 两个模式按钮宽度差 ${dw.toFixed(1)}px${dw > 1 ? '  ⚠ 不等宽' : ''}`);
        }
    }

    console.log('\n[卡片内部]（前 6 张，看跨卡片的边缘是否一致）');
    const keys = ['code', 'name', 'fav', 'premium', 'profitLabel', 'profitVal', 'profitHelp'];
    console.log('   ' + 'card'.padEnd(6) + keys.map(k => k.padStart(11)).join('') + '   卡片高');
    m.cards.forEach((c, i) => {
        console.log('   #' + String(i).padEnd(5) + keys.map(k => String(c[k] ? c[k].l : '-').padStart(11)).join('') + `   ${c.box.h}`);
    });
    // 边缘方差
    keys.forEach(k => {
        const ls = m.cards.map(c => c[k] && c[k].l).filter(v => typeof v === 'number');
        if (ls.length > 1) {
            const range = Math.max(...ls) - Math.min(...ls);
            if (range > 0.5) console.log(`   ⚠ ${k} 左边缘跨卡片浮动 ${range.toFixed(1)}px  (${ls.join(', ')})`);
        }
    });
    keys.forEach(k => {
        const rs = m.cards.map(c => c[k] && c[k].r).filter(v => typeof v === 'number');
        if (rs.length > 1) {
            const range = Math.max(...rs) - Math.min(...rs);
            if (range > 0.5) console.log(`   ⚠ ${k} 右边缘跨卡片浮动 ${range.toFixed(1)}px  (${rs.join(', ')})`);
        }
    });
    // 字号一致性
    ['code', 'name', 'premium', 'profitLabel', 'profitVal'].forEach(k => {
        const fs = m.cards.map(c => c.fs[k]).filter(Boolean);
        const uniq = [...new Set(fs)];
        if (uniq.length > 1) console.log(`   ⚠ 字号 ${k} 不统一: ${uniq.join(', ')}`);
    });
    // 卡片高度
    const hs = m.cards.map(c => c.box.h);
    if (hs.length > 1) {
        const range = Math.max(...hs) - Math.min(...hs);
        console.log(`   卡片高度 ${hs.join(', ')}` + (range > 1 ? `  ⚠ 相差 ${range.toFixed(1)}px` : '  ✔ 一致'));
    }
    // 溢价文本的左右边缘
    console.log('   溢价文本:');
    m.cards.forEach((c, i) => console.log(`      #${i} "${c.premiumText}"  l=${c.premium && c.premium.l} r=${c.premium && c.premium.r}`));
    console.log('   名称文本:');
    m.cards.forEach((c, i) => console.log(`      #${i} "${c.nameText}"  name.l=${c.name && c.name.l} r=${c.name && c.name.r} fav.l=${c.fav && c.fav.l}`));

    if (m.pagination) {
        console.log(`\n[分页条] box=${JSON.stringify(m.pagination.box)}`);
        m.pagination.children.forEach(c => console.log(`   ${c.tag.padEnd(24)} l=${String(c.l).padStart(6)} r=${String(c.r).padStart(6)} w=${String(c.w).padStart(6)} h=${String(c.h).padStart(5)}  ${c.txt}`));
    }

    console.log('\n[可点区域 < 44px]');
    m.smallTargets.forEach(t => console.log('   ' + t));

    await ctx.close();
}

await browser.close();
