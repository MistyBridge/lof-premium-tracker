/**
 * 金快查 - 管理员面板
 */
var AdminPanel = {
    _users: [],
    _selected: {},

    init: async function () {
        var self = this;
        if (!window._sb) { document.addEventListener('sb:ready', function () { self.init(); }, { once: true }); return; }

        // 检查管理员权限
        try {
            var session = await window._sb.auth.getSession();
            if (!session.data || !session.data.session) { location.hash = '#/'; return; }
            var profile = await window._sb.from('profiles').select('role').single();
            if (profile.data?.role !== 'admin') { location.hash = '#/'; return; }
        } catch (e) { location.hash = '#/'; return; }

        this._bindEvents();
        this._loadUsers();
    },

    _bindEvents: function () {
        var self = this;
        document.getElementById('adminSearchBtn').addEventListener('click', function () { self._loadUsers(); });
        document.getElementById('adminSearch').addEventListener('keydown', function (e) { if (e.key === 'Enter') self._loadUsers(); });
        document.getElementById('adminSelectAll').addEventListener('change', function () {
            self._selected = {};
            if (this.checked) self._users.forEach(function (u) { self._selected[u.id] = true; });
            self._renderCheckboxes();
        });
        document.getElementById('adminBanSelected').addEventListener('click', function () { self._batchAction('ban'); });
        document.getElementById('adminUnbanSelected').addEventListener('click', function () { self._batchAction('unban'); });
        document.getElementById('adminExportCSV').addEventListener('click', function () { self._exportCSV(); });
    },

    _loadUsers: async function () {
        var self = this;
        var list = document.getElementById('adminUserList');
        list.innerHTML = '<tr><td colspan="7" class="admin-empty">加载中...</td></tr>';

        var search = document.getElementById('adminSearch').value.trim().toLowerCase();
        var status = document.getElementById('adminStatusFilter').value;
        var time = document.getElementById('adminTimeFilter').value;

        var query = window._sb.from('profiles').select('*').order('created_at', { ascending: false }).limit(100);
        if (status !== 'all') query = query.eq('status', status);
        if (search) query = query.or('email.ilike.%' + search + '%,nickname.ilike.%' + search + '%');

        var res = await query;
        if (res.error) { list.innerHTML = '<tr><td colspan="7" class="admin-empty">加载失败</td></tr>'; return; }

        var users = res.data || [];
        if (time !== 'all') {
            var days = parseInt(time);
            var cutoff = new Date();
            cutoff.setDate(cutoff.getDate() - days);
            users = users.filter(function (u) { return u.last_login && new Date(u.last_login) >= cutoff; });
        }

        self._users = users;
        self._selected = {};
        document.getElementById('adminSelectAll').checked = false;
        document.getElementById('adminPageInfo').textContent = '共 ' + users.length + ' 位用户';

        if (users.length === 0) {
            list.innerHTML = '<tr><td colspan="7" class="admin-empty">暂无数据</td></tr>';
            return;
        }

        list.innerHTML = users.map(function (u) {
            var roleLabel = u.role === 'admin' ? '<span class="admin-badge admin-badge-admin">管理员</span>' : '<span class="admin-badge admin-badge-user">用户</span>';
            var statusLabel = u.status === 'active' ? '<span class="admin-badge admin-badge-active">正常</span>' : '<span class="admin-badge admin-badge-banned">已封禁</span>';
            var created = u.created_at ? new Date(u.created_at).toLocaleDateString('zh-CN') : '-';
            var actions = '';
            if (u.status === 'active') {
                actions += '<button class="admin-action-btn ban" data-id="' + u.id + '">封禁</button>';
            } else {
                actions += '<button class="admin-action-btn unban" data-id="' + u.id + '">解封</button>';
            }
            if (u.role !== 'admin') {
                actions += '<button class="admin-action-btn promote" data-id="' + u.id + '">设管理员</button>';
            }
            return '<tr data-id="' + u.id + '"><td><input type="checkbox" class="admin-checkbox" data-id="' + u.id + '"></td><td>' + self._escapeHtml(u.email) + '</td><td>' + self._escapeHtml(u.nickname || '-') + '</td><td>' + roleLabel + '</td><td>' + statusLabel + '</td><td>' + created + '</td><td>' + actions + '</td></tr>';
        }).join('');

        // Bind checkboxes
        list.querySelectorAll('.admin-checkbox').forEach(function (cb) {
            cb.addEventListener('change', function () {
                if (this.checked) self._selected[this.dataset.id] = true;
                else delete self._selected[this.dataset.id];
            });
        });

        // Bind action buttons
        list.querySelectorAll('.admin-action-btn.ban').forEach(function (btn) {
            btn.addEventListener('click', function () { self._banUser(this.dataset.id); });
        });
        list.querySelectorAll('.admin-action-btn.unban').forEach(function (btn) {
            btn.addEventListener('click', function () { self._unbanUser(this.dataset.id); });
        });
        list.querySelectorAll('.admin-action-btn.promote').forEach(function (btn) {
            btn.addEventListener('click', function () { self._promoteUser(this.dataset.id); });
        });
    },

    _renderCheckboxes: function () {
        var self = this;
        document.querySelectorAll('.admin-checkbox').forEach(function (cb) {
            cb.checked = !!self._selected[cb.dataset.id];
        });
    },

    _batchAction: async function (action) {
        var ids = Object.keys(this._selected);
        if (ids.length === 0) { alert('请先选择用户'); return; }
        var newStatus = action === 'ban' ? 'banned' : 'active';
        var confirmMsg = action === 'ban' ? '确定要封禁 ' + ids.length + ' 位用户吗？' : '确定要解封 ' + ids.length + ' 位用户吗？';
        if (!confirm(confirmMsg)) return;

        var self = this;
        for (var i = 0; i < ids.length; i++) {
            await window._sb.from('profiles').update({ status: newStatus }).eq('id', ids[i]);
        }
        self._loadUsers();
    },

    _banUser: async function (id) {
        if (!confirm('确定封禁此用户？')) return;
        await window._sb.from('profiles').update({ status: 'banned' }).eq('id', id);
        this._loadUsers();
    },

    _unbanUser: async function (id) {
        if (!confirm('确定解封此用户？')) return;
        await window._sb.from('profiles').update({ status: 'active' }).eq('id', id);
        this._loadUsers();
    },

    _promoteUser: async function (id) {
        if (!confirm('确定将此用户设为管理员？')) return;
        await window._sb.from('profiles').update({ role: 'admin' }).eq('id', id);
        this._loadUsers();
    },

    _exportCSV: function () {
        var rows = ['邮箱,昵称,角色,状态,注册时间'];
        this._users.forEach(function (u) {
            rows.push([u.email, u.nickname || '', u.role, u.status, u.created_at || ''].join(','));
        });
        var blob = new Blob(['﻿' + rows.join('\n')], { type: 'text/csv;charset=utf-8' });
        var url = URL.createObjectURL(blob);
        var a = document.createElement('a');
        a.href = url; a.download = 'users_' + new Date().toISOString().slice(0, 10) + '.csv';
        a.click(); URL.revokeObjectURL(url);
    },

    _escapeHtml: function (text) {
        var div = document.createElement('div');
        div.textContent = text || '';
        return div.innerHTML;
    }
};
