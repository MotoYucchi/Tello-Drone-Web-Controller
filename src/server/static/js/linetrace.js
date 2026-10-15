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
        'ltCornerForwardSpeed': 'corner_forward_speed',
        'ltCornerBackSpeed': 'corner_recovery_back_speed',
        'ltCornerMemorySec': 'corner_memory_sec',
    },

    _sendTimeout: null,

    init() {
        // Toggle Experimental Features
        const toggleExp = document.getElementById('toggleExperimental');

        if (toggleExp) {
            toggleExp.addEventListener('change', async (e) => {
                const endpoint = e.target.checked ? '/api/experimental/enable' : '/api/experimental/disable';
                try {
                    const res = await App.api('POST', endpoint.replace('/api', ''));
                    this.setExperimentalState(e.target.checked);
                    if (e.target.checked) {
                        App.notify('試験的機能を有効化しました (10Hz高頻度ログ・周回記録)', 'success');
                    } else {
                        App.notify('試験的機能を無効化しクリーンリセットしました', 'info');
                    }
                } catch (err) {
                    console.error('試験的機能切替エラー:', err);
                }
            });
        }

        // Course Type Selection
        const courseSelect = document.getElementById('ltCourseType');
        if (courseSelect) {
            courseSelect.addEventListener('change', async (e) => {
                try {
                    await App.api('POST', '/linetrace/course', { course_type: e.target.value });
                    const label = e.target.value === 'square' ? '四角コース' : 'その他コース';
                    App.notify(`コース設定変更: ${label} (周回リセット)`, 'info');
                } catch (err) {
                    console.error('コース設定エラー:', err);
                }
            });
        }

        // Reset Laps Button
        const btnResetLaps = document.getElementById('btnResetLaps');
        if (btnResetLaps) {
            btnResetLaps.addEventListener('click', async () => {
                try {
                    await App.api('POST', '/linetrace/reset_laps');
                    App.notify('周回数カウンターをリセットしました', 'info');
                } catch (err) {
                    console.error('周回リセットエラー:', err);
                }
            });
        }

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

                const rowCorner = document.getElementById('rowCornerRecovery');
                if (rowCorner) {
                    rowCorner.style.display = mode === 'standard' ? 'flex' : 'none';
                }
                const rowMemory = document.getElementById('rowCornerMemory');
                if (rowMemory) {
                    rowMemory.style.display = mode === 'standard' ? 'flex' : 'none';
                }
            });
        }


        // Checkboxes
        const chkBacktrack = document.getElementById('ltLostBacktrack');
        if (chkBacktrack) {
            chkBacktrack.addEventListener('change', () => this._sendParams());
        }
        const chkAutoRotate = document.getElementById('ltLostAutoRotate');
        if (chkAutoRotate) {
            chkAutoRotate.addEventListener('change', () => this._sendParams());
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
                valueEl.textContent = sliderId === 'ltCornerMemorySec' ? `${slider.value}s` : slider.value;
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
                params[paramName] = sliderId === 'ltCornerMemorySec' ? parseFloat(slider.value) : parseInt(slider.value, 10);
            }
        }
        const cameraModeSelect = document.getElementById('ltCameraMode');
        if (cameraModeSelect) {
            params['camera_mode'] = cameraModeSelect.value;
        }

        const chkBacktrack = document.getElementById('ltLostBacktrack');
        if (chkBacktrack) {
            params['lost_backtrack'] = chkBacktrack.checked;
        }
        const chkAutoRotate = document.getElementById('ltLostAutoRotate');
        if (chkAutoRotate) {
            params['lost_auto_rotate'] = chkAutoRotate.checked;
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
                if (valueEl) {
                    valueEl.textContent = sliderId === 'ltCornerMemorySec' ? `${Math.round(params[paramName])}s` : params[paramName];
                }
            }
        }

        if (params.lost_backtrack !== undefined) {
            const chk = document.getElementById('ltLostBacktrack');
            if (chk) chk.checked = !!params.lost_backtrack;
        }
        if (params.lost_auto_rotate !== undefined) {
            const chk = document.getElementById('ltLostAutoRotate');
            if (chk) chk.checked = !!params.lost_auto_rotate;
        }

        // Camera mode
        if (params.camera_mode !== undefined) {
            const cameraModeSelect = document.getElementById('ltCameraMode');
            if (cameraModeSelect) cameraModeSelect.value = params.camera_mode;
            const rowCorner = document.getElementById('rowCornerRecovery');
            if (rowCorner) {
                rowCorner.style.display = params.camera_mode === 'standard' ? 'flex' : 'none';
            }
            const rowMemory = document.getElementById('rowCornerMemory');
            if (rowMemory) {
                rowMemory.style.display = params.camera_mode === 'standard' ? 'flex' : 'none';
            }
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
            let text = `追従中 (dx:${result.offset_dx > 0 ? '+' : ''}${Math.round(result.offset_dx)}px, ${Math.round(result.angle_deg)}°)`;
            if (result.is_corner) {
                text += ` [直角:${result.corner_dir === 'right' ? '右' : '左'}]`;
            }
            el.textContent = text;
            el.style.color = '#4ade80'; // 明るいグリーン
        } else if (result.tracking_state === 'searching') {
            el.textContent = result.status_message || 'ライン自動探索中...';
            el.style.color = '#facc15'; // 警告イエロー
        } else if (result.tracking_state === 'stabilizing') {
            el.textContent = '姿勢安定化中 (ホバリング)';
            el.style.color = '#38bdf8'; // スカイブルー
        } else if (result.tracking_state === 'lost') {
            el.textContent = 'ライン見失い (ホバリング待機)';
            el.style.color = '#f87171'; // 注意レッド
        } else {
            el.textContent = '未検出';
            el.style.color = 'var(--text-muted)';
        }

        // 周回数＆ラップタイム表示の更新
        const elLap = document.getElementById('ltLapCountVal');
        if (elLap && result.lap_count !== undefined) {
            elLap.innerHTML = `${result.lap_count}<span style="font-size:11px;">周</span>`;
        }

        const elCorner = document.getElementById('ltCornerProgressVal');
        if (elCorner && result.corner_pass_count !== undefined) {
            elCorner.textContent = `${result.corner_pass_count}/4`;
        }

        const elCurrLap = document.getElementById('ltCurrentLapVal');
        if (elCurrLap && result.current_lap_sec !== undefined) {
            elCurrLap.innerHTML = `${result.current_lap_sec.toFixed(1)}<span style="font-size:11px;">s</span>`;
        }

        const elLastLap = document.getElementById('ltLastLapVal');
        if (elLastLap) {
            if (result.last_lap_sec && result.last_lap_sec > 0) {
                elLastLap.innerHTML = `${result.last_lap_sec.toFixed(1)}<span style="font-size:11px;">s</span>`;
            } else {
                elLastLap.innerHTML = `--<span style="font-size:11px;">s</span>`;
            }
        }

        // コース種別のUI反映
        if (result.course_type !== undefined) {
            const courseSelect = document.getElementById('ltCourseType');
            if (courseSelect && courseSelect.value !== result.course_type) {
                courseSelect.value = result.course_type;
            }
        }
    },

    /**
     * 試験的機能の表示状態を同期
     */
    setExperimentalState(enabled) {
        const toggleExp = document.getElementById('toggleExperimental');
        if (toggleExp) toggleExp.checked = !!enabled;

        const panel = document.getElementById('panel-linetrace');
        if (panel) {
            panel.style.display = enabled ? 'block' : 'none';
        }

        const mobileTab = document.querySelector('.mobile-tab-btn[data-target="panel-linetrace"]');
        if (mobileTab) {
            mobileTab.style.display = enabled ? 'inline-flex' : 'none';
        }
    }
};


// Init
document.addEventListener('DOMContentLoaded', () => {
    LineTraceUI.init();
});
