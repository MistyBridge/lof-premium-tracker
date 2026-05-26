const fs = require('fs');
const { Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
        Header, Footer, AlignmentType, HeadingLevel, BorderStyle, WidthType,
        ShadingType, PageNumber, PageBreak, TableOfContents, LevelFormat } = require('docx');

const B = { style: BorderStyle.SINGLE, size: 1, color: 'CCCCCC' };
const borders = { top: B, bottom: B, left: B, right: B };
const cellMargins = { top: 60, bottom: 60, left: 100, right: 100 };
const headerBg = { fill: '1A2740', type: ShadingType.CLEAR };
const altBg = { fill: 'F6F8FB', type: ShadingType.CLEAR };

function hdrCell(text, width, bg) {
    return new TableCell({ borders, width: { size: width, type: WidthType.DXA }, shading: bg || headerBg, margins: cellMargins,
        children: [new Paragraph({ children: [new TextRun({ text, bold: true, color: bg ? '000000' : 'FFFFFF', font: 'Arial', size: 20 })] })] });
}
function cell(text, width, bg) {
    return new TableCell({ borders, width: { size: width, type: WidthType.DXA }, shading: bg || undefined, margins: cellMargins,
        children: [new Paragraph({ children: [new TextRun({ text, font: 'Arial', size: 20 })] })] });
}
function p(text) {
    return new Paragraph({ spacing: { after: 120 }, children: [new TextRun({ text, font: 'Arial', size: 22 })] });
}
function boldP(text) {
    return new Paragraph({ spacing: { after: 120 }, children: [new TextRun({ text, font: 'Arial', size: 22, bold: true })] });
}
function codeP(text) {
    return new Paragraph({ spacing: { after: 60 }, shading: { fill: 'F4F6F8', type: ShadingType.CLEAR },
        children: [new TextRun({ text, font: 'Courier New', size: 18 })] });
}
function h1(text) { return new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun({ text, font: 'Arial', size: 36, bold: true, color: '1A2740' })] }); }
function h2(text) { return new Paragraph({ heading: HeadingLevel.HEADING_2, children: [new TextRun({ text, font: 'Arial', size: 28, bold: true, color: '2C5F8A' })] }); }
function h3(text) { return new Paragraph({ heading: HeadingLevel.HEADING_3, children: [new TextRun({ text, font: 'Arial', size: 24, bold: true })] }); }
function bullet(text) { return new Paragraph({ numbering: { reference: 'bullets', level: 0 }, spacing: { after: 60 }, children: [new TextRun({ text, font: 'Arial', size: 22 })] }); }

const children = [];

// ====== TITLE PAGE ======
children.push(new Paragraph({ spacing: { before: 3000, after: 200 }, alignment: AlignmentType.CENTER,
    children: [new TextRun({ text: '金快查', font: 'Arial', size: 56, bold: true, color: '1A2740' })] }));
children.push(new Paragraph({ spacing: { after: 100 }, alignment: AlignmentType.CENTER,
    children: [new TextRun({ text: '全市场 LOF 基金实时折溢价监控系统', font: 'Arial', size: 32, color: '2C5F8A' })] }));
children.push(new Paragraph({ spacing: { after: 100 }, alignment: AlignmentType.CENTER,
    children: [new TextRun({ text: '技术架构文档 v1.2.0', font: 'Arial', size: 26, color: '666666' })] }));
children.push(new Paragraph({ spacing: { after: 2000 }, alignment: AlignmentType.CENTER,
    children: [new TextRun({ text: '2026-05-18 | MistyBridge', font: 'Arial', size: 22, color: '999999' })] }));
children.push(new Paragraph({ children: [new PageBreak()] }));

// ====== TOC ======
children.push(h1('目录'));
children.push(new TableOfContents('目录', { hyperlink: true, headingStyleRange: '1-3' }));
children.push(new Paragraph({ children: [new PageBreak()] }));

