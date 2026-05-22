/**
 * 金快查 — 通用缓存模块
 * localStorage + TTL + Stale-While-Revalidate
 */
var Cache = {
    _prefix: 'jkc_',

    set: function(key, data, ttlMs) {
        try {
            var entry = { d: data, e: Date.now() + (ttlMs || 300000) };
            localStorage.setItem(this._prefix + key, JSON.stringify(entry));
        } catch(e) {
            // quota exceeded, silently fail
        }
    },

    get: function(key) {
        try {
            var raw = localStorage.getItem(this._prefix + key);
            if (!raw) return null;
            var entry = JSON.parse(raw);
            if (Date.now() > entry.e) { localStorage.removeItem(this._prefix + key); return null; }
            return entry.d;
        } catch(e) { return null; }
    },

    remove: function(key) {
        localStorage.removeItem(this._prefix + key);
    },

    swr: function(key, ttlMs, fetcher, onData) {
        var cached = this.get(key);
        if (cached) { onData(cached, true); }
        var self = this;
        fetcher().then(function(fresh) {
            self.set(key, fresh, ttlMs);
            onData(fresh, false);
        }).catch(function(err) {
            if (!cached) { onData(null, false, err); }
        });
    }
};
