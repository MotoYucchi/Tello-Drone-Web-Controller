/**
 * linetrace.js — LineTrace UI制御
 *
 * HSVスライダーの値を管理し、WebSocket経由でLineTraceエンジンのパラメータを更新する。
 */

const LineTraceUI = {
    // スライダーIDとパラメータ名のマッピング
    sliders: {
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
        // Toggle
        document.getElementById('toggleLineTrace').addEventListener('change', (e) => {
            if (e.target.checked) {
                App.wsSend({ type: 'linetrace_start' });
                App.notify('LineTrace 開始', 'info');
            } else {
                App.wsSend({ type: 'linetrace_stop' });
                App.notify('LineTrace 停止', 'info');
            }
        });

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
        }, 150);
    },

    _sendParams() {
        const params = {};
        for (const [sliderId, paramName] of Object.entries(this.sliders)) {
            const slider = document.getElementById(sliderId);
            if (slider) {
                params[paramName] = parseInt(slider.value, 10);
            }
        }
        App.wsSend({ type: 'linetrace_params', params });
    },

    /**
     * サーバーから受け取ったパラメータでスライダーを更新
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
        // Toggle state
        const toggle = document.getElementById('toggleLineTrace');
        if (params.active !== undefined && toggle) {
            toggle.checked = params.active;
        }
    },
};

// Init
document.addEventListener('DOMContentLoaded', () => {
    LineTraceUI.init();
});