// ====== 一、项目概述 ======
children.push(h1('一、项目概述'));
children.push(p('金快查是一个 LOF（Listed Open-end Fund，上市型开放式基金）全市场实时折溢价监控系统，覆盖深沪两市全部 LOF 基金（~540 只），提供 Web 端响应式访问，帮助投资者发现套利机会。'));
children.push(boldP('生产地址'));
children.push(bullet('前端：jinkuaicha.com'));
children.push(bullet('后端：lof-premium-tracker-production.up.railway.app'));
children.push(bullet('版本：v1.2.0 | 日线数据：91,697 行 | 净值覆盖率：100%'));

// ====== 二、前端架构 ======
children.push(h1('二、前端架构'));
children.push(h2('2.1 技术栈'));
children.push(new Table({ width: { size: 9026, type: WidthType.DXA }, columnWidths: [3000, 6026],
    rows: [
        new TableRow({ children: [hdrCell('层级', 3000), hdrCell('技术', 6026)] }),
        new TableRow({ children: [cell('部署', 3000), cell('Cloudflare Pages + Functions', 6026)] }),
        new TableRow({ children: [cell('框架', 3000, altBg), cell('原生 HTML5 / CSS3 / ES6（零依赖 SPA）', 6026, altBg)] }),
        new TableRow({ children: [cell('图表', 3000), cell('Chart.js 4.4（CDN加载，详情弹窗按需使用）', 6026)] }),
        new TableRow({ children: [cell('样式', 3000, altBg), cell('CSS 自定义属性 + 媒体查询响应式', 6026, altBg)] }),
        new TableRow({ children: [cell('网络', 3000), cell('fetch() + 自定义重试逻辑', 6026)] }),
    ] }));

children.push(h2('2.2 文件结构'));
children.push(codeP('/'));
children.push(codeP('├── index.html              # 单页入口'));
children.push(codeP('├── js/'));
children.push(codeP('│   ├── config.js           # 环境配置'));
children.push(codeP('│   ├── api.js              # 网络层（重试/超时）'));
children.push(codeP('│   └── app.js              # 业务逻辑（1498行）'));
children.push(codeP('├── css/style.css           # 全局样式 + 暗色模式'));
children.push(codeP('├── pages/                  # 协议/隐私页面'));
children.push(codeP('└── functions/              # CF Functions 代理'));
children.push(new Paragraph({ spacing: { after: 100 }, children: [] }));

children.push(h2('2.3 核心模块：app.js'));
children.push(p('类 LofFundMonitor，全局单例 lofMonitor，挂载 window。'));
children.push(new Table({ width: { size: 9026, type: WidthType.DXA }, columnWidths: [2200, 3000, 3826],
    rows: [
        new TableRow({ children: [hdrCell('功能', 2200), hdrCell('方法', 3000), hdrCell('说明', 3826)] }),
        new TableRow({ children: [cell('初始化', 2200), cell('init()', 3000), cell('健康检查→加载排行→加载全量基金', 3826)] }),
        new TableRow({ children: [cell('渲染表格', 2200, altBg), cell('renderTable()', 3000, altBg), cell('PC端<tr>行 + 移动端卡片', 3826, altBg)] }),
        new TableRow({ children: [cell('预计收益', 2200), cell('calcEstimatedProfit()', 3000), cell('含费率明细（申购/赎回/佣金）', 3826)] }),
        new TableRow({ children: [cell('详情弹窗', 2200, altBg), cell('showFundDetail()', 3000, altBg), cell('12项KPI + Chart.js双线图', 3826, altBg)] }),
        new TableRow({ children: [cell('暗色模式', 2200), cell('toggleDarkMode()', 3000), cell('CSS变量切换 + localStorage', 3826)] }),
        new TableRow({ children: [cell('事件委托', 2200, altBg), cell('document click', 3000, altBg), cell('.fund-row/.mobile-card → 详情弹窗等', 3826, altBg)] }),
    ] }));

