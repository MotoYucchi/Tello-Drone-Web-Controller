/**
 * app.js — メインアプリケーション + WebSocket管理
 */

// =========================================================================
// グローバル状態
// =========================================================================
const App = {
    ws: null,
    wsTelemetry: null,
    connected: false,
    flying: false,
    videoStreaming: false,

    // API helper
    async api(method, path, body = null) {
        const opts = {
            method,
            headers: { 'Content-Type': 'application/json' },
        };
        if (body) opts.body = JSON.stringify(body);
        try {
            const resp = await fetch(`/api${path}`, opts);
            return await resp.json();
        } catch (e) {
            console.error(`API error: ${path}`, e);
            App.notify(`API エラー: ${e.message}`, 'error');
            return { success: false };
        }
    },

    // =========================================================================
    // Notifications
    // =========================================================================
    notify(message, type = 'info', duration = 3000) {
        const area = document.getElementById('notificationArea');
        const el = document.createElement('div');
        el.className = `notification ${type}`;
        el.textContent = message;
        area.prepend(el);
        setTimeout(() => {
            el.classList.add('fade-out');
            setTimeout(() => el.remove(), 300);
        }, duration);
    },

    // =========================================================================
    // WebSocket
    // =========================================================================
    connectWS() {
        const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
        const base = `${proto}//${location.host}/ws`;

        // Control WS
        this.ws = new WebSocket(`${base}/control`);
        this.ws.onopen = () => {
            console.log('WS control connected');
            document.getElementById('footerWsStatus').textContent = '接続';
        };
        this.ws.onmessage = (e) => this._handleWSMessage(JSON.parse(e.data));
        this.ws.onclose = () => {
            console.log('WS control disconnected');
            document.getElementById('footerWsStatus').textContent = '切断';
            // 自動再接続
            setTimeout(() => this.connectWS(), 3000);
        };
        this.ws.onerror = (e) => console.error('WS error', e);

        // Telemetry WS
        this.wsTelemetry = new WebSocket(`${base}/telemetry`);
        this.wsTelemetry.onmessage = (e) => this._handleTelemetry(JSON.parse(e.data));
    },

    wsSend(msg) {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            this.ws.send(JSON.stringify(msg));
        }
    },

    _handleWSMessage(msg) {
        const type = msg.type;

        if (type === 'status') {
            this._updateStatus(msg.data);
        } else if (type === 'connect_response') {
            if (msg.success) {
                this.connected = true;
                this._updateConnectionUI(true);
                this._updateStatus(msg.status);
                this.notify('Tello に接続しました', 'success');
            } else {
                this.notify('Tello の接続に失敗しました', 'error');
            }
        } else if (type === 'disconnect_response') {
            this.connected = false;
            this.flying = false;
            this._updateConnectionUI(false);
            this.notify('Tello から切断しました', 'info');
        } else if (type === 'takeoff_response') {
            if (msg.success) {
                this.flying = true;
                this.notify('離陸しました', 'success');
            } else {
                this.notify('離陸に失敗しました', 'error');
            }
        } else if (type === 'land_response') {
            if (msg.success) {
                this.flying = false;
                this.notify('着陸しました', 'success');
            }
        } else if (type === 'emergency_response') {
            this.flying = false;
            this.notify('緊急停止を実行しました', 'warning');
        } else if (type === 'keyboard_response') {
            // silent
        } else if (type === 'video_response') {
            if (msg.success) {
                VideoManager.showStream();
            }
        } else if (type === 'linetrace_params') {
            if (typeof LineTraceUI !== 'undefined') {
                LineTraceUI.updateSliders(msg.params);
            }
        } else if (type === 'qr_response') {
            QRManager.handleResult(msg);
        } else if (type === 'error') {
            this.notify(msg.message || 'エラーが発生しました', 'error');
        }
    },

    _handleTelemetry(msg) {
        if (msg.type !== 'telemetry') return;

        const tello = msg.tello || {};
        const telemetry = msg.telemetry || {};
        const video = msg.video || {};
        const lt = msg.linetrace_result || {};

        // Update status values
        this.connected = tello.connected || false;
        this.flying = tello.flying || false;

        const bat = telemetry.battery || tello.battery || 0;
        const height = telemetry.height || tello.height || 0;
        const temp = telemetry.temp_high || tello.temperature || 0;
        const flightTime = telemetry.flight_time || tello.flight_time || 0;

        document.getElementById('valBattery').textContent = `${bat}%`;
        document.getElementById('valHeight').textContent = `${height}cm`;
        document.getElementById('valTemp').textContent = `${temp}°C`;
        document.getElementById('valTime').textContent = `${flightTime}s`;
        document.getElementById('footerFps').textContent = video.fps || 0;
        document.getElementById('footerLocalIp').textContent = tello.local_ip || '--';

        // LineTrace detection status
        if (lt.detected !== undefined) {
            document.getElementById('ltDetected').textContent =
                lt.detected ? `検出中 (area: ${lt.area})` : '未検出';
        }

        this._updateConnectionUI(this.connected);
    },

    _updateStatus(status) {
        if (!status) return;
        this.connected = status.connected;
        this.flying = status.flying;
        document.getElementById('valBattery').textContent = `${status.battery || 0}%`;
        document.getElementById('valHeight').textContent = `${status.height || 0}cm`;
        document.getElementById('valTemp').textContent = `${status.temperature || 0}°C`;
        document.getElementById('valTime').textContent = `${status.flight_time || 0}s`;
        if (status.local_ip) {
            document.getElementById('footerLocalIp').textContent = status.local_ip;
        }
        this._updateConnectionUI(status.connected);
    },

    _updateConnectionUI(connected) {
        const dot = document.getElementById('statusDot');
        const text = document.getElementById('statusText');
        const btn = document.getElementById('btnConnect');

        if (connected) {
            dot.classList.add('connected');
            text.textContent = '接続中';
            btn.innerHTML = '<i class="fas fa-plug"></i><span>切断</span>';
        } else {
            dot.classList.remove('connected');
            text.textContent = '切断中';
            btn.innerHTML = '<i class="fas fa-plug"></i><span>接続</span>';
        }
    },

    // =========================================================================
    // Network Interfaces
    // =========================================================================
    async loadInterfaces() {
        const result = await this.api('GET', '/network/interfaces');
        const select = document.getElementById('networkInterface');
        // Clear existing options except first
        while (select.options.length > 1) select.remove(1);

        if (result.interfaces) {
            result.interfaces.forEach(iface => {
                const opt = document.createElement('option');
                opt.value = iface.ip;
                opt.textContent = `${iface.adapter} (${iface.ip})${iface.is_tello ? ' ★Tello' : ''}`;
                if (iface.is_tello) opt.selected = true;
                select.add(opt);
            });
        }
    },
};

