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

    _onKeyDown(e) {
        if (!this.enabled) return;
        // テキスト入力中はキーボード操作を無効化
        if (['INPUT', 'TEXTAREA', 'SELECT'].includes(e.target.tagName)) return;

        const key = e.key.toLowerCase();

        // 単発キー (T: 離陸, L: 着陸, Space: 緊急停止)
        if (this.SINGLE_KEYS.has(key)) {
            e.preventDefault();
            const mappedKey = key === ' ' ? 'space' : key;
            this.triggerSingle(mappedKey);
            return;
        }

        // RC制御キー（長押しリピート時の二重送信を防止）
        if (this.RC_KEYS.has(key) && !this.pressedKeys.has(key)) {
            e.preventDefault();
            this.pressKey(key);
        }
    },

    _onKeyUp(e) {
        if (!this.enabled) return;
        const key = e.key.toLowerCase();

        if (this.RC_KEYS.has(key) && this.pressedKeys.has(key)) {
            e.preventDefault();
            this.releaseKey(key);
        }
    },

    /**
     * 単発コマンド実行
     */
    triggerSingle(key) {
        App.wsSend({ type: 'keyboard', action: 'single', key });
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
                if (this.SINGLE_KEYS.has(key) || key === 'space') {
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

        // .key および .vpad-btn 全てにバインド
        document.querySelectorAll('.key[data-key], .vpad-btn[data-key]').forEach(attachButtonEvents);
    },

    _highlightKey(key, active) {
        document.querySelectorAll(`.key[data-key="${key}"], .vpad-btn[data-key="${key}"]`).forEach((el) => {
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