// ====== 三、后端架构 ======
children.push(new Paragraph({ children: [new PageBreak()] }));
children.push(h1('三、后端架构'));
children.push(h2('3.1 技术栈'));
children.push(new Table({ width: { size: 9026, type: WidthType.DXA }, columnWidths: [2200, 6826],
    rows: [
        new TableRow({ children: [hdrCell('层级', 2200), hdrCell('技术', 6826)] }),
        new TableRow({ children: [cell('部署', 2200), cell('Railway（RAILPACK 自动构建）', 6826)] }),
        new TableRow({ children: [cell('框架', 2200, altBg), cell('Flask 2.3 + Gunicorn', 6826, altBg)] }),
        new TableRow({ children: [cell('数据库', 2200), cell('PostgreSQL（三表：funds + premium_snapshots + daily_kline）', 6826)] }),
        new TableRow({ children: [cell('数据源', 2200, altBg), cell('15个API源，K线8级串行降级，熔断保护', 6826, altBg)] }),
        new TableRow({ children: [cell('并发', 2200), cell('threading线程池 + TaskQueue(4) + Semaphore(15)', 6826)] }),
        new TableRow({ children: [cell('缓存', 2200, altBg), cell('内存dict + threading.RLock读写锁', 6826, altBg)] }),
    ] }));

children.push(h2('3.2 数据抓取架构'));
children.push(p('fetch_all() 每5分钟触发，6步流水线：'));
children.push(codeP('Step 1: 价格行情 (AkShare → Legacy 整体降级)'));
children.push(codeP('Step 2: NAV净值 (AkShare → Legacy 逐基金降级)'));
children.push(codeP('Step 3: 溢价率计算 premium_rate=(price-nav)/nav*100'));
children.push(codeP('Step 4: 申购状态 (lsjz API, 15并发)'));
children.push(codeP('Step 5: 费率数据 (缓存优先，80%命中率跳过爬虫)'));
children.push(codeP('Step 6: save_snapshot() → PostgreSQL (触发器拦截周末)'));
children.push(new Paragraph({ spacing: { after: 100 }, children: [] }));

children.push(h2('3.3 全部数据源（15个）'));
children.push(new Table({ width: { size: 9026, type: WidthType.DXA }, columnWidths: [500, 1400, 3526, 1200, 2400],
    rows: [
        new TableRow({ children: [hdrCell('#', 500), hdrCell('类别', 1400), hdrCell('数据源/API端点', 3526), hdrCell('优先级', 1200), hdrCell('用途', 2400)] }),
        new TableRow({ children: [cell('1', 500), cell('行情', 1400), cell('AkShare fund_lof_spot_em()', 3526), cell('主', 1200), cell('全市场实时行情', 2400)] }),
        new TableRow({ children: [cell('2', 500, altBg), cell('行情', 1400, altBg), cell('东方财富 push2delay', 3526, altBg), cell('备', 1200, altBg), cell('沪市LOF行情', 2400, altBg)] }),
        new TableRow({ children: [cell('3', 500), cell('行情', 1400), cell('腾讯 QT qt.gtimg.cn', 3526), cell('备', 1200), cell('深市LOF行情', 2400)] }),
        new TableRow({ children: [cell('4', 500, altBg), cell('K线(1)', 1400, altBg), cell('东方财富 push2his', 3526, altBg), cell('1st', 1200, altBg), cell('日K线OHLC+成交额', 2400, altBg)] }),
        new TableRow({ children: [cell('5', 500), cell('K线(2)', 1400), cell('新浪财经 money.finance.sina.com.cn', 3526), cell('2nd', 1200), cell('240日历史', 2400)] }),
        new TableRow({ children: [cell('6', 500, altBg), cell('K线(3)', 1400, altBg), cell('网易财经 img1.money.126.net', 3526, altBg), cell('3rd', 1200, altBg), cell('按年分文件', 2400, altBg)] }),
        new TableRow({ children: [cell('7', 500), cell('K线(4)', 1400), cell('腾讯QT K线 web.ifzq.gtimg.cn', 3526), cell('4th', 1200), cell('前复权日K线', 2400)] }),
        new TableRow({ children: [cell('8', 500, altBg), cell('K线(5)', 1400, altBg), cell('Baostock Python库', 3526, altBg), cell('5th', 1200, altBg), cell('需bs.login()', 2400, altBg)] }),
        new TableRow({ children: [cell('9', 500), cell('K线(6)', 1400), cell('OpenBB / Yahoo', 3526), cell('6th', 1200), cell('海外备源', 2400)] }),
        new TableRow({ children: [cell('10', 500, altBg), cell('K线(7)', 1400, altBg), cell('TuShare Python库', 3526, altBg), cell('7th', 1200, altBg), cell('需token', 2400, altBg)] }),
        new TableRow({ children: [cell('11', 500), cell('K线(8)', 1400), cell('AkShare fund_lof_hist_em()', 3526), cell('8th', 1200), cell('全量兜底', 2400)] }),
        new TableRow({ children: [cell('12', 500, altBg), cell('净值', 1400, altBg), cell('天天基金 fundgz', 3526, altBg), cell('主', 1200, altBg), cell('盘中估算+盘后正式', 2400, altBg)] }),
        new TableRow({ children: [cell('13', 500), cell('净值', 1400), cell('东方财富 lsjz (分页)', 3526), cell('备', 1200), cell('历史净值补缺', 2400)] }),
        new TableRow({ children: [cell('14', 500, altBg), cell('费率', 1400, altBg), cell('东方财富 fundf10', 3526, altBg), cell('—', 1200, altBg), cell('申赎费率+限额', 2400, altBg)] }),
        new TableRow({ children: [cell('15', 500), cell('代码', 1400), cell('push2delay + sz_lof_codes.json', 3526), cell('—', 1200), cell('基金代码库', 2400)] }),
    ] }));

