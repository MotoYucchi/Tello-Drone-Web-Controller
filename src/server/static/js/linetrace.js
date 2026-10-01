/**
 * linetrace.js — LineTrace UI制御
 *
 * HSVスライダー、ガウシアン平滑化、機体カメラモードの値を管理し、
 * WebSocket経由でLineTraceエンジンのパラメータを更新する。
 */

const LineTraceUI = {
    // スライダーIDとパラメータ名のマッピング
    sliders: {
        'ltGaussian': 'gaussian_ksize',
        'ltHMin': 'h_min',
        'ltHMax': 'h_max',
        'ltSMin': 's_min',
        'ltSMax': 's_max',
        'ltVMin': 'v_min',
        'ltVMax': 'v_max',
        'ltSpeed': 'forward_speed',
    },

    _sendTimeout: null,

    init() {
        // Toggle LineTrace
        const toggle = document.getElementById('toggleLineTrace');
        if (toggle) {
            toggle.addEventListener('change', (e) => {
                if (e.target.checked) {
                    App.wsSend({ type: 'linetrace_start' });
                    App.notify('LineTrace (LSD) 開始', 'info');
                } else {
                    App.wsSend({ type: 'linetrace_stop' });
                    App.notify('LineTrace 停止', 'info');
                }
            });
        }

        // Camera Mode
        const cameraModeSelect = document.getElementById('ltCameraMode');
        if (cameraModeSelect) {
            cameraModeSelect.addEventListener('change', (e) => {
                const mode = e.target.value;
                App.wsSend({
                    type: 'linetrace_params',
                    params: { camera_mode: mode }
                });
                const modeName = mode === 'downward' ? '改造機体(ほぼ真下カメラ)' : '通常機体(前方微下向きカメラ)';
                App.notify(`機体カメラモード変更: ${modeName}`, 'info');
            });
        }

        // Presets
        document.querySelectorAll('.preset-btn[data-preset]').forEach(btn => {
            btn.addEventListener('click', () => {
                const preset = btn.dataset.preset;
                App.wsSend({ type: 'linetrace_preset', preset });
                // UI active state
                document.querySelectorAll('.preset-btn').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                App.notify(`色プリセット: ${preset}`, 'info');
            });
        });

        // Sliders
        for (const [sliderId, paramName] of Object.entries(this.sliders)) {
            const slider = document.getElementById(sliderId);
            const valueEl = document.getElementById(sliderId + 'Val');
            if (!slider || !valueEl) continue;

            slider.addEventListener('input', () => {
                valueEl.textContent = slider.value;
                this._debounceSendParams();
            });
        }
    },

    _debounceSendParams() {
        clearTimeout(this._sendTimeout);
        this._sendTimeout = setTimeout(() => {
            this._sendParams();
        }, 120);
    },

    _sendParams() {
        const params = {};
        for (const [sliderId, paramName] of Object.entries(this.sliders)) {
            const slider = document.getElementById(sliderId);
            if (slider) {
                params[paramName] = parseInt(slider.value, 10);
            }
        }
        const cameraModeSelect = document.getElementById('ltCameraMode');
        if (cameraModeSelect) {
            params['camera_mode'] = cameraModeSelect.value;
        }

        App.wsSend({ type: 'linetrace_params', params });
    },

    /**
     * サーバーから受け取ったパラメータでUIを更新
     */
    updateSliders(params) {
        if (!params) return;
        for (const [sliderId, paramName] of Object.entries(this.sliders)) {
            if (params[paramName] !== undefined) {
                const slider = document.getElementById(sliderId);
                const valueEl = document.getElementById(sliderId + 'Val');
                if (slider) slider.value = params[paramName];
                if (valueEl) valueEl.textContent = params[paramName];
            }
        }

        // Camera mode
        if (params.camera_mode !== undefined) {
            const cameraModeSelect = document.getElementById('ltCameraMode');
            if (cameraModeSelect) cameraModeSelect.value = params.camera_mode;
        }

        // Toggle state
        const toggle = document.getElementById('toggleLineTrace');
        if (params.active !== undefined && toggle) {
            toggle.checked = params.active;
        }
    },

    /**
     * 検出結果の表示更新
     */
    updateResultInfo(result) {
        const el = document.getElementById('ltDetected');
        if (!el || !result) return;

        if (result.detected) {
            let text = `検出中 (dx:${result.offset_dx > 0 ? '+' : ''}${Math.round(result.offset_dx)}px, ${Math.round(result.angle_deg)}°)`;
            if (result.is_corner) {
                text += ` [直角:${result.corner_dir === 'right' ? '右' : '左'}]`;
            }
            el.textContent = text;
            el.style.color = '#4ade80'; // green
        } else {
            el.textContent = '未検出';
            el.style.color = 'var(--text-muted)';
        }
    }
};

// Init
document.addEventListener('DOMContentLoaded', () => {
    LineTraceUI.init();
});
