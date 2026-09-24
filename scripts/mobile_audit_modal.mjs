/**
 * 弹窗（基金详情 / 筛选设置）移动端几何审计。
 *
 * 检查点：
 *   1. 弹窗是否贴到视口底部（底部 sheet 留缝会露出后面的列表）
 *   2. 弹窗是否超出视口左右
 *   3. 内部 KPI 网格是否对齐、有无裁剪
 *   4. 内部可点区域是否 < 44px
 *   5. 顶部/底部固定区域是否遮住内容
 *
 * 用法：node scripts/mobile_audit_modal.mjs [baseUrl] [--vp=390]
 */
import { chromium } from 'playwright';

const BASE = (process.argv[2] && !process.argv[2].startsWith('--') ? process.argv[2] : 'http://127.0.0.1:5599') + '/?api=';
const UPSTREAM = 'https://jinkuaicha.com';
const ONLY_VP = (process.argv.find(a => a.startsWith('--vp=')) || '').slice(5).split(',').filter(Boolean);

const VIEWPORTS = [
    { name: '320', width: 320, height: 568 },
    { name: '360', width: 360, height: 740 },
    { name: '390', width: 390, height: 844 },
    { name: '430', width: 430, height: 932 },
].filter(v => !ONLY_VP.length || ONLY_VP.includes(v.name));

const scan = () => {
    const d = el => {
        if (!el) return null;
        const cs = getComputedStyle(el);
        const b = el.getBoundingClientRect();
        return {
            tag: el.tagName.toLowerCase(), id: el.id || null,
            cls: typeof el.className === 'string' ? el.className.trim().split(/\s+/).slice(0, 2).join('.') : null,
            box: [+b.left.toFixed(1), +b.top.toFixed(1), +b.width.toFixed(1), +b.height.toFixed(1)],
            txt: (el.textContent || '').trim().slice(0, 16),
            fs: cs.fontSize, pos: cs.position, bg: cs.backgroundColor,
            ovf: cs.overflow, z: cs.zIndex,
        };
    };
    const vw = document.documentElement.clientWidth, vh = document.documentElement.clientHeight;
    const out = { vw, vh };

    // 注意：position:fixed 的元素 offsetParent 恒为 null，不能用它判可见
    const visible = el => !!el && el.getBoundingClientRect().width > 0 && el.getBoundingClientRect().height > 0;

    const fdm = document.querySelector('.fund-detail-modal');
    if (visible(fdm)) {
        const b = fdm.getBoundingClientRect();
        out.detail = {
            box: d(fdm),
            gapBottom: +(vh - b.bottom).toFixed(1),
            gapTop: +b.top.toFixed(1),
            scrollable: fdm.scrollHeight > fdm.clientHeight,
            scrollH: fdm.scrollHeight, clientH: fdm.clientHeight,
            header: d(document.querySelector('.fd-header')),
            phase1: d(document.querySelector('#fdPhase1')),
            kpiGrid: d(document.querySelector('.fd-kpi-grid')),
            kpis: [...document.querySelectorAll('.fd-kpi-item')].slice(0, 12).map(el => ({
                ...d(el), txt: (el.textContent || '').trim().slice(0, 14),
            })),
            chart: d(document.querySelector('.fd-chart-container')),
            controls: d(document.querySelector('.fd-chart-controls')),
        };
        // KPI 网格是否对齐：按 top 分组
        const rows = {};
        [...document.querySelectorAll('.fd-kpi-item')].forEach(el => {
            const b = el.getBoundingClientRect();
            const k = Math.round(b.top);
            (rows[k] = rows[k] || []).push({ l: +b.left.toFixed(1), r: +b.right.toFixed(1), w: +b.width.toFixed(1), h: +b.height.toFixed(1) });
        });
        out.kpiRows = rows;
    }

    const sm = document.getElementById('settingsModal');
    if (visible(sm)) {
        const inner = sm.querySelector('.modal-content');
        const b = inner.getBoundingClientRect();
        out.settings = {
            overlay: d(sm),
            content: d(inner),
            gapBottom: +(vh - b.bottom).toFixed(1),
            gapTop: +b.top.toFixed(1),
            body: d(sm.querySelector('.modal-body')),
            bodyScrollable: (() => { const e = sm.querySelector('.modal-body'); return e ? e.scrollHeight > e.clientHeight : null; })(),
            footer: d(sm.querySelector('.modal-footer')),
            groups: [...sm.querySelectorAll('.form-group')].map(el => ({ ...d(el), label: (el.querySelector('label') || {}).textContent })),
            unitInputs: [...sm.querySelectorAll('.input-with-unit')].map(d),
        };
    }

    // 可点区域 < 44
    const small = [];
    document.querySelectorAll('#view-data button, #view-data a, #view-data select, #view-data input, .fund-detail-modal button, .fund-detail-modal a, .modal-content button').forEach(el => {
        if (el.offsetParent === null) return;
        const r = el.getBoundingClientRect();
        if (r.width === 0) return;
        if (r.width < 44 || r.height < 44) {
            const cls = typeof el.className === 'string' ? el.className.trim().split(/\s+/).slice(0, 2).join('.') : '';
            small.push(`${el.tagName.toLowerCase()}${el.id ? '#' + el.id : ''}${cls ? '.' + cls : ''} ${r.width.toFixed(1)}x${r.height.toFixed(1)}`);
        }
    });
    out.smallTargets = [...new Set(small)];
    return out;
};