// ====== 数据库 ======
children.push(new Paragraph({ children: [new PageBreak()] }));
children.push(h2('3.4 PostgreSQL 数据库'));
children.push(p('三表设计，联合主键(date, code)，幂等upsert，365天滚动保留。'));
children.push(p('数据量：funds 538行 / premium_snapshots 周期性 / daily_kline 91,697行'));
children.push(new Paragraph({ spacing: { after: 60 }, children: [] }));

children.push(h3('funds（基金参考表）'));
children.push(new Table({ width: { size: 9026, type: WidthType.DXA }, columnWidths: [2200, 2200, 4626],
    rows: [
        new TableRow({ children: [hdrCell('列', 2200), hdrCell('类型', 2200), hdrCell('说明', 4626)] }),
        new TableRow({ children: [cell('code', 2200), cell('VARCHAR(6) PK', 2200), cell('基金代码', 4626)] }),
        new TableRow({ children: [cell('name', 2200, altBg), cell('VARCHAR(100)', 2200, altBg), cell('基金名称', 4626, altBg)] }),
    ] }));
children.push(new Paragraph({ spacing: { after: 60 }, children: [] }));

children.push(h3('premium_snapshots（实时快照）'));
children.push(new Table({ width: { size: 9026, type: WidthType.DXA }, columnWidths: [2200, 2200, 4626],
    rows: [
        new TableRow({ children: [hdrCell('列', 2200), hdrCell('类型', 2200), hdrCell('说明', 4626)] }),
        new TableRow({ children: [cell('date', 2200), cell('DATE PK', 2200), cell('快照日期', 4626)] }),
        new TableRow({ children: [cell('code', 2200, altBg), cell('VARCHAR(6) PK', 2200, altBg), cell('基金代码', 4626, altBg)] }),
        new TableRow({ children: [cell('premium_rate', 2200), cell('NUMERIC(10,4)', 2200), cell('溢价率 %', 4626)] }),
        new TableRow({ children: [cell('price / nav', 2200, altBg), cell('NUMERIC(12,4)', 2200, altBg), cell('场内价格 / 场外净值', 4626, altBg)] }),
        new TableRow({ children: [cell('amount', 2200), cell('NUMERIC(16,2)', 2200), cell('成交额', 4626)] }),
    ] }));
