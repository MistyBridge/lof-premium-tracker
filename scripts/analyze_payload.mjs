/**
 * 分析 /api/v1/funds 单行 JSON 的体积构成。
 * 目的：给"精简 payload"这条路一个可验证的数字 ——
 * 哪些字段永远是 null（可无损删除），哪些字段两两完全相同（可去重）。
 *
 *   node scripts/analyze_payload.mjs [etf|lof]
 */
const mode = process.argv[2] || 'etf';
const size = mode === 'etf' ? 2400 : 600;
const url = `http://api.jinkuaicha.com/api/v1/funds?page=1&size=${size}&filter_mode=${mode}`;

const res = await fetch(url);
const text = await res.text();
const json = JSON.parse(text);
const rows = json.data;

console.log(`板块=${mode}  行数=${rows.length}`);
console.log(`原始 JSON 总字节=${text.length.toLocaleString()}  平均每行=${Math.round(text.length / rows.length)} 字节`);
console.log(`字段总数=${Object.keys(rows[0]).length}`);
console.log('');

// 1. 永远为 null/undefined 的字段
const keys = Object.keys(rows[0]);
const alwaysNull = [];
const nullCount = {};
for (const k of keys) {
  let n = 0;
  for (const r of rows) {
    const v = r[k];
    if (v === null || v === undefined) n++;
  }
  nullCount[k] = n;
  if (n === rows.length) alwaysNull.push(k);
}

// 2. 与另一个字段逐行完全相同的字段（只保留首个）
const dupOf = {};
const seen = [];
for (const k of keys) {
  if (alwaysNull.includes(k)) continue;
  let matched = null;
  for (const prev of seen) {
    let same = true;
    for (const r of rows) {
      if (r[k] !== r[prev]) { same = false; break; }
    }
    if (same) { matched = prev; break; }
  }
  if (matched) dupOf[k] = matched;
  else seen.push(k);
}

console.log('=== 全部为 null 的字段（删除不影响任何展示）===');
console.log(alwaysNull.length ? '  ' + alwaysNull.join(', ') : '  无');
console.log('');
console.log('=== 与其它字段逐行完全相同的字段（可去重）===');
const dupEntries = Object.entries(dupOf);
console.log(dupEntries.length ? dupEntries.map(([k, v]) => `  ${k}  ==  ${v}`).join('\n') : '  无');
console.log('');

// 3. 模拟精简后的体积
const drop = new Set([...alwaysNull, ...Object.keys(dupOf)]);
const slim = rows.map((r) => {
  const o = {};
  for (const k of Object.keys(r)) if (!drop.has(k)) o[k] = r[k];
  return o;
});
const slimBytes = JSON.stringify(slim).length;
console.log('=== 精简效果 ===');
console.log(`  删除字段数：${drop.size} / ${keys.length}`);
console.log(`  精简后总字节≈${slimBytes.toLocaleString()}  （原 ${text.length.toLocaleString()}，降到 ${(slimBytes / text.length * 100).toFixed(0)}%）`);
console.log('');
console.log('=== 各行 null 占比最高的字段（前 12）===');
Object.entries(nullCount)
  .filter(([k, n]) => n > 0 && n < rows.length)
  .sort((a, b) => b[1] - a[1])
  .slice(0, 12)
  .forEach(([k, n]) => console.log(`  ${k.padEnd(22)} ${String(n).padStart(5)}/${rows.length} 行是 null  (${(n / rows.length * 100).toFixed(0)}%)`));
