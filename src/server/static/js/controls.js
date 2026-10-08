/**
 * controls.js — キーボード操作 & タッチ・バーチャルコントローラー操作
 * 
 * PCのキーボード操作に加え、スマートフォンやタブレットでのオンスクリーン操作
 * （タッチパッド/バーチャルD-pad/各キーの長押し操作）に対応。
 * HTTP環境（非Secure Context）でも安全に動作するよう配慮。
 */

const Controls = {
    pressedKeys: new Set(),
    enabled: true,

    // RC制御キーマッピング
    RC_KEYS: new Set(['w', 's', 'a', 'd', 'q', 'e', 'r', 'f']),
    // 単発キー
    SINGLE_KEYS: new Set(['t', 'l', ' ']),

    init() {
        // キーボードイベント
        document.addEventListener('keydown', (e) => this._onKeyDown(e));
        document.addEventListener('keyup', (e) => this._onKeyUp(e));

        // タッチ / ポインターイベント（画面上のキーボードガイドおよび仮想コントローラー）
        this._bindTouchControls();

        // ウィンドウのフォーカス喪失時（タブ切り替えや画面ロックなど）に安全停止
        window.addEventListener('blur', () => this.releaseAll());
    },

    /**
     * すべてのキー/ボタンの押下状態を解除（安全停止）
     */
    releaseAll() {
        for (const key of this.pressedKeys) {
            App.wsSend({ type: 'keyboard', action: 'release', key });
            this._highlightKey(key, false);
        }
        this.pressedKeys.clear();
    },

    _normalizeKey(e) {
        // e.code を優先（物理キー判定: 日本語IME・全角モード・CapsLockの影響を完全に排除）
        const codeMap = {
            'KeyW': 'w', 'KeyS': 's', 'KeyA': 'a', 'KeyD': 'd',
            'KeyQ': 'q', 'KeyE': 'e', 'KeyR': 'r', 'KeyF': 'f',
            'KeyT': 't', 'KeyL': 'l', 'Space': 'space'
        };
        if (e.code && codeMap[e.code]) {
            return codeMap[e.code];
        }
        // フォールバック: e.key
        const k = (e.key || '').toLowerCase();
        if (k === ' ' || k === 'space') return 'space';
        if (k === 'ｔ') return 't';
        if (k === 'ｌ') return 'l';
        if (k === 'ｗ') return 'w';
        if (k === 'ｓ') return 's';
        if (k === 'ａ') return 'a';
        if (k === 'ｄ') return 'd';
        if (k === 'ｑ') return 'q';
        if (k === 'ｅ') return 'e';
        if (k === 'ｒ') return 'r';
        if (k === 'ｆ') return 'f';
        return k;
    },

    _onKeyDown(e) {
        if (!this.enabled) return;
        // 入力フォームでの文字入力中はキーボード操縦を無効化 (スライダーやボタンは操縦可能)
        if (e.target.tagName === 'TEXTAREA' || (e.target.tagName === 'INPUT' && ['text', 'search', 'password', 'email', 'number'].includes(e.target.type))) {
            return;
        }

        const normKey = this._normalizeKey(e);

        // 単発キー (t: 離陸, l: 着陸, space: 緊急停止)
        if (this.SINGLE_KEYS.has(normKey) || normKey === 'space') {
            e.preventDefault();
            this.triggerSingle(normKey);
            return;
        }

        // RC制御キー（長押しリピート時の二重送信を防止）
        if (this.RC_KEYS.has(normKey) && !this.pressedKeys.has(normKey)) {
            e.preventDefault();
            this.pressKey(normKey);
        }
    },

    _onKeyUp(e) {
        if (!this.enabled) return;
        const normKey = this._normalizeKey(e);

        if (this.RC_KEYS.has(normKey) && this.pressedKeys.has(normKey)) {
            e.preventDefault();
            this.releaseKey(normKey);
        }
    },

    /**
     * 単発コマンド実行
     */
    triggerSingle(key) {
        if (key === 't') {
            App.handleTakeoff();
        } else if (key === 'l') {
            App.handleLand();
        } else if (key === 'space') {
            App.handleEmergency();
        } else {
            App.wsSend({ type: 'keyboard', action: 'single', key });
        }
        this._highlightKey(key, true);
        this._vibrate(20);
        setTimeout(() => this._highlightKey(key, false), 200);
    },

    /**
     * 移動キー押下開始
     */
    pressKey(key) {
        if (this.pressedKeys.has(key)) return;
        this.pressedKeys.add(key);
        App.wsSend({ type: 'keyboard', action: 'press', key });
        this._highlightKey(key, true);
        this._vibrate(10);
    },

    /**
     * 移動キー押下解除
     */
    releaseKey(key) {
        if (!this.pressedKeys.has(key)) return;
        this.pressedKeys.delete(key);
        App.wsSend({ type: 'keyboard', action: 'release', key });
        this._highlightKey(key, false);
    },

    /**
     * 画面上の仮想ボタン（キーガイド & スマホコントローラー）にポインターイベントを登録
     */
    _bindTouchControls() {
        const attachButtonEvents = (btn) => {
            const key = btn.dataset.key;
            if (!key) return;

            const onStart = (e) => {
                e.preventDefault();
                if (key === 't') {
                    App.handleTakeoff();
                } else if (key === 'l') {
                    App.handleLand();
                } else if (key === 'space') {
                    App.handleEmergency();
                } else if (this.SINGLE_KEYS.has(key)) {
                    this.triggerSingle(key);
                } else if (this.RC_KEYS.has(key)) {
                    this.pressKey(key);
                }
            };

            const onEnd = (e) => {
                e.preventDefault();
                if (this.RC_KEYS.has(key)) {
                    this.releaseKey(key);
                }
            };

            // pointerdown / pointerup でマルチタッチやマウスドラッグ外れに対応
            btn.addEventListener('pointerdown', onStart);
            btn.addEventListener('pointerup', onEnd);
            btn.addEventListener('pointercancel', onEnd);
            btn.addEventListener('pointerleave', (e) => {
                // ポインターがボタン領域から外れたらリリース
                if (this.pressedKeys.has(key)) {
                    onEnd(e);
                }
            });

            // コンテキストメニュー（長押し時の選択メニュー）を抑制
            btn.addEventListener('contextmenu', (e) => e.preventDefault());
        };

        // 画面上のすべての [data-key] 要素（キーガイド、仮想D-Pad、離陸・着陸ボタン）にバインド
        document.querySelectorAll('[data-key]').forEach(attachButtonEvents);
    },

    _highlightKey(key, active) {
        document.querySelectorAll(`[data-key="${key}"]`).forEach((el) => {
            if (active) {
                el.classList.add('active');
            } else {
                el.classList.remove('active');
            }
        });
    },

    /**
     * 安全な触覚フィードバック（HTTP環境・非対応端末でも例外を投げない）
     */
    _vibrate(ms) {
        try {
            if (typeof navigator !== 'undefined' && navigator.vibrate) {
                navigator.vibrate(ms);
            }
        } catch (_) {
            // Non-secure context または未対応環境では静かに無視
        }
    }
};

// Init
document.addEventListener('DOMContentLoaded', () => {
    Controls.init();
});