const browser = await chromium.launch();

for (const vp of VIEWPORTS) {
    const ctx = await browser.newContext({ viewport: { width: vp.width, height: vp.height }, deviceScaleFactor: 2, isMobile: true, hasTouch: true, locale: 'zh-CN' });
    const page = await ctx.newPage();
    await page.route('**/api/**', async route => {
        const u = new URL(route.request().url());
        try { await route.fulfill({ response: await route.fetch({ url: UPSTREAM + u.pathname + u.search, timeout: 60000 }) }); }
        catch { await route.abort().catch(() => {}); }
    });
    await ctx.addInitScript(() => { try { sessionStorage.setItem('jkc_welcome_shown', '1'); localStorage.setItem('lof_darkMode', 'light'); } catch (e) {} });

    console.log(`\n${'='.repeat(70)}\n=== ${vp.width}x${vp.height} ===\n${'='.repeat(70)}`);
    await page.goto(BASE + '#/lof', { waitUntil: 'domcontentloaded' });
    await page.waitForFunction(() => document.querySelectorAll('#mobileCardList .mobile-card').length > 0, { timeout: 60000 }).catch(() => {});
    await page.waitForTimeout(800);

    // 详情弹窗
    const card = await page.$('#mobileCardList .mobile-card');
    if (card) {
        await card.click({ timeout: 8000 }).catch(() => {});
        await page.waitForTimeout(4000);
        const m = await page.evaluate(scan);
        if (m.detail) {
            console.log('\n[基金详情弹窗]');
            console.log(`   弹窗 box=${JSON.stringify(m.detail.box.box)}  底部留缝=${m.detail.gapBottom}px  顶部=${m.detail.gapTop}px`);
            console.log(`   可滚动=${m.detail.scrollable} scrollH=${m.detail.scrollH} clientH=${m.detail.clientH}`);
            console.log(`   header=${JSON.stringify(m.detail.header && m.detail.header.box)}`);
            console.log(`   phase1=${JSON.stringify(m.detail.phase1 && m.detail.phase1.box)}`);
            console.log(`   kpiGrid=${JSON.stringify(m.detail.kpiGrid && m.detail.kpiGrid.box)} chart=${JSON.stringify(m.detail.chart && m.detail.chart.box)}`);
            console.log('   KPI 行:');
            Object.entries(m.kpiRows).forEach(([top, items]) => {
                const widths = items.map(i => i.w);
                const same = new Set(widths).size === 1;
                console.log(`      top=${top}  ${items.map(i => `w=${i.w} h=${i.h}`).join('  ')}${same ? '' : '   ⚠ 同排宽度不一致'}`);
            });
            console.log('   KPI 单元:');
            m.detail.kpis.forEach(k => console.log(`      ${JSON.stringify(k.box)} ${k.fs}  "${k.txt}"`));
        }
        console.log('   可点区域 < 44px（含弹窗）:');
        m.smallTargets.forEach(t => console.log('      ' + t));
        await page.evaluate(() => { const b = document.querySelector('.fd-close'); if (b) b.click(); });
        await page.waitForTimeout(600);
    }

    // 设置弹窗
    await page.evaluate(() => { const b = document.getElementById('settingsBtn'); if (b) b.click(); });
    await page.waitForTimeout(900);
    const s = await page.evaluate(scan);
    if (s.settings) {
        console.log('\n[筛选设置弹窗]');
        console.log(`   content box=${JSON.stringify(s.settings.content.box)}  底部留缝=${s.settings.gapBottom}px  顶部=${s.settings.gapTop}px`);
        console.log(`   body=${JSON.stringify(s.settings.body && s.settings.body.box)} 可滚动=${s.settings.bodyScrollable}`);
        console.log(`   footer=${JSON.stringify(s.settings.footer && s.settings.footer.box)}`);
        console.log('   form-group:');
        s.settings.groups.forEach(g => console.log(`      ${JSON.stringify(g.box)} "${g.label}"`));
        console.log('   带单位输入框:');
        s.settings.unitInputs.forEach(u => console.log(`      ${JSON.stringify(u.box)} "${u.txt}"`));
    }
    await ctx.close();
}

await browser.close();
