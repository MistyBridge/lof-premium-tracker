/**
 * 金快查 - 用户设置云端同步 (localStorage ↔ Supabase user_settings)
 */
var SettingsSync = {
    /** 从 Supabase 拉取设置，合并到 localStorage */
    pullFromCloud: async function () {
        if (!window._sb) return;
        try {
            var session = await window._sb.auth.getSession();
            if (!session.data || !session.data.session) return;
            var res = await window._sb.from('user_settings').select('*').limit(1).maybeSingle();
            if (res.error || !res.data) return;
            var s = res.data;
            if (s.dark_mode) localStorage.setItem('lof_darkMode', s.dark_mode);
            if (s.default_page) localStorage.setItem('lof_defaultPage', s.default_page);
            if (s.page_size) localStorage.setItem('lof_pageSize', s.page_size);
            if (s.show_suspended !== null && s.show_suspended !== undefined) localStorage.setItem('lof_showSuspended_v2', s.show_suspended ? '1' : '0');
            if (s.columns_config) localStorage.setItem('lof_column_prefs_v1', JSON.stringify(s.columns_config));
            console.log('[SettingsSync] Pulled from cloud');
        } catch (e) {
            console.error('[SettingsSync] Pull failed:', e.message);
        }
    },

    /** 推送当前设置到 Supabase */
    pushToCloud: async function () {
        if (!window._sb) return;
        try {
            var session = await window._sb.auth.getSession();
            if (!session.data || !session.data.session) return;
            var prefs = {
                dark_mode: localStorage.getItem('lof_darkMode') || 'light',
                default_page: localStorage.getItem('lof_defaultPage') || 'lof',
                page_size: parseInt(localStorage.getItem('lof_pageSize')) || 20,
                show_suspended: localStorage.getItem('lof_showSuspended_v2') === '1',
                columns_config: null
            };
            try {
                var cols = JSON.parse(localStorage.getItem('lof_column_prefs_v1'));
                if (cols) prefs.columns_config = cols;
            } catch (e) {}
            await window._sb.from('user_settings').upsert(prefs);
            console.log('[SettingsSync] Pushed to cloud');
        } catch (e) {
            console.error('[SettingsSync] Push failed:', e.message);
        }
    }
};