children.push(new Paragraph({ spacing: { after: 60 }, children: [] }));

children.push(h3('daily_kline（日线数据，365天保留）'));
children.push(new Table({ width: { size: 9026, type: WidthType.DXA }, columnWidths: [2200, 2200, 4626],
    rows: [
        new TableRow({ children: [hdrCell('列', 2200), hdrCell('类型', 2200), hdrCell('说明', 4626)] }),
        new TableRow({ children: [cell('date', 2200), cell('DATE PK', 2200), cell('日期', 4626)] }),
        new TableRow({ children: [cell('code', 2200, altBg), cell('VARCHAR(6) PK', 2200, altBg), cell('基金代码', 4626, altBg)] }),
        new TableRow({ children: [cell('price / nav', 2200), cell('NUMERIC(12,4)', 2200), cell('场内收盘价 / 场外净值', 4626)] }),
        new TableRow({ children: [cell('amount', 2200, altBg), cell('NUMERIC(16,2)', 2200, altBg), cell('成交额（元）', 4626, altBg)] }),
        new TableRow({ children: [cell('change_pct', 2200), cell('NUMERIC(10,4)', 2200), cell('涨跌幅 %', 4626)] }),
        new TableRow({ children: [cell('premium_rate', 2200, altBg), cell('NUMERIC(10,4)', 2200, altBg), cell('溢价率 %', 4626, altBg)] }),
    ] }));
children.push(new Paragraph({ spacing: { after: 60 }, children: [] }));

children.push(boldP('周末防护'));
children.push(codeP('CREATE FUNCTION prevent_weekend_snapshot()'));
children.push(codeP('RETURNS TRIGGER AS $$'));
children.push(codeP('BEGIN'));
children.push(codeP('  IF EXTRACT(DOW FROM NEW.date) IN (0, 6) THEN RETURN NULL;'));
children.push(codeP('  END IF; RETURN NEW;'));
children.push(codeP('END; $$ LANGUAGE plpgsql;'));
children.push(new Paragraph({ spacing: { after: 100 }, children: [] }));

// ====== 线程池 ======
children.push(new Paragraph({ children: [new PageBreak()] }));
children.push(h2('3.5 线程池设计'));
children.push(h3('3.5.1 TaskQueue — 后台任务调度'));
children.push(p('全局单例，max_workers=4，负责K线回填、净值回填等耗时任务。'));
children.push(new Table({ width: { size: 9026, type: WidthType.DXA }, columnWidths: [2500, 6526],
    rows: [
        new TableRow({ children: [hdrCell('特性', 2500), hdrCell('实现', 6526)] }),
        new TableRow({ children: [cell('同类型去重', 2500), cell('submit("nav_backfill")再次调用返回已有Task，不重复执行', 6526)] }),
        new TableRow({ children: [cell('排队唤醒', 2500, altBg), cell('任务完成后 _process_pending() 自动取下一个', 6526, altBg)] }),
        new TableRow({ children: [cell('状态查询', 2500), cell('GET /api/tasks 返回运行中/排队中任务列表', 6526)] }),
        new TableRow({ children: [cell('自动清理', 2500, altBg), cell('cleanup_old(3600) 每小时清理已完成/失败记录', 6526, altBg)] }),
        new TableRow({ children: [cell('任务类型', 2500), cell('kline_backfill / nav_backfill', 6526)] }),
    ] }));
children.push(codeP('submit() → 同类型已运行?返回 | 有空闲?启动 | 否则→排队'));
children.push(new Paragraph({ spacing: { after: 100 }, children: [] }));

