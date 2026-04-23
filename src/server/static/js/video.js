/**
 * video.js — 映像管理
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
        // MJPEG ストリームのURLを設定
        this.streamImg.src = '/video_stream?' + Date.now();
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
    },

    screenshot() {
        if (!this.streamImg || !this.streamImg.src) {
            App.notify('映像がありません', 'warning');
            return;
        }

        // 画像をCanvasにコピーしてダウンロード
        const canvas = document.createElement('canvas');
        canvas.width = this.streamImg.naturalWidth || 640;
        canvas.height = this.streamImg.naturalHeight || 480;
        const ctx = canvas.getContext('2d');
        ctx.drawImage(this.streamImg, 0, 0);

        canvas.toBlob((blob) => {
            if (!blob) return;
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `tello_${new Date().toISOString().replace(/[:.]/g, '-')}.jpg`;
            a.click();
            URL.revokeObjectURL(url);
            App.notify('スクリーンショットを保存しました', 'success');
        }, 'image/jpeg', 0.95);
    },
};

// Init
document.addEventListener('DOMContentLoaded', () => {
    VideoManager.init();
});
