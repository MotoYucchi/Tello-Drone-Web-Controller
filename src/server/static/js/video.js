/**
 * video.js — 映像管理＆静止画撮影
 */

const VideoManager = {
    streamImg: null,
    overlay: null,

    init() {
        this.streamImg = document.getElementById('videoStream');
        this.overlay = document.getElementById('videoOverlay');
    },

    showStream() {
        if (!this.streamImg || !this.overlay) this.init();
        
        const toggle = document.getElementById('toggleVideoMode');
        const isLineTrace = toggle && toggle.checked;

        if (isLineTrace) {
            this.streamImg.src = '/linetrace_stream?' + Date.now();
        } else {
            this.streamImg.src = '/video_stream?' + Date.now();
        }
        
        this.streamImg.style.display = 'block';
        this.overlay.classList.add('hidden');
        App.videoStreaming = true;
    },

    hideStream() {
        if (!this.streamImg || !this.overlay) this.init();
        this.streamImg.src = '';
        this.streamImg.style.display = 'none';
        this.overlay.classList.remove('hidden');
        App.videoStreaming = false;
        
        const toggle = document.getElementById('toggleVideoMode');
        if (toggle) toggle.checked = false;
    },

    toggleMode(isLineTrace) {
        if (!App.videoStreaming || !this.streamImg) return;
        if (isLineTrace) {
            this.streamImg.src = '/linetrace_stream?' + Date.now();
        } else {
            this.streamImg.src = '/video_stream?' + Date.now();
        }
    },

    async screenshot() {
        if (!App.videoStreaming && (!this.streamImg || !this.streamImg.src)) {
            App.notify('映像ストリーミングが開始されていません', 'warning');
            return;
        }

        try {
            // バックエンドAPIから高画質PNGを直接ダウンロード
            const resp = await fetch('/api/screenshot');
            if (resp.ok) {
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
                    const d = new Date();
                    const pad = (n) => String(n).padStart(2, '0');
                    const ts = `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}-${pad(d.getHours())}-${pad(d.getMinutes())}-${pad(d.getSeconds())}`;
                    filename = `TELLO_${ts}.png`;
                }

                const url = URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = filename;
                document.body.appendChild(a);
                a.click();
                document.body.removeChild(a);
                URL.revokeObjectURL(url);
                App.notify(`静止画を保存しました (${filename})`, 'success');
                return;
            }
        } catch (e) {
            console.warn('API経由のスクリーンショット失敗、Canvasフォールバックを実行:', e);
        }

        // フォールバック: CanvasからPNGとして保存
        if (!this.streamImg || !this.streamImg.naturalWidth) {
            App.notify('静止画キャプチャに失敗しました', 'error');
            return;
        }

        const canvas = document.createElement('canvas');
        canvas.width = this.streamImg.naturalWidth || 640;
        canvas.height = this.streamImg.naturalHeight || 480;
        const ctx = canvas.getContext('2d');
        ctx.drawImage(this.streamImg, 0, 0);

        canvas.toBlob((blob) => {
            if (!blob) return;
            const d = new Date();
            const pad = (n) => String(n).padStart(2, '0');
            const ts = `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}-${pad(d.getHours())}-${pad(d.getMinutes())}-${pad(d.getSeconds())}`;
            const filename = `TELLO_${ts}.png`;

            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = filename;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            URL.revokeObjectURL(url);
            App.notify(`静止画を保存しました (${filename})`, 'success');
        }, 'image/png');
    },

    async resetBuffer() {
        if (!App.videoStreaming) {
            App.notify('映像ストリーミングが開始されていません', 'info');
            return;
        }
        try {
            App.wsSend({ type: 'video_reset_buffer' });
            const res = await App.api('POST', '/video/reset_buffer');
            if (res && res.success) {
                App.notify(res.message || '遅延をリセットし、最新映像に同期しました', 'success', 2000);
                if (this.streamImg) {
                    const baseSrc = this.streamImg.src.split('?')[0];
                    this.streamImg.src = `${baseSrc}?${Date.now()}`;
                }
            } else {
                App.notify(res.message || '遅延リセットに失敗しました', 'warning');
            }
        } catch (e) {
            console.error('遅延リセットエラー:', e);
            App.notify('遅延リセットエラー', 'error');
        }
    },

    async setLatencyMode(val) {
        const drainRate = parseInt(val, 10);
        const lowLat = drainRate > 0;
        App.wsSend({ type: 'video_latency', low_latency: lowLat, drain_rate: drainRate });
        await App.api('POST', '/video/latency', { low_latency: lowLat, drain_rate: drainRate });
        App.notify(`遅延モード変更: ${drainRate === 1 ? '低遅延(推奨)' : (drainRate === 2 ? '積極ドロップ' : 'バッファ維持')}`, 'info', 1500);
    },
};

// Init
document.addEventListener('DOMContentLoaded', () => {
    VideoManager.init();

    const toggle = document.getElementById('toggleVideoMode');
    if (toggle) {
        toggle.addEventListener('change', (e) => {
            VideoManager.toggleMode(e.target.checked);
        });
    }

    const btnReset = document.getElementById('btnResetVideoBuffer');
    if (btnReset) {
        btnReset.addEventListener('click', () => {
            VideoManager.resetBuffer();
        });
    }

    const latencySelect = document.getElementById('videoLatencyMode');
    if (latencySelect) {
        latencySelect.addEventListener('change', (e) => {
            VideoManager.setLatencyMode(e.target.value);
        });
    }
});
