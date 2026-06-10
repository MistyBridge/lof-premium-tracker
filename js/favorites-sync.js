/**
 * 金快查 - 收藏云端同步 (localStorage ↔ Supabase)
 */
var FavoritesSync = {
    _syncing: false,

    /** 登录后：从 Supabase 拉取收藏，合并到 localStorage */
    pullAndMerge: async function () {
        if (this._syncing || !window._sb) return;
        this._syncing = true;
        try {
            var session = await window._sb.auth.getSession();
            if (!session.data || !session.data.session) { this._syncing = false; return; }

            // 读取云端收藏
            var cloudRes = await window._sb.from('fund_favorites').select('fund_code');
            if (cloudRes.error) throw cloudRes.error;
            var cloudCodes = (cloudRes.data || []).map(function (r) { return r.fund_code; });

            // 读取本地收藏
            var localCodes = [];
            try { localCodes = JSON.parse(localStorage.getItem('lof_favorites')) || []; } catch (e) {}

            // 合并：取并集
            var merged = {};
            localCodes.forEach(function (c) { merged[c] = true; });
            cloudCodes.forEach(function (c) { merged[c] = true; });
            var mergedList = Object.keys(merged);

            // 写入本地
            localStorage.setItem('lof_favorites', JSON.stringify(mergedList));

            // 同步云端（补上本地有云端没有的）
            var toPush = mergedList.filter(function (c) { return cloudCodes.indexOf(c) < 0; });
            var uid = session.data.session.user.id;
            for (var i = 0; i < toPush.length; i++) {
                await window._sb.from('fund_favorites').insert({ fund_code: toPush[i], user_id: uid });
            }

            console.log('[FavSync] Merged ' + localCodes.length + ' local + ' + cloudCodes.length + ' cloud = ' + mergedList.length + ' total');
            return mergedList;
        } catch (e) {
            console.error('[FavSync] Pull failed:', e.message);
        } finally {
            this._syncing = false;
        }
    },

    /** 添加单只收藏到云端 */
    addToCloud: async function (code) {
        if (!window._sb) return;
        try {
            var session = await window._sb.auth.getSession();
            if (!session.data || !session.data.session) return;
            var uid = session.data.session.user.id;
            await window._sb.from('fund_favorites').upsert(
                { fund_code: code, user_id: uid },
                { onConflict: 'user_id,fund_code' }
            );
        } catch (e) {
            console.error('[FavSync] Add failed:', e.message);
        }
    },

    /** 从云端删除单只收藏 */
    removeFromCloud: async function (code) {
        if (!window._sb) return;
        try {
            var session = await window._sb.auth.getSession();
            if (!session.data || !session.data.session) return;
            var uid = session.data.session.user.id;
            await window._sb.from('fund_favorites').delete()
                .eq('fund_code', code)
                .eq('user_id', uid);
        } catch (e) {
            console.error('[FavSync] Remove failed:', e.message);
        }
    },

    /** 获取云端收藏数量 */
    getCount: async function () {
        if (!window._sb) return 0;
        try {
            var res = await window._sb.from('fund_favorites').select('fund_code', { count: 'exact', head: true });
            return res.count || 0;
        } catch (e) { return 0; }
    }
};
