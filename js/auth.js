/**
 * 金快查 - 用户认证模块
 */

var Auth = {
    _modal: null,

    init: function () {
        var self = this;
        this._modal = document.getElementById('authModal');
        if (!this._modal) return;

        // 关闭按钮
        document.getElementById('authCloseBtn').addEventListener('click', function () {
            self.close();
        });

        // 邮件提示弹窗
        var emailSentModal = document.getElementById('emailSentModal');
        document.getElementById('emailSentClose').addEventListener('click', function () {
            emailSentModal.style.display = 'none';
        });
        document.getElementById('emailSentOkBtn').addEventListener('click', function () {
            emailSentModal.style.display = 'none';
        });

        // 切换表单
        this._bindSwitch('switchToRegister', 'register');
        this._bindSwitch('switchToLogin', 'login');
        this._bindSwitch('switchToReset', 'reset');
        this._bindSwitch('switchToLoginFromReset', 'login');

        // 提交
        document.getElementById('authLoginBtn').addEventListener('click', function () { self._login(); });
        document.getElementById('authRegisterBtn').addEventListener('click', function () { self._register(); });
        document.getElementById('authResetBtn').addEventListener('click', function () { self._resetPassword(); });

        // Enter 提交
        this._modal.addEventListener('keydown', function (e) {
            if (e.key !== 'Enter') return;
            var loginVisible = document.getElementById('authFormLogin').style.display !== 'none';
            var regVisible = document.getElementById('authFormRegister').style.display !== 'none';
            var resetVisible = document.getElementById('authFormReset').style.display !== 'none';
            if (loginVisible) self._login();
            else if (regVisible) self._register();
            else if (resetVisible) self._resetPassword();
        });

        // 监听 Supabase 就绪（可能已经就绪了）
        if (window._sb) {
            self._restoreSession();
        } else {
            document.addEventListener('sb:ready', function () {
                self._restoreSession();
            });
        }
    },

    _whenReady: function (cb) {
        if (window._sb) { cb(); return; }
        document.addEventListener('sb:ready', cb, { once: true });
    },

    open: function (mode) {
        mode = mode || 'login';
        var self = this;
        if (this._modal) {
            this._modal.style.display = 'flex';
            document.body.style.overflow = 'hidden';
        }
        this._showForm(mode);
        if (mode === 'login') {
            // 恢复记住的邮箱和密码
            var savedEmail = localStorage.getItem('sb_remember_email');
            if (savedEmail) {
                document.getElementById('authEmail').value = savedEmail;
                var savedPwd = localStorage.getItem('sb_remember_pwd');
                if (savedPwd) {
                    document.getElementById('authPassword').value = savedPwd;
                    document.getElementById('authRemember').checked = true;
                }
            }
        }
    },

    close: function () {
        if (this._modal) {
            this._modal.style.display = 'none';
            document.body.style.overflow = '';
        }
        this._clearErrors();
    },

    openIfNotLoggedIn: function () {
        var self = this;
        this._whenReady(function () {
            if (self._session()) {
                location.hash = '#/account';
            } else {
                self.open('login');
            }
        });
    },

    logout: async function () {
        if (window._sb) {
            await window._sb.auth.signOut();
        }
        localStorage.removeItem('sb_remember_pwd');
        this._updateUI(null);
        this.close();
    },

    // ── 内部 ──

    _session: function () {
        return window._sb ? window._sb.auth.session : null;
    },

    _showForm: function (form) {
        document.getElementById('authFormLogin').style.display = form === 'login' ? '' : 'none';
        document.getElementById('authFormRegister').style.display = form === 'register' ? '' : 'none';
        document.getElementById('authFormReset').style.display = form === 'reset' ? '' : 'none';
        document.getElementById('authModalTitle').textContent =
            form === 'register' ? '注册' : form === 'reset' ? '重置密码' : '登录';
        this._clearErrors();
    },

    _bindSwitch: function (btnId, formName) {
        var self = this;
        var btn = document.getElementById(btnId);
        if (btn) btn.addEventListener('click', function (e) { e.preventDefault(); self._showForm(formName); });
    },

    _clearErrors: function () {
        var els = ['authError', 'regError', 'regSuccess', 'resetError', 'resetMsg'];
        for (var i = 0; i < els.length; i++) {
            var el = document.getElementById(els[i]);
            if (el) el.style.display = 'none';
        }
    },

    _showError: function (id, msg) {
        var el = document.getElementById(id);
        if (el) { el.textContent = msg; el.style.display = ''; }
    },

    _login: async function () {
        var email = document.getElementById('authEmail').value.trim();
        var pass = document.getElementById('authPassword').value;
        if (!email || !pass) { this._showError('authError', '请填写邮箱和密码'); return; }
        var btn = document.getElementById('authLoginBtn');
        btn.disabled = true; btn.textContent = '登录中...';
        try {
            var res = await window._sb.auth.signInWithPassword({ email: email, password: pass });
            if (res.error) throw res.error;
            // 记住邮箱
            localStorage.setItem('sb_remember_email', email);
            // 记住密码
            var remember = document.getElementById('authRemember');
            if (remember && remember.checked) {
                localStorage.setItem('sb_remember_pwd', pass);
            } else {
                localStorage.removeItem('sb_remember_pwd');
            }
            this._updateUI(res.data.user);
            this.close();
            // 登录后同步收藏和设置
            if (typeof FavoritesSync !== 'undefined') FavoritesSync.pullAndMerge();
            if (typeof SettingsSync !== 'undefined') SettingsSync.pullFromCloud();
            location.hash = '#/account';
        } catch (e) {
            this._showError('authError', e.message || '登录失败');
        }
        btn.disabled = false; btn.textContent = '登录';
    },

    _register: async function () {
        var email = document.getElementById('regEmail').value.trim();
        var pass = document.getElementById('regPassword').value;
        var pass2 = document.getElementById('regPasswordConfirm').value;
        if (!email || !pass) { this._showError('regError', '请填写邮箱和密码'); return; }
        if (pass.length < 6) { this._showError('regError', '密码至少6位'); return; }
        if (pass !== pass2) { this._showError('regError', '两次密码输入不一致'); return; }
        var btn = document.getElementById('authRegisterBtn');
        btn.disabled = true; btn.textContent = '注册中...';
        var self = this;
        try {
            var res = await window._sb.auth.signUp({ email: email, password: pass });
            // Check for error (e.g. already registered)
            if (res.error) {
                var msg = (res.error.message || '').toLowerCase();
                if (msg.indexOf('already') >= 0 || msg.indexOf('registered') >= 0) {
                    self._showError('regError', '该邮箱已被注册');
                } else {
                    self._showError('regError', res.error.message || '注册失败');
                }
            } else if (res.data.user && res.data.user.identities && res.data.user.identities.length === 0) {
                self._showError('regError', '该邮箱已被注册');
            } else {
                // 注册成功，需要邮件验证激活
                self._showError('regError', '');
                document.getElementById('regSuccess').style.display = '';
                // 2秒后关闭注册弹窗，弹出邮件提示
                setTimeout(function () {
                    self.close();
                    document.getElementById('emailSentModal').style.display = 'flex';
                }, 2000);
            }
        } catch (e) {
            self._showError('regError', e.message || '注册失败');
        }
        btn.disabled = false; btn.textContent = '注册';
    },

    _resetPassword: async function () {
        var email = document.getElementById('resetEmail').value.trim();
        if (!email) { this._showError('resetError', '请输入邮箱'); return; }
        var btn = document.getElementById('authResetBtn');
        btn.disabled = true; btn.textContent = '发送中...';
        try {
            var redirectTo = location.origin + location.pathname;
            var res = await window._sb.auth.resetPasswordForEmail(email, { redirectTo: redirectTo });
            if (res.error) throw res.error;
            var msg = document.getElementById('resetMsg');
            if (msg) { msg.style.display = ''; msg.textContent = '重置链接已发送，请查收邮件'; }
            document.getElementById('resetError').style.display = 'none';
        } catch (e) {
            this._showError('resetError', e.message || '发送失败');
        }
        btn.disabled = false; btn.textContent = '发送重置链接';
    },

    _restoreSession: async function () {
        try {
            var res = await window._sb.auth.getSession();
            if (res.data && res.data.session) {
                this._updateUI(res.data.session.user);
                if (typeof FavoritesSync !== 'undefined') FavoritesSync.pullAndMerge();
                if (typeof SettingsSync !== 'undefined') SettingsSync.pullFromCloud();
                return;
            }
        } catch (e) { /* no session */ }
        // 没有 Supabase session，尝试用记住的密码自动登录
        var savedEmail = localStorage.getItem('sb_remember_email');
        var savedPwd = localStorage.getItem('sb_remember_pwd');
        if (savedEmail && savedPwd) {
            try {
                var loginRes = await window._sb.auth.signInWithPassword({ email: savedEmail, password: savedPwd });
                if (loginRes.data && loginRes.data.user) {
                    this._updateUI(loginRes.data.user);
                    if (typeof FavoritesSync !== 'undefined') FavoritesSync.pullAndMerge();
                    if (typeof SettingsSync !== 'undefined') SettingsSync.pullFromCloud();
                }
            } catch (e) { /* auto-login failed */ }
        }
    },

    _updateUI: function (user) {
        // 导航页
        var landingLink = document.querySelector('#view-landing .user-center-link');
        if (landingLink) {
            if (user) {
                landingLink.textContent = user.email;
                landingLink.title = '进入用户中心';
                landingLink.style.cursor = 'pointer';
                landingLink.onclick = function () { location.hash = '#/account'; };
            } else {
                landingLink.textContent = '用户中心';
                landingLink.title = '登录/注册';
                landingLink.style.cursor = 'pointer';
                landingLink.onclick = function () { Auth.open('login'); };
            }
        }
    }
};

Auth.init();
