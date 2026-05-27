/**
 * 金快查 — 基金详情 KPI 卡片注册中心
 */
var KPI_CARD_REGISTRY = [
    { id: 'fdCode',           label: '代码',         defaultVisible: true,  critical: true  },
    { id: 'fdName',           label: '名称',         defaultVisible: true,  critical: true  },
    { id: 'fdPrice',          label: '现价',         defaultVisible: true,  critical: false },
    { id: 'fdNav',            label: '净值',         defaultVisible: true,  critical: false },
    { id: 'fdChangePct',      label: '涨跌幅',       defaultVisible: true,  critical: false },
    { id: 'fdPremiumRate',    label: '溢价率',       defaultVisible: true,  critical: false },
    { id: 'fdAvgPremium',     label: '三日均溢',     defaultVisible: true,  critical: false },
    { id: 'fdAmount',         label: '成交额',       defaultVisible: true,  critical: false },
    { id: 'fdEstProfitRate',  label: '预计收益率',   defaultVisible: true,  critical: false },
    { id: 'fdEstProfitAmount',label: '预计收益额',   defaultVisible: true,  critical: false },
    { id: 'fdStatus',         label: '状态',         defaultVisible: false,  critical: false },
    { id: 'fdPurchaseLimit',  label: '申购限额',     defaultVisible: true,  critical: false },
    { id: 'fdNavDate',        label: '净值日期',     defaultVisible: true,  critical: false },
    { id: 'fdVolume',         label: '成交量',       defaultVisible: false, critical: false },
    { id: 'fdChangeAmount',   label: '涨跌额',       defaultVisible: false, critical: false },
    { id: 'fdSuspended',      label: '停牌状态',     defaultVisible: false, critical: false },
    { id: 'fdPurchaseFee',    label: '申购费率',     defaultVisible: false, critical: false },
    { id: 'fdDataDate',       label: '数据日期',     defaultVisible: false, critical: false },
    { id: 'fdTurnoverRate',   label: '换手率',       defaultVisible: false, critical: false },
    { id: 'fdOnExchangeShares',label: '场内份额',    defaultVisible: false, critical: false },
];

var KPI_PREFS_KEY = 'lof_kpi_card_prefs_v1';

function loadKpiPrefs() { try { return JSON.parse(localStorage.getItem(KPI_PREFS_KEY)) || {}; } catch (e) { return {}; } }
function saveKpiPrefs(p) { localStorage.setItem(KPI_PREFS_KEY, JSON.stringify(p)); }

function getActiveKpiIds() {
    var prefs = loadKpiPrefs();
    var visible = prefs.visible || {};
    var order = prefs.order || KPI_CARD_REGISTRY.map(function (c) { return c.id; });
    var active = [];
    KPI_CARD_REGISTRY.forEach(function (c) {
        if (c.critical || (c.id in visible ? visible[c.id] : c.defaultVisible)) {
            active.push(c.id);
        }
    });
    active.sort(function (a, b) { return order.indexOf(a) - order.indexOf(b); });
    return active;
}

function resetKpiPrefs() { localStorage.removeItem(KPI_PREFS_KEY); }

// 存档系统
var KPI_PRESETS_KEY = 'lof_kpi_card_presets_v1';
function loadKpiPresets() { try { return JSON.parse(localStorage.getItem(KPI_PRESETS_KEY)) || []; } catch (e) { return []; } }
function saveKpiPresets(presets) { localStorage.setItem(KPI_PRESETS_KEY, JSON.stringify(presets)); }
function saveCurrentAsKpiPreset(name) {
    var presets = loadKpiPresets();
    presets.push({ name: name, prefs: loadKpiPrefs() });
    saveKpiPresets(presets);
}
function applyKpiPreset(index) {
    var presets = loadKpiPresets();
    if (index >= 0 && index < presets.length) {
        saveKpiPrefs(presets[index].prefs);
    }
}
function overwriteKpiPreset(index) {
    var presets = loadKpiPresets();
    if (index >= 0 && index < presets.length) {
        presets[index].prefs = loadKpiPrefs();
        saveKpiPresets(presets);
    }
}
function deleteKpiPreset(index) {
    var presets = loadKpiPresets();
    presets.splice(index, 1);
    saveKpiPresets(presets);
}