children.push(h3('3.5.2 数据抓取 — 阶段内并发'));
children.push(new Table({ width: { size: 9026, type: WidthType.DXA }, columnWidths: [2000, 3526, 3500],
    rows: [
        new TableRow({ children: [hdrCell('阶段', 2000), hdrCell('并发模型', 3526), hdrCell('参数', 3500)] }),
        new TableRow({ children: [cell('价格行情', 2000), cell('datasource manager 主备切换', 3526), cell('单次调用', 3500)] }),
        new TableRow({ children: [cell('NAV净值', 2000, altBg), cell('datasource manager 逐基金降级', 3526, altBg), cell('内部并发', 3500, altBg)] }),
        new TableRow({ children: [cell('申购状态', 2000), cell('threading.Thread 分批', 3526), cell('Semaphore(15), 50只/批', 3500)] }),
        new TableRow({ children: [cell('费率爬虫', 2000, altBg), cell('fee_fetcher.fetch_fees_batch()', 3526, altBg), cell('concurrency=10', 3500, altBg)] }),
    ] }));
children.push(new Paragraph({ spacing: { after: 100 }, children: [] }));

children.push(h3('3.5.3 K线历史回填'));
children.push(codeP('WORKERS=3, code_queue=Queue()'));
children.push(codeP('def worker(): code=get_nowait() → fetch(9源降级) → INSERT ON CONFLICT'));
children.push(p('3个worker共享Queue，抢占基金代码，流式即时写入，不积攒内存。'));
children.push(new Paragraph({ spacing: { after: 100 }, children: [] }));

children.push(h3('3.5.4 Gunicorn 进程模型'));
children.push(codeP('gunicorn --workers 1 --threads 4 --timeout 120'));
children.push(new Table({ width: { size: 9026, type: WidthType.DXA }, columnWidths: [3500, 1500, 4026],
    rows: [
        new TableRow({ children: [hdrCell('层级', 3500), hdrCell('数量', 1500), hdrCell('职责', 4026)] }),
        new TableRow({ children: [cell('Gunicorn worker进程', 3500), cell('1', 1500), cell('处理HTTP请求', 4026)] }),
        new TableRow({ children: [cell('Gunicorn线程', 3500, altBg), cell('4', 1500, altBg), cell('并发处理请求', 4026, altBg)] }),
        new TableRow({ children: [cell('TaskQueue worker', 3500), cell('4', 1500), cell('后台任务（进程中独立线程）', 4026)] }),
    ] }));
children.push(p('线程池总数 = 4(请求) + 4(后台) = 8线程。瓶颈在Gunicorn workers=1，改为2即可翻倍吞吐量。'));

// ====== 部署 ======
children.push(new Paragraph({ children: [new PageBreak()] }));
children.push(h2('3.6 CF Functions 代理层'));
children.push(new Table({ width: { size: 9026, type: WidthType.DXA }, columnWidths: [4000, 2000, 3026],
    rows: [
        new TableRow({ children: [hdrCell('文件', 4000), hdrCell('路由', 2000), hdrCell('说明', 3026)] }),
        new TableRow({ children: [cell('functions/api/[[path]].js', 4000), cell('/api/*', 2000), cell('反向代理，CORS头', 3026)] }),
        new TableRow({ children: [cell('functions/health.js', 4000, altBg), cell('/health', 2000, altBg), cell('健康检查代理', 3026, altBg)] }),
    ] }));

children.push(h2('3.7 API 端点'));
children.push(new Table({ width: { size: 9026, type: WidthType.DXA }, columnWidths: [1000, 3000, 2026, 3000],
    rows: [
        new TableRow({ children: [hdrCell('方法', 1000), hdrCell('路径', 3000), hdrCell('参数', 2026), hdrCell('说明', 3000)] }),
        new TableRow({ children: [cell('GET', 1000), cell('/api/funds', 3000), cell('page/page_size/sort等', 2026), cell('全量基金列表（分页+排序+筛选）', 3000)] }),
        new TableRow({ children: [cell('GET', 1000, altBg), cell('/api/funds/<code>', 3000, altBg), cell('—', 2026, altBg), cell('单只基金详情', 3000, altBg)] }),
        new TableRow({ children: [cell('GET', 1000), cell('/api/funds/<code>/chart', 3000), cell('days(7/30/90/180/365)', 2026), cell('价格/净值/溢价率曲线', 3000)] }),
        new TableRow({ children: [cell('GET', 1000, altBg), cell('/health', 3000, altBg), cell('—', 2026, altBg), cell('服务状态/缓存/历史天数', 3000, altBg)] }),
        new TableRow({ children: [cell('POST', 1000), cell('/api/nav-backfill', 3000), cell('—', 2026), cell('手动触发净值回填', 3000)] }),
    ] }));

