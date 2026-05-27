/**
 * 金快查 - 用户中心页面
 */
var AccountPage = {
    _inited: false,
    _userId: null,

    init: function () {
        if (this._inited) { this._loadUser(); return; }
        this._inited = true;
        this._bindEvents();
        this._loadUser();
    },

    _bindEvents: function () {
        var self = this;

        // 退出
        var logoutBtn = document.getElementById('accountLogoutBtn');
        if (logoutBtn) logoutBtn.addEventListener('click', function () {
            self._showConfirm('退出登录', '确定要退出当前账号吗？', false, function () { self._logout(); });
        });

        // 注销
        var destroyBtn = document.getElementById('accountDestroyBtn');
        if (destroyBtn) destroyBtn.addEventListener('click', function () { self._destroyAccount(); });

        // 头像上传
        var avatar = document.getElementById('accountAvatar');
        var fileInput = document.getElementById('accountAvatarInput');
        if (avatar && fileInput) {
            avatar.addEventListener('click', function () { fileInput.click(); });
            fileInput.addEventListener('change', function () { self._uploadAvatar(this.files[0]); });
        }

        // 编辑资料
        var editBtn = document.getElementById('accountEditBtn');
        if (editBtn) editBtn.addEventListener('click', function () { self._openEditProfile(); });
        var closeBtn = document.getElementById('profileEditClose');
        if (closeBtn) closeBtn.addEventListener('click', function () { self._closeEditProfile(); });
        var saveBtn = document.getElementById('profileEditSave');
        if (saveBtn) saveBtn.addEventListener('click', function () { self._saveProfile(); });

        // 头像预览
        var avatar = document.getElementById('accountAvatar');
        if (avatar) avatar.addEventListener('click', function () { self._openAvatarPreview(); });
        var avatarClose = document.getElementById('avatarPreviewClose');
        if (avatarClose) avatarClose.addEventListener('click', function () { self._closeAvatarPreview(); });
        var avatarUploadBtn = document.getElementById('avatarUploadBtn');
        if (avatarUploadBtn) avatarUploadBtn.addEventListener('click', function () { document.getElementById('accountAvatarInput').click(); });
        var fileInput = document.getElementById('accountAvatarInput');
        if (fileInput) fileInput.addEventListener('change', function () { self._uploadAvatar(this.files[0]); });

        // 收藏同步
        var syncBtn = document.getElementById('accountSyncBtn');
        if (syncBtn) {
            syncBtn.disabled = false;
            syncBtn.textContent = '同步收藏';
            syncBtn.addEventListener('click', function () {
                self._doFavSync();
            });
        }

        // 修改密码
        var chPwdBtn = document.getElementById('accountChPwdBtn');
        if (chPwdBtn) chPwdBtn.addEventListener('click', function () { self._openChPwd(); });
        var chPwdClose = document.getElementById('chPwdClose');
        if (chPwdClose) chPwdClose.addEventListener('click', function () { self._closeChPwd(); });
        var chPwdSave = document.getElementById('chPwdSave');
        if (chPwdSave) chPwdSave.addEventListener('click', function () { self._saveChPwd(); });

        // 偏好
        var darkMode = document.getElementById('accountDarkMode');
        if (darkMode) {
            darkMode.addEventListener('change', function () {
                var m = this.value;
                localStorage.setItem('lof_darkMode', m);
                document.documentElement.classList.remove('dark-mode', 'light-mode');
                document.documentElement.classList.add(m === 'dark' ? 'dark-mode' : 'light-mode');
            });
        }
    },

    _loadUser: async function () {
        if (!window._sb) {
            document.addEventListener('sb:ready', this._loadUser.bind(this), { once: true });
            return;
        }
        try {
            var res = await window._sb.auth.getSession();
            if (!res.data || !res.data.session) { location.hash = '#/'; return; }
            var user = res.data.session.user;
            this._userId = user.id;

            // Load profile from DB
            var profileRes = await window._sb
                .from('profiles')
                .select('nickname,avatar_url,created_at')
                .eq('id', user.id)
                .single();

            var profile = profileRes.data || {};
            var nickname = profile.nickname || user.email.split('@')[0];
            var avatarUrl = profile.avatar_url;

            // Render
            document.getElementById('accountEmail').textContent = user.email || '未知';
            document.getElementById('accountNickname').textContent = nickname;
            this._renderAvatar(avatarUrl, nickname.charAt(0).toUpperCase());

            var createdAt = profile.created_at || user.created_at;
            if (createdAt) {
                document.getElementById('accountMeta').textContent =
                    '注册时间：' + new Date(createdAt).toLocaleDateString('zh-CN') +
                    ' · 上次登录：' + new Date(user.last_sign_in_at || createdAt).toLocaleDateString('zh-CN');
            }

            this._updateFavCount();
            // Prefs
            document.getElementById('accountDarkMode').value = localStorage.getItem('lof_darkMode') || 'light';
        } catch (e) {
            console.error('[Account] Load failed:', e.message);
        }
    },

    _renderAvatar: function (url, fallback) {
        var el = document.getElementById('accountAvatar');
        if (url) {
            el.innerHTML = '<img src="' + url + '" alt="avatar" style="width:56px;height:56px;border-radius:50%;object-fit:cover">';
        } else {
            el.innerHTML = '<img src="assets/default-avatar.jpg" alt="avatar" style="width:56px;height:56px;border-radius:50%;object-fit:cover">';
        }
    },

    _openAvatarPreview: function () {
        var el = document.getElementById('accountAvatar');
        var previewImg = document.getElementById('avatarPreviewImg');
        var img = el.querySelector('img');
        if (img) {
            previewImg.src = img.src;
        } else {
            previewImg.src = '';
        }
        document.getElementById('avatarPreviewModal').style.display = 'flex';
    },
    _closeAvatarPreview: function () {
        document.getElementById('avatarPreviewModal').style.display = 'none';
    },

    _uploadAvatar: async function (file) {
        if (!file) return;
        if (file.size > 200 * 1024) { alert('图片大小不能超过200KB'); return; }
        var self = this;
        var ext = file.name.split('.').pop().toLowerCase();
        if (['jpg','jpeg','png','gif','webp'].indexOf(ext) < 0) { alert('仅支持 JPG/PNG/GIF/WebP 格式'); return; }

        var path = this._userId + '.' + ext;
        try {
            var uploadRes = await window._sb.storage.from('avatars').upload(path, file, { upsert: true, contentType: file.type });
            if (uploadRes.error) throw uploadRes.error;
            var urlRes = window._sb.storage.from('avatars').getPublicUrl(path);
            var url = urlRes.data.publicUrl;
            await window._sb.from('profiles').update({ avatar_url: url }).eq('id', this._userId);
            this._renderAvatar(url, '');
            var previewImg = document.getElementById('avatarPreviewImg');
            if (previewImg) previewImg.src = url;
        } catch (e) {
            console.error('[Account] Upload failed:', e.message);
            alert('上传失败：' + (e.message || '未知错误'));
        }
    },

    _openEditProfile: function () {
        document.getElementById('profileNicknameInput').value = document.getElementById('accountNickname').textContent;
        document.getElementById('profileEditModal').style.display = 'flex';
        document.getElementById('profileEditError').style.display = 'none';
    },
    _closeEditProfile: function () { document.getElementById('profileEditModal').style.display = 'none'; },
    _saveProfile: async function () {
        var nickname = document.getElementById('profileNicknameInput').value.trim();
        if (!nickname) { document.getElementById('profileEditError').style.display = ''; document.getElementById('profileEditError').textContent = '昵称不能为空'; return; }
        var btn = document.getElementById('profileEditSave');
        btn.disabled = true; btn.textContent = '保存中...';
        try {
            await window._sb.from('profiles').update({ nickname: nickname }).eq('id', this._userId);
            document.getElementById('accountNickname').textContent = nickname;
            this._closeEditProfile();
        } catch (e) {
            document.getElementById('profileEditError').style.display = '';
            document.getElementById('profileEditError').textContent = e.message || '保存失败';
        }
        btn.disabled = false; btn.textContent = '保存';
    },

    _openChPwd: function () {
        document.getElementById('chPwdError').style.display = 'none';
        document.getElementById('chPwdCurrent').value = '';
        document.getElementById('chPwdNew').value = '';
        document.getElementById('chPwdNew2').value = '';
        document.getElementById('chPwdModal').style.display = 'flex';
    },
    _closeChPwd: function () { document.getElementById('chPwdModal').style.display = 'none'; },
    _saveChPwd: async function () {
        var cur = document.getElementById('chPwdCurrent').value;
        var newP = document.getElementById('chPwdNew').value;
        var newP2 = document.getElementById('chPwdNew2').value;
        if (!cur || !newP) { document.getElementById('chPwdError').style.display = ''; document.getElementById('chPwdError').textContent = '请填写新密码'; return; }
        if (newP.length < 6) { document.getElementById('chPwdError').style.display = ''; document.getElementById('chPwdError').textContent = '新密码至少6位'; return; }
        if (newP !== newP2) { document.getElementById('chPwdError').style.display = ''; document.getElementById('chPwdError').textContent = '两次新密码不一致'; return; }
        var btn = document.getElementById('chPwdSave');
        btn.disabled = true; btn.textContent = '修改中...';
        try {
            // Re-authenticate then update
            var email = document.getElementById('accountEmail').textContent;
            var authRes = await window._sb.auth.signInWithPassword({ email: email, password: cur });
            if (authRes.error) throw authRes.error;
            var updateRes = await window._sb.auth.updateUser({ password: newP });
            if (updateRes.error) throw updateRes.error;
            this._closeChPwd();
        } catch (e) {
            document.getElementById('chPwdError').style.display = '';
            document.getElementById('chPwdError').textContent = e.message || '修改失败';
        }
        btn.disabled = false; btn.textContent = '确认修改';
    },

    _logout: async function () {
        if (window._sb) await window._sb.auth.signOut();
        // 清除记住的密码（保留邮箱）
        localStorage.removeItem('sb_remember_pwd');
        var links = document.querySelectorAll('.user-center-link');
        links.forEach(function (l) {
            l.textContent = '用户中心';
            l.onclick = function () { if (window.Auth) Auth.open('login'); };
        });
        location.hash = '#/';
        if (window.Auth) Auth._updateUI(null);
    },

    // ── 通用确认弹窗 ──
    _showConfirm: function (title, msg, extra, callback) {
        var self = this;
        document.getElementById('confirmTitle').textContent = title;
        document.getElementById('confirmMsg').textContent = msg;
        var extraDiv = document.getElementById('confirmExtra');
        extraDiv.style.display = extra ? '' : 'none';
        if (extra) {
            document.getElementById('confirmEmail').value = '';
            document.getElementById('confirmPassword').value = '';
            document.getElementById('confirmError').style.display = 'none';
        }
        document.getElementById('confirmModal').style.display = 'flex';
        document.getElementById('confirmCancelBtn').onclick = function () {
            document.getElementById('confirmModal').style.display = 'none';
        };
        document.getElementById('confirmOkBtn').onclick = async function () {
            if (extra) {
                var email = document.getElementById('confirmEmail').value.trim();
                var pass = document.getElementById('confirmPassword').value;
                if (!email || !pass) {
                    document.getElementById('confirmError').style.display = '';
                    document.getElementById('confirmError').textContent = '请填写邮箱和密码';
                    return;
                }
                // Re-authenticate
                try {
                    var authRes = await window._sb.auth.signInWithPassword({ email: email, password: pass });
                    if (authRes.error) throw authRes.error;
                } catch (e) {
                    document.getElementById('confirmError').style.display = '';
                    document.getElementById('confirmError').textContent = '身份验证失败：' + (e.message || '密码错误');
                    return;
                }
            }
            document.getElementById('confirmModal').style.display = 'none';
            if (callback) callback();
        };
    },

    _doFavSync: async function () {
        var btn = document.getElementById('accountSyncBtn');
        btn.disabled = true;
        btn.textContent = '同步中...';
        try {
            await FavoritesSync.pullAndMerge();
            this._updateFavCount();
            btn.textContent = '同步完成 ✓';
        } catch (e) {
            btn.textContent = '同步失败';
        }
        setTimeout(function () { btn.disabled = false; this._updateFavCount(); }.bind(this), 2000);
    },

    _updateFavCount: function () {
        var localFavs = JSON.parse(localStorage.getItem('lof_favorites') || '[]').length;
        var btn = document.getElementById('accountSyncBtn');
        btn.textContent = '同步收藏 (本地 ' + localFavs + ' 只)';
        if (typeof FavoritesSync !== 'undefined') {
            FavoritesSync.getCount().then(function (n) {
                btn.textContent = '同步收藏 (本地 ' + localFavs + ' · 云端 ' + n + ' 只)';
            });
        }
    },

    _destroyAccount: function () {
        var self = this;
        this._showConfirm('注销账户', '此操作不可恢复！所有数据将被永久删除。请通过邮箱和密码确认身份。', true, async function () {
            try {
                // Delete via RPC (server-side function)
                var rpcRes = await window._sb.rpc('delete_own_account');
                if (rpcRes.error) throw rpcRes.error;
                // Clear local state
                var links = document.querySelectorAll('.user-center-link');
                links.forEach(function (l) {
                    l.textContent = '用户中心';
                    l.onclick = function () { if (window.Auth) Auth.open('login'); };
                });
                location.hash = '#/';
                if (window.Auth) Auth._updateUI(null);
            } catch (e) {
                console.error('[Account] Destroy failed:', e.message);
                alert('注销失败：' + (e.message || '未知错误'));
            }
        });
    }
};
