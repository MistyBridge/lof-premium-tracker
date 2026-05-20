/**
 * 金快查 — 表头注册中心
 * 所有可显示列的元数据 + localStorage 用户偏好管理
 */
const COLUMN_REGISTRY = [
    { id: 'code',               label: '代码',       width: 98,  defaultVisible: true,  frozen: true,  sortable: true,  sortField: 'code' },
    { id: 'name',               label: '名称',       width: 169, defaultVisible: true,  frozen: true,  sortable: true,  sortField: 'name' },
    { id: 'price',              label: '现价',       width: 104, defaultVisible: true,  frozen: false, sortable: true,  sortField: 'price' },
    { id: 'nav',                label: '净值',       width: 137, defaultVisible: true,  frozen: false, sortable: true,  sortField: 'nav' },
    { id: 'change_pct',         label: '涨跌幅',      width: 104, defaultVisible: true,  frozen: false, sortable: true,  sortField: 'change_pct' },
    { id: 'premium_rate',       label: '溢价率',      width: 111, defaultVisible: true,  frozen: false, sortable: true,  sortField: 'premium_rate' },
    { id: 'avg_premium_3d',     label: '三日均溢',    width: 117, defaultVisible: true,  frozen: false, sortable: true,  sortField: 'avg_premium_3d' },
    { id: 'amount',             label: '成交额',      width: 124, defaultVisible: true,  frozen: false, sortable: true,  sortField: 'amount_w' },
    { id: 'est_profit_rate',    label: '预计收益率',   width: 137, defaultVisible: true,  frozen: false, sortable: true,  sortField: 'est_profit_rate' },
    { id: 'est_profit_amount',  label: '预计收益额',   width: 137, defaultVisible: true,  frozen: false, sortable: true,  sortField: 'est_profit_amount' },
    { id: 'purchase_status',    label: '申购状态',    width: 117, defaultVisible: false, frozen: false, sortable: false, sortField: null },
    { id: 'nav_date',           label: '净值时间',    width: 130, defaultVisible: false, frozen: false, sortable: false, sortField: null },
    { id: 'volume',             label: '成交量',      width: 117, defaultVisible: false, frozen: false, sortable: false, sortField: null },
    { id: 'change_amount',      label: '涨跌额',      width: 104, defaultVisible: false, frozen: false, sortable: false, sortField: null },
    { id: 'is_suspended',       label: '停牌状态',    width: 111, defaultVisible: false, frozen: false, sortable: false, sortField: null },
    { id: 'purchase_fee_rate',  label: '申购费率',    width: 111, defaultVisible: false, frozen: false, sortable: false, sortField: null },
    { id: 'data_date',          label: '数据日期',    width: 130, defaultVisible: false, frozen: false, sortable: false, sortField: null },
];
if (typeof window !== 'undefined') { window.COLUMN_REGISTRY = COLUMN_REGISTRY; }

/* ── localStorage 偏好管理 ── */
var STORAGE_KEY = 'lof_column_prefs_v1';

function loadColumnPrefs() {
    try { return JSON.parse(localStorage.getItem(STORAGE_KEY)) || {}; }
    catch (e) { return {}; }
}

function saveColumnPrefs(prefs) {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(prefs));
}

/**
 * 获取当前应显示的列（合并注册表默认值 + 用户偏好）
 * 代码列始终可见、始终在最前
 */
function getActiveColumns() {
    var prefs = loadColumnPrefs();
    var userOrder = prefs.order || null;
    var userVisible = prefs.visible || {};
    // 构建 id → 可见 映射：默认按 defaultVisible，用户可覆盖
    var visible = {};
    COLUMN_REGISTRY.forEach(function(c) {
        if (c.id === 'code') { visible[c.id] = true; return; }
        if (c.id in userVisible) { visible[c.id] = userVisible[c.id]; }
        else { visible[c.id] = c.defaultVisible; }
    });
    // 排序：code 始终第一，其余按 userOrder（或注册表默认顺序）
    var order = userOrder || COLUMN_REGISTRY.map(function(c) { return c.id; });
    // 确保 code 在 order 最前
    var codeIdx = order.indexOf('code');
    if (codeIdx > 0) { order.splice(codeIdx, 1); order.unshift('code'); }
    var active = [];
    COLUMN_REGISTRY.forEach(function(c) {
        if (visible[c.id]) { active.push(c); }
    });
    active.sort(function(a, b) {
        var ai = order.indexOf(a.id), bi = order.indexOf(b.id);
        if (ai === -1) return 1;
        if (bi === -1) return -1;
        return ai - bi;
    });
    return active;
}

/**
 * 更新用户列偏好
 * visible: { colId: true/false, ... }
 * order:   [colId, ...] 全量顺序
 */
function updateColumnPrefs(visible, order) {
    var prefs = loadColumnPrefs();
    if (visible !== undefined) {
        prefs.visible = prefs.visible || {};
        Object.keys(visible).forEach(function(k) { prefs.visible[k] = visible[k]; });
    }
    if (order !== undefined) { prefs.order = order; }
    saveColumnPrefs(prefs);
}

function resetColumnPrefs() {
    localStorage.removeItem(STORAGE_KEY);
}

/* ── 表头存档 ── */
var PRESETS_KEY = 'lof_column_presets_v1';

function loadPresets() {
    try { return JSON.parse(localStorage.getItem(PRESETS_KEY)) || []; }
    catch (e) { return []; }
}

function savePresets(presets) {
    localStorage.setItem(PRESETS_KEY, JSON.stringify(presets));
}

/** 保存当前配置为新存档 */
function saveCurrentAsPreset(name) {
    var prefs = loadColumnPrefs();
    var visible = prefs.visible || {};
    var order = prefs.order || COLUMN_REGISTRY.map(function(c) { return c.id; });
    var presets = loadPresets();
    presets.push({ name: name, visible: JSON.parse(JSON.stringify(visible)), order: order.slice() });
    savePresets(presets);
}

/** 用当前配置覆盖指定存档 */
function overwritePreset(index) {
    var presets = loadPresets();
    if (index < 0 || index >= presets.length) return;
    var prefs = loadColumnPrefs();
    var visible = prefs.visible || {};
    var order = prefs.order || COLUMN_REGISTRY.map(function(c) { return c.id; });
    presets[index].visible = JSON.parse(JSON.stringify(visible));
    presets[index].order = order.slice();
    savePresets(presets);
}

/** 应用存档 */
function applyPreset(index) {
    var presets = loadPresets();
    if (index < 0 || index >= presets.length) return;
    var preset = presets[index];
    updateColumnPrefs(preset.visible, preset.order);
}

/** 删除存档 */
function deletePreset(index) {
    var presets = loadPresets();
    if (index < 0 || index >= presets.length) return;
    presets.splice(index, 1);
    savePresets(presets);
}