children.push(h2('3.8 配置常量'));
children.push(new Table({ width: { size: 9026, type: WidthType.DXA }, columnWidths: [3500, 2000, 3526],
    rows: [
        new TableRow({ children: [hdrCell('常量', 3500), hdrCell('默认值', 2000), hdrCell('说明', 3526)] }),
        new TableRow({ children: [cell('REQUEST_TIMEOUT', 3500), cell('10s', 2000), cell('单次API请求超时', 3526)] }),
        new TableRow({ children: [cell('REFRESH_INTERVAL', 3500, altBg), cell('300s', 2000, altBg), cell('懒更新间隔', 3526, altBg)] }),
        new TableRow({ children: [cell('KLIN_RETENTION_DAYS', 3500), cell('365', 2000), cell('日线数据保留天数', 3526)] }),
        new TableRow({ children: [cell('SNAPSHOT_RETENTION_DAYS', 3500, altBg), cell('21', 2000, altBg), cell('快照数据保留天数', 3526, altBg)] }),
        new TableRow({ children: [cell('AKSHARE_FAILURE_THRESHOLD', 3500), cell('3', 2000), cell('熔断连续失败次数', 3526)] }),
        new TableRow({ children: [cell('AKSHARE_COOLDOWN_SECONDS', 3500, altBg), cell('300', 2000, altBg), cell('熔断冷却时间', 3526, altBg)] }),
    ] }));

// ====== 四、部署架构 ======
children.push(new Paragraph({ children: [new PageBreak()] }));
children.push(h1('四、部署架构'));
children.push(codeP('┌──────────── Cloudflare ────────────┐'));
children.push(codeP('│  Pages(静态) + Functions(API代理)  │'));
children.push(codeP('└────────────────────────────────┘'));
children.push(codeP('                 │  CORS / 反向代理'));
children.push(codeP('┌──────────── Railway ─────────────┐'));
children.push(codeP('│  Gunicorn(1w×4t) + Flask         │'));
children.push(codeP('│  ├── TaskQueue(4) 后台任务        │'));
children.push(codeP('│  └── PostgreSQL (3表, 91K行)      │'));
children.push(codeP('└────────────────────────────────┘'));
children.push(codeP('                 │  15个数据源'));
children.push(codeP('┌── 行情(3) · K线(8降级) · 净值(2) · 费率(1) · 代码(1) ──┐'));
children.push(p(''));
children.push(p('CI/CD：前端 git push main → GitHub Actions → CF Pages；后端 git push main → Railway Webhook → RAILPACK。'));

// ====== 五、关键功能 ======
children.push(h1('五、关键功能实现'));
children.push(h2('5.1 溢价率计算'));
children.push(codeP('premium_rate = (场内价格 - 场外净值) / 场外净值 × 100'));
children.push(p('正值 = 溢价（申购套利），负值 = 折价（赎回套利）。三日均溢 = 近3日平均。'));
children.push(new Paragraph({ spacing: { after: 100 }, children: [] }));

children.push(h2('5.2 预计收益计算'));
children.push(bullet('溢价套利：收益 = 溢价率 - 申购费率 - 卖出佣金率'));
children.push(bullet('折价套利：收益 = 折价率 - 买入佣金率 - 赎回费率'));
children.push(bullet('考虑最低佣金收费（5元起）'));
children.push(bullet('利润<=0时返回"不建议交易"'));
children.push(bullet('暂停申购基金自动归零'));
children.push(new Paragraph({ spacing: { after: 100 }, children: [] }));

