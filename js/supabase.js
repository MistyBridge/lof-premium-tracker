/**
 * 金快查 - Supabase 客户端封装
 */
(function () {
    var SUPABASE_URL = 'https://dwlvonyixwmyrekvxzgx.supabase.co';
    var SUPABASE_ANON_KEY = 'sb_publishable_dir8chSzBaXpZ4hwCXHBMg_ri5Sh7li';

    var attempts = 0;
    function init() {
        if (typeof supabase === 'undefined') {
            if (++attempts > 200) {
                console.error('[Supabase] SDK failed to load');
                return;
            }
            setTimeout(init, 50);
            return;
        }
        window._sb = supabase.createClient(SUPABASE_URL, SUPABASE_ANON_KEY, {
            auth: {
                persistSession: true,
                storageKey: 'sb_session',
                autoRefreshToken: true,
                detectSessionInUrl: false
            }
        });
        console.log('[Supabase] Client ready');
        document.dispatchEvent(new CustomEvent('sb:ready'));
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
