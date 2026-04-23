/**
 * controls.js — キーボード操作
 */

const Controls = {
    pressedKeys: new Set(),
    enabled: true,

    // RC制御キーマッピング
    RC_KEYS: new Set(['w', 's', 'a', 'd', 'q', 'e', 'r', 'f']),
    // 単発キー
    SINGLE_KEYS: new Set(['t', 'l', ' ']),

    init() {
        document.addEventListener('keydown', (e) => this._onKeyDown(e));
        document.addEventListener('keyup', (e) => this._onKeyUp(e));
    },

    _onKeyDown(e) {
        if (!this.enabled) return;
        // テキスト入力中は無視
        if (['INPUT', 'TEXTAREA', 'SELECT'].includes(e.target.tagName)) return;

        const key = e.key.toLowerCase();

        // 単発キー
        if (this.SINGLE_KEYS.has(key)) {
            e.preventDefault();
            const mappedKey = key === ' ' ? 'space' : key;
            App.wsSend({ type: 'keyboard', action: 'single', key: mappedKey });
            this._highlightKey(mappedKey, true);
            setTimeout(() => this._highlightKey(mappedKey, false), 200);
            return;
        }

        // RC制御キー（リピート防止）
        if (this.RC_KEYS.has(key) && !this.pressedKeys.has(key)) {
            e.preventDefault();
            this.pressedKeys.add(key);
            App.wsSend({ type: 'keyboard', action: 'press', key });
            this._highlightKey(key, true);
        }
    },

    _onKeyUp(e) {
        if (!this.enabled) return;
        const key = e.key.toLowerCase();

        if (this.RC_KEYS.has(key) && this.pressedKeys.has(key)) {
            e.preventDefault();
            this.pressedKeys.delete(key);
            App.wsSend({ type: 'keyboard', action: 'release', key });
            this._highlightKey(key, false);
        }
    },

    _highlightKey(key, active) {
        const el = document.querySelector(`.key[data-key="${key}"]`);
        if (el) {
            if (active) {
                el.classList.add('active');
            } else {
                el.classList.remove('active');
            }
        }
    },
};

// Init
document.addEventListener('DOMContentLoaded', () => {
    Controls.init();
});