children.push(h2('5.3 历史数据与图表'));
children.push(bullet('每日懒更新自动保存当日快照到 premium_snapshots + daily_kline'));
children.push(bullet('/init-kline-history 补填365天K线（TaskQueue调度）'));
children.push(bullet('/api/nav-backfill 回填缺失净值（lsjz分页，72,567行）'));
children.push(bullet('图表API支持 7/30/90/180/365日五种时间范围'));
children.push(bullet('ChartCache预渲染Top5溢价+Top5折价，5分钟刷新'));
children.push(bullet('图表数据优先查daily_kline，回退premium_snapshots'));
children.push(new Paragraph({ spacing: { after: 100 }, children: [] }));

children.push(h2('5.4 安全与性能'));
children.push(bullet('无鉴权：公开数据工具，无需登录'));
children.push(bullet('CORS：CF Functions统一添加CORS头'));
children.push(bullet('限流：CF Pages自带DDoS防护'));
children.push(bullet('重试：前端3次指数退避重试 + 后端3次重试外部API'));
children.push(bullet('熔断：AkShare连续3次故障自动降级Legacy，300s冷却'));
children.push(bullet('缓存：内存缓存 + PostgreSQL持久化 + CDN静态文件缓存'));

// ====== BUILD ======
const doc = new Document({
    styles: {
        default: { document: { run: { font: 'Arial', size: 22 } } },
        paragraphStyles: [
            { id: 'Heading1', name: 'Heading 1', basedOn: 'Normal', next: 'Normal', quickFormat: true,
              run: { size: 36, bold: true, font: 'Arial', color: '1A2740' },
              paragraph: { spacing: { before: 360, after: 120 }, outlineLevel: 0 } },
            { id: 'Heading2', name: 'Heading 2', basedOn: 'Normal', next: 'Normal', quickFormat: true,
              run: { size: 28, bold: true, font: 'Arial', color: '2C5F8A' },
              paragraph: { spacing: { before: 240, after: 80 }, outlineLevel: 1 } },
            { id: 'Heading3', name: 'Heading 3', basedOn: 'Normal', next: 'Normal', quickFormat: true,
              run: { size: 24, bold: true, font: 'Arial' },
              paragraph: { spacing: { before: 180, after: 80 }, outlineLevel: 2 } },
        ]
    },
    numbering: {
        config: [
            { reference: 'bullets', levels: [{ level: 0, format: LevelFormat.BULLET, text: '•', alignment: AlignmentType.LEFT,
              style: { paragraph: { indent: { left: 720, hanging: 360 } } } }] },
            { reference: 'codeblocks', levels: [{ level: 0, format: LevelFormat.BULLET, text: '', alignment: AlignmentType.LEFT,
              style: { paragraph: { indent: { left: 0, hanging: 0 } } } }] },
        ]
    },
    sections: [{
        properties: {
            page: { size: { width: 11906, height: 16838 }, margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 } }
        },
        headers: {
            default: new Header({ children: [new Paragraph({ alignment: AlignmentType.RIGHT,
                children: [new TextRun({ text: '金快查 · 技术架构文档 v1.2.0', font: 'Arial', size: 18, color: '999999' })] })] })
        },
        footers: {
            default: new Footer({ children: [new Paragraph({ alignment: AlignmentType.CENTER,
                children: [new TextRun({ text: '— ', font: 'Arial', size: 18, color: '999999' }),
                          new TextRun({ children: [PageNumber.CURRENT], font: 'Arial', size: 18, color: '999999' }),
                          new TextRun({ text: ' —', font: 'Arial', size: 18, color: '999999' })] })] })
        },
        children
    }]
});

const outPath = 'D:/汇报/金快查文档/02-技术架构/金快查_技术架构文档.docx';
Packer.toBuffer(doc).then(buf => { fs.writeFileSync(outPath, buf); console.log('OK: ' + outPath); });
