/**
 * app.js — メインアプリケーション + WebSocket管理
 * 
 * 2010年代後半ダークテーマUIのステート管理、テレメトリ受信、
 * スマホHTTP環境（非Secure Context）における安全なフォールバックを完備。
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
    // Notifications (2010s Dark Alert Style)
    // =========================================================================
    notify(message, type = 'info', duration = 3000) {
        const area = document.getElementById('notificationArea');
        if (!area) return;
        const el = document.createElement('div');
        el.className = `notification ${type}`;
        el.textContent = message;
        area.prepend(el);
        setTimeout(() => {
            el.classList.add('fade-out');
            setTimeout(() => el.remove(), 250);
        }, duration);
    },

    // =========================================================================
    // HTTP/Non-Secure Context Safe Clipboard Copy
    // =========================================================================
    copyToClipboard(text) {
        if (!text) return;
        if (window.isSecureContext && navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(text).then(() => {
                this.notify('クリップボードにコピーしました', 'info');
            }).catch(() => {
                this._fallbackCopyText(text);
            });
        } else {
            this._fallbackCopyText(text);
        }
    },

    _fallbackCopyText(text) {
        try {
            const textArea = document.createElement('textarea');
            textArea.value = text;
            textArea.style.position = 'fixed';
            textArea.style.top = '-9999px';
            textArea.style.left = '-9999px';
            textArea.style.opacity = '0';
            document.body.appendChild(textArea);
            textArea.focus();
            textArea.select();
            const ok = document.execCommand('copy');
            document.body.removeChild(textArea);
            if (ok) {
                this.notify('クリップボードにコピーしました', 'info');
            } else {
                prompt('内容をコピーしてください (Ctrl+C / 選択コピー):', text);
            }
        } catch (_) {
            prompt('内容をコピーしてください (Ctrl+C / 選択コピー):', text);
        }
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
            const wsStatus = document.getElementById('footerWsStatus');
            if (wsStatus) {
                wsStatus.textContent = '接続済';
                wsStatus.className = 'stat-value text-success';
            }
            
            // 接続時にPashatoku設定を送信
            const userInp = document.getElementById('qrUserName');
            const studentInp = document.getElementById('qrStudentId');
            if (userInp && studentInp) {
                this.wsSend({ type: 'pashatoku_creds', user_name: userInp.value, student_id: studentInp.value });
            }
        };
        this.ws.onmessage = (e) => this._handleWSMessage(JSON.parse(e.data));
        this.ws.onclose = () => {
            console.log('WS control disconnected');
            const wsStatus = document.getElementById('footerWsStatus');
            if (wsStatus) {
                wsStatus.textContent = '切断';
                wsStatus.className = 'stat-value text-muted';
            }
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
                if (typeof QRManager !== 'undefined') QRManager.loadLinks();
            } else {
                this.notify('Tello の接続に失敗しました', 'error');
            }
        } else if (type === 'disconnect_response') {
            this.connected = false;
            this.flying = false;
            this._updateConnectionUI(false);
            this._resetTelemetryUI();
            this.notify('Tello から切断しました', 'info');
            // 切断時にネットワークインターフェースを自動再検出
            this.loadInterfaces();
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
        } else if (type === 'linetrace_response') {
            if (msg.message) {
                this.notify(msg.message, msg.success ? 'info' : 'warning');
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

        this.connected = tello.connected || false;
        this.flying = tello.flying || false;

        if (this.connected) {
            const bat = telemetry.battery || tello.battery || 0;
            const height = telemetry.height || tello.height || 0;
            const temp = telemetry.temp_high || tello.temperature || 0;
            const flightTime = telemetry.flight_time || tello.flight_time || 0;

            const elBat = document.getElementById('valBattery');
            const elHeight = document.getElementById('valHeight');
            const elTemp = document.getElementById('valTemp');
            const elTime = document.getElementById('valTime');
            const elFps = document.getElementById('footerFps');
            const elIp = document.getElementById('footerLocalIp');

            if (elBat) {
                elBat.textContent = `${bat}%`;
                elBat.className = bat <= 20 ? 'value text-danger' : (bat <= 40 ? 'value text-warning' : 'value');
            }
            if (elHeight) elHeight.textContent = `${height}cm`;
            if (elTemp) elTemp.textContent = `${temp}°C`;
            if (elTime) elTime.textContent = `${flightTime}s`;
            if (elFps) elFps.textContent = video.fps || 0;
            const elFpsInline = document.getElementById('footerFpsInline');
            if (elFpsInline) elFpsInline.textContent = `${video.fps || 0} FPS`;
            if (elIp) elIp.textContent = tello.local_ip || '--';

            // LineTrace結果の更新
            if (typeof LineTraceUI !== 'undefined' && lt.detected !== undefined) {
                LineTraceUI.updateResultInfo(lt);
            }
        } else {
            this._resetTelemetryUI();
        }

        this._updateConnectionUI(this.connected);
    },

    _updateStatus(status) {
        if (!status) return;
        this.connected = status.connected;
        this.flying = status.flying;

        if (this.connected) {
            const elBat = document.getElementById('valBattery');
            const elHeight = document.getElementById('valHeight');
            const elTemp = document.getElementById('valTemp');
            const elTime = document.getElementById('valTime');
            const elIp = document.getElementById('footerLocalIp');

            if (elBat) elBat.textContent = `${status.battery || 0}%`;
            if (elHeight) elHeight.textContent = `${status.height || 0}cm`;
            if (elTemp) elTemp.textContent = `${status.temperature || 0}°C`;
            if (elTime) elTime.textContent = `${status.flight_time || 0}s`;
            if (elIp && status.local_ip) elIp.textContent = status.local_ip;
        } else {
            this._resetTelemetryUI();
        }

        this._updateConnectionUI(status.connected);
    },

    _resetTelemetryUI() {
        const elBat = document.getElementById('valBattery');
        const elHeight = document.getElementById('valHeight');
        const elTemp = document.getElementById('valTemp');
        const elTime = document.getElementById('valTime');
        const elFps = document.getElementById('footerFps');
        const elIp = document.getElementById('footerLocalIp');
        const elLt = document.getElementById('ltDetected');

        if (elBat) { elBat.textContent = '--%'; elBat.className = 'value'; }
        if (elHeight) elHeight.textContent = '--cm';
        if (elTemp) elTemp.textContent = '--°C';
        if (elTime) elTime.textContent = '--s';
        if (elFps) elFps.textContent = '0';
        const elFpsInline = document.getElementById('footerFpsInline');
        if (elFpsInline) elFpsInline.textContent = '0 FPS';
        if (elIp) elIp.textContent = '--';
        if (elLt) {
            elLt.textContent = '--';
            elLt.className = 'value text-muted';
        }

        // 映像ストリームもリセット
        VideoManager.hideStream();
    },

    _updateConnectionUI(connected) {
        const dot = document.getElementById('statusDot');
        const text = document.getElementById('statusText');
        const btn = document.getElementById('btnConnect');

        if (connected) {
            if (dot) dot.className = 'status-dot connected';
            if (text) text.textContent = '接続中';
            if (btn) btn.innerHTML = '<i class="fas fa-plug"></i> <span>切断</span>';
        } else {
            if (dot) dot.className = 'status-dot';
            if (text) text.textContent = '切断中';
            if (btn) btn.innerHTML = '<i class="fas fa-plug"></i> <span>接続</span>';
        }
    },

    // =========================================================================
    // Network Interfaces
    // =========================================================================
    async loadInterfaces() {
        const result = await this.api('GET', '/network/interfaces');
        const select = document.getElementById('networkInterface');
        if (!select) return;

        const currentVal = select.value;
        while (select.options.length > 1) select.remove(1);

        if (result.interfaces) {
            result.interfaces.forEach(iface => {
                const opt = document.createElement('option');
                opt.value = iface.ip;
                opt.textContent = `${iface.adapter} (${iface.ip})${iface.is_tello ? ' ★Tello' : ''}`;
                if (iface.is_tello || iface.ip === currentVal) opt.selected = true;
                select.add(opt);
            });
        }
    },

    // =========================================================================
    // フライトログ (Timeline CSV) ダウンロード
    // =========================================================================
    async downloadFlightLog() {
        try {
            const resp = await fetch('/api/logs/latest');
            if (!resp.ok) {
                App.notify('保存されたフライトログがありません', 'warning');
                return;
            }
            const blob = await resp.blob();
            const disposition = resp.headers.get('Content-Disposition');
            let filename = '';
            if (disposition && disposition.indexOf('filename=') !== -1) {
                const matches = /filename[^;=\n]*=((['"]).*?\2|[^;\n]*)/.exec(disposition);
                if (matches != null && matches[1]) {
                    filename = matches[1].replace(/['"]/g, '');
                }
            }
            if (!filename) {
                filename = `TELLO_flight_${Date.now()}.csv`;
            }

            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = filename;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            URL.revokeObjectURL(url);
            App.notify(`フライトログCSVをダウンロードしました (${filename})`, 'success');
        } catch (e) {
            console.error('フライトログダウンロードエラー:', e);
            App.notify('フライトログのダウンロードに失敗しました', 'error');
        }
    }
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
        if (msgEl) {
            msgEl.textContent = result.message || '';
            msgEl.style.display = 'block';
        }

        if (result.newly_stored) {
            App.notify(`QR 保存: ${result.qr_text}`, 'success');
            this.loadLinks();
        } else if (result.already_stored) {
            App.notify(`QR 読込済: ${result.qr_text}`, 'info');
        } else if (!result.qr_detected) {
            App.notify('QRコードが検出されませんでした', 'warning');
        }
    },

    renderLinks(links) {
        const container = document.getElementById('qrLinksList');
        if (!container) return;
        if (!links || Object.keys(links).length === 0) {
            container.innerHTML = '<div class="qr-empty"><i class="fas fa-qrcode"></i><p>保存済みデータはありません</p></div>';
            return;
        }

        container.innerHTML = '';
        for (const [key, data] of Object.entries(links)) {
            const item = document.createElement('div');
            item.className = 'qr-link-item';
            
            let contentHTML = '';
            const safeText = (data.qr_text || '').replace(/"/g, '&quot;');
            if (data.link) {
                contentHTML = `<a href="${data.link}" target="_blank" rel="noopener">${safeText}</a>`;
            } else {
                contentHTML = `<span>${safeText}</span>`;
            }

            item.innerHTML = `
                <div class="qr-text-wrap">${contentHTML}</div>
                <div class="qr-item-actions">
                    <button class="btn btn-xs btn-default" title="コピー" onclick="App.copyToClipboard('${safeText}')">
                        <i class="fas fa-copy"></i>
                    </button>
                    <button class="btn btn-xs btn-danger btn-delete" title="削除" onclick="QRManager.deleteLink('${key}')">
                        <i class="fas fa-trash"></i>
                    </button>
                </div>
            `;
            container.appendChild(item);
        }
    },

    async deleteLink(num) {
        await App.api('DELETE', `/qr/links/${encodeURIComponent(num)}`);
        App.notify(`リンクを削除しました`, 'info');
        this.loadLinks();
    },

    async downloadCSV() {
        const result = await App.api('GET', '/qr/links');
        const links = result.links || {};
        if (Object.keys(links).length === 0) {
            App.notify('ダウンロードするデータがありません', 'warning');
            return;
        }

        let csvContent = "\uFEFF"; // BOM for Excel
        csvContent += "日時,テキスト,URL\n";
        for (const [key, data] of Object.entries(links)) {
            const dt = data.timestamp || "";
            const text = (data.qr_text || "").replace(/"/g, '""');
            const url = (data.link || "").replace(/"/g, '""');
            csvContent += `"${dt}","${text}","${url}"\n`;
        }

        const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.setAttribute("href", url);
        link.setAttribute("download", `qr_data_${Date.now()}.csv`);
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        URL.revokeObjectURL(url);
    },
};

// =========================================================================
// モバイル向けタブマネージャー (PCでは無効化/常時表示)
// =========================================================================
const TabManager = {
    init() {
        const tabBtns = document.querySelectorAll('.mobile-tab-btn');
        if (!tabBtns.length) return;

        tabBtns.forEach(btn => {
            btn.addEventListener('click', () => {
                const targetId = btn.dataset.target;
                tabBtns.forEach(b => b.classList.remove('active'));
                btn.classList.add('active');

                // モバイル表示時のみターゲットパネルの切り替え
                document.querySelectorAll('.tab-panel').forEach(panel => {
                    if (panel.id === targetId) {
                        panel.classList.add('tab-active');
                    } else {
                        panel.classList.remove('tab-active');
                    }
                });
            });
        });
    }
};

// =========================================================================
// Init
// =========================================================================
document.addEventListener('DOMContentLoaded', () => {
    // セキュリティコンテキスト（HTTP環境）の検出と案内
    const isSecure = window.isSecureContext || location.hostname === 'localhost' || location.hostname === '127.0.0.1';
    const securityBadge = document.getElementById('securityNotice');
    if (securityBadge) {
        if (!isSecure) {
            securityBadge.textContent = 'HTTP接続 (ローカル通信)';
            securityBadge.title = 'PCホストによるHTTP環境です。カメラ/センサー等のブラウザ直接利用は制限されますが、ドローン制御・MJPEG映像は正常に機能します。';
            securityBadge.classList.add('visible');
        } else {
            securityBadge.textContent = 'ローカル接続';
        }
    }

    // WebSocket接続
    App.connectWS();

    // ネットワークインターフェース取得
    App.loadInterfaces();

    // QRリンク読み込み
    QRManager.loadLinks();

    // モバイルタブ初期化
    TabManager.init();

    // === Pashatoku 連携設定 ===
    const userInp = document.getElementById('qrUserName');
    const studentInp = document.getElementById('qrStudentId');
    if (userInp && studentInp) {
        userInp.value = localStorage.getItem('qrUserName') || '';
        studentInp.value = localStorage.getItem('qrStudentId') || '';

        const updatePashatokuCreds = () => {
            localStorage.setItem('qrUserName', userInp.value);
            localStorage.setItem('qrStudentId', studentInp.value);
            App.wsSend({ type: 'pashatoku_creds', user_name: userInp.value, student_id: studentInp.value });
        };

        userInp.addEventListener('input', updatePashatokuCreds);
        studentInp.addEventListener('input', updatePashatokuCreds);
    }

    // === Buttons ===
    const btnConnect = document.getElementById('btnConnect');
    if (btnConnect) {
        btnConnect.addEventListener('click', () => {
            if (App.connected) {
                App.wsSend({ type: 'disconnect' });
            } else {
                const ip = document.getElementById('networkInterface').value;
                App.wsSend({ type: 'connect', local_ip: ip });
            }
        });
    }

    const btnTakeoff = document.getElementById('btnTakeoff');
    if (btnTakeoff) {
        btnTakeoff.addEventListener('click', () => {
            App.wsSend({ type: 'takeoff' });
        });
    }

    const btnLand = document.getElementById('btnLand');
    if (btnLand) {
        btnLand.addEventListener('click', () => {
            App.wsSend({ type: 'land' });
        });
    }

    const btnEmergency = document.getElementById('btnEmergency');
    if (btnEmergency) {
        btnEmergency.addEventListener('click', () => {
            if (confirm('緊急停止を実行しますか？モーターが即停止します。')) {
                App.wsSend({ type: 'emergency' });
            }
        });
    }

    const btnVideoStart = document.getElementById('btnVideoStart');
    if (btnVideoStart) {
        btnVideoStart.addEventListener('click', () => {
            App.wsSend({ type: 'video_start' });
        });
    }

    const btnVideoStop = document.getElementById('btnVideoStop');
    if (btnVideoStop) {
        btnVideoStop.addEventListener('click', () => {
            App.wsSend({ type: 'video_stop' });
            VideoManager.hideStream();
        });
    }

    const btnScreenshot = document.getElementById('btnScreenshot');
    if (btnScreenshot) {
        btnScreenshot.addEventListener('click', () => {
            VideoManager.screenshot();
        });
    }

    const btnFlightLog = document.getElementById('btnDownloadFlightLog');
    if (btnFlightLog) {
        btnFlightLog.addEventListener('click', () => {
            App.downloadFlightLog();
        });
    }

    const btnQrScan = document.getElementById('btnQrScan');
    if (btnQrScan) {
        btnQrScan.addEventListener('click', () => {
            QRManager.scan();
        });
    }

    const btnQrRefresh = document.getElementById('btnQrRefresh');
    if (btnQrRefresh) {
        btnQrRefresh.addEventListener('click', () => {
            QRManager.loadLinks();
        });
    }

    const btnQrDownload = document.getElementById('btnQrDownload');
    if (btnQrDownload) {
        btnQrDownload.addEventListener('click', () => {
            QRManager.downloadCSV();
        });
    }

    const btnRefreshInterfaces = document.getElementById('btnRefreshInterfaces');
    if (btnRefreshInterfaces) {
        btnRefreshInterfaces.addEventListener('click', () => {
            App.loadInterfaces();
            App.notify('ネットワークインターフェースを再検出しました', 'info');
        });
    }

    const videoQualityPreset = document.getElementById('videoQualityPreset');
    if (videoQualityPreset) {
        videoQualityPreset.addEventListener('change', (e) => {
            const presets = {
                low: { width: 320, height: 240, quality: 50 },
                medium: { width: 640, height: 480, quality: 80 },
                high: { width: 960, height: 720, quality: 95 },
            };
            const p = presets[e.target.value] || presets.medium;
            App.api('POST', '/video/quality', p);
        });
    }
});