// =========================================================================
// QR Manager
// =========================================================================
const QRManager = {
    async scan() {
        App.wsSend({ type: 'qr_scan' });
    },

    async loadLinks() {
        const result = await App.api('GET', '/qr/links');
        this.renderLinks(result.links || {});
    },

    handleResult(result) {
        const msgEl = document.getElementById('qrMessage');
        msgEl.textContent = result.message || '';
        msgEl.style.display = 'block';

        if (result.newly_stored) {
            App.notify(`QR: ${result.three_digit_number} → リンク保存`, 'success');
            this.loadLinks();
        } else if (result.already_stored) {
            App.notify(`QR: ${result.three_digit_number} は保存済み`, 'info');
        } else if (!result.qr_detected) {
            App.notify('QRコードが検出されませんでした', 'warning');
        }
    },

    renderLinks(links) {
        const container = document.getElementById('qrLinksList');
        if (!links || Object.keys(links).length === 0) {
            container.innerHTML = '<div class="qr-empty"><i class="fas fa-qrcode"></i><p>保存済みリンクはありません</p></div>';
            return;
        }

        container.innerHTML = '';
        for (const [num, data] of Object.entries(links)) {
            const item = document.createElement('div');
            item.className = 'qr-link-item';
            item.innerHTML = `
                <span class="link-number">${num}</span>
                <a href="${data.link}" target="_blank" rel="noopener">${data.link}</a>
                <button class="btn btn-sm btn-danger btn-delete" onclick="QRManager.deleteLink('${num}')">
                    <i class="fas fa-trash"></i>
                </button>
            `;
            container.appendChild(item);
        }
    },

    async deleteLink(num) {
        await App.api('DELETE', `/qr/links/${num}`);
        App.notify(`リンク ${num} を削除しました`, 'info');
        this.loadLinks();
    },
};


// =========================================================================
// Init
// =========================================================================
document.addEventListener('DOMContentLoaded', () => {
    // WebSocket接続
    App.connectWS();

    // ネットワークインターフェース取得
    App.loadInterfaces();

    // QRリンク読み込み
    QRManager.loadLinks();

    // === Buttons ===
    document.getElementById('btnConnect').addEventListener('click', () => {
        if (App.connected) {
            App.wsSend({ type: 'disconnect' });
        } else {
            const ip = document.getElementById('networkInterface').value;
            App.wsSend({ type: 'connect', local_ip: ip });
        }
    });

    document.getElementById('btnTakeoff').addEventListener('click', () => {
        App.wsSend({ type: 'takeoff' });
    });

    document.getElementById('btnLand').addEventListener('click', () => {
        App.wsSend({ type: 'land' });
    });

    document.getElementById('btnEmergency').addEventListener('click', () => {
        if (confirm('緊急停止を実行しますか？モーターが即停止します。')) {
            App.wsSend({ type: 'emergency' });
        }
    });

    document.getElementById('btnVideoStart').addEventListener('click', () => {
        App.wsSend({ type: 'video_start' });
    });

    document.getElementById('btnVideoStop').addEventListener('click', () => {
        App.wsSend({ type: 'video_stop' });
        VideoManager.hideStream();
    });

    document.getElementById('btnScreenshot').addEventListener('click', () => {
        VideoManager.screenshot();
    });

    document.getElementById('btnQrScan').addEventListener('click', () => {
        QRManager.scan();
    });

    document.getElementById('btnQrRefresh').addEventListener('click', () => {
        QRManager.loadLinks();
    });

    document.getElementById('btnRefreshInterfaces').addEventListener('click', () => {
        App.loadInterfaces();
    });

    document.getElementById('videoQualityPreset').addEventListener('change', (e) => {
        const presets = {
            low: { width: 320, height: 240, quality: 50 },
            medium: { width: 640, height: 480, quality: 80 },
            high: { width: 960, height: 720, quality: 95 },
        };
        const p = presets[e.target.value] || presets.medium;
        App.api('POST', '/video/quality', p);
    });
});
