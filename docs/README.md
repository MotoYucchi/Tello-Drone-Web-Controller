# Tello Drone Web Controller

WiFiバインド対応・LineTrace搭載のTelloドローン制御Webアプリケーション

---

## 目次

- [概要](#概要)
- [機能一覧](#機能一覧)
- [動作要件](#動作要件)
- [セットアップ](#セットアップ)
- [起動方法](#起動方法)
- [使い方](#使い方)
  - [接続](#接続)
  - [飛行制御](#飛行制御)
  - [キーボード操作](#キーボード操作)
  - [LineTrace](#linetrace)
  - [QRコード](#qrコード)
  - [映像ストリーミング](#映像ストリーミング)
- [ネットワーク構成](#ネットワーク構成)
- [API リファレンス](#api-リファレンス)
- [トラブルシューティング](#トラブルシューティング)
- [ライセンス](#ライセンス)

---

## 概要

DJI Telloドローンをブラウザから操作するWebアプリケーションです。有線LAN + WiFiの同時接続環境でも、WiFi側（Tello側）に確実にパケットを送信するネットワークバインド機能を搭載しています。

### 主な特徴

- **ネットワークバインド**: 生UDPソケットでWiFiインターフェースに直接バインド
- **LineTrace**: 映像からラインを検出し自動追従
- **QRコード読み取り**: 強化された前処理によるQRコード検出
- **レスポンシブUI**: PC・タブレット・モバイル対応のダークモードUI
- **リアルタイム制御**: WebSocket経由のキーボード・RC制御

---

## 機能一覧

| 機能 | 説明 |
|------|------|
| ドローン接続/切断 | WiFiインターフェース自動検出 + 手動選択 |
| 離陸/着陸/緊急停止 | ボタン操作またはキーボード (T/L/Space) |
| 移動制御 | WASD（水平移動）、R/F（上昇/下降）、Q/E（回転） |
| 映像ストリーミング | MJPEG方式のリアルタイム映像表示 |
| LineTrace | HSV色空間フィルタリングによるライン追跡 |
| QRコードスキャン | 映像からQRコードを検出しリンクを保存 |
| テレメトリ | バッテリー、高度、温度、飛行時間のリアルタイム表示 |
| ネットワーク設定 | インターフェース選択、映像品質設定 |

---

## 動作要件

| 項目 | 要件 |
|------|------|
| OS | Windows 10/11, macOS, Linux |
| Python | 3.11 以上 |
| パッケージマネージャー | [uv](https://docs.astral.sh/uv/) |
| ドローン | DJI Tello / Tello EDU |
| ブラウザ | Chrome, Edge, Firefox (最新版) |

---

## セットアップ

### 簡単セットアップ（推奨）

同梱のランチャースクリプトを使用すると、`uv` のインストールから起動まで自動で行えます。

**Windows:**
```
start.bat
```

**macOS / Linux:**
```bash
chmod +x start.sh
./start.sh
```

### 手動セットアップ

#### 1. uv のインストール

**Windows (PowerShell):**
```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

**macOS / Linux:**
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

#### 2. 依存関係のインストール

```bash
cd web_drone_controller
uv sync
```

#### 3. サーバー起動

```bash
uv run python -m src
```

#### 4. ブラウザでアクセス

```
http://localhost:8000
```

---

## 起動方法

```bash
# 開発モード（ホットリロード有効）
uv run python -m src

# ブラウザで開く
# http://localhost:8000
```

---

## 使い方

### 接続

1. PCのWiFiをTelloのネットワークに接続（SSID: `TELLO-XXXXXX`）
2. ブラウザで `http://localhost:8000` を開く
3. 右上の「接続」ボタンをクリック
4. ステータスが「接続中」に変わったら準備完了

> **💡 有線LAN併用時**: ネットワーク設定パネルでTelloインターフェース（★Tello マーク付き）を選択してから接続してください。

### 飛行制御

| ボタン | 動作 |
|--------|------|
| 離陸 | ドローンが約1mの高さまで上昇 |
| 着陸 | その場で着陸 |
| 緊急停止 | モーター即停止（確認ダイアログあり） |

### キーボード操作

| キー | 動作 |
|------|------|
| W | 前進 |
| S | 後退 |
| A | 左移動 |
| D | 右移動 |
| R | 上昇 |
| F | 下降 |
| Q | 左回転（反時計回り） |
| E | 右回転（時計回り） |
| T | 離陸 |
| L | 着陸 |
| Space | 緊急停止 |

> **⚠️ 注意**: テキスト入力欄にフォーカスがあるとキーボード操作は無効です。

### LineTrace

1. 映像ストリーミングを開始
2. LineTraceパネルで色プリセット（赤/青/黄/黒）を選択、またはHSVスライダーで手動調整
3. LineTraceのトグルスイッチをON
4. ドローンが検出したラインに沿って自動追従

#### HSVパラメータ

| パラメータ | 説明 | 範囲 |
|-----------|------|------|
| H min/max | 色相（Hue）の範囲 | 0-179 |
| S min/max | 彩度（Saturation）の範囲 | 0-255 |
| V min/max | 明度（Value）の範囲 | 0-255 |
| 速度 | 前進速度 | 0-100 |

### QRコード

1. 映像ストリーミング中に「スキャン」ボタンをクリック
2. QRコード内の3桁の数字を抽出してリンクを自動生成・保存
3. 「更新」ボタンで保存済みリンク一覧を更新

### 映像ストリーミング

1. ドローン接続後、映像エリアの「映像開始」ボタンをクリック
2. 映像停止ボタン（■）で停止
3. カメラアイコンでスクリーンショットを保存

---

## ネットワーク構成

```
┌─────────────────┐     WiFi (192.168.10.x)      ┌──────────┐
│    PC            │◄──────────────────────────────►│  Tello   │
│                  │        UDP :8889 (cmd)         │          │
│  ┌─────────┐    │        UDP :8890 (state)       │          │
│  │ FastAPI  │    │        UDP :11111 (video)      │          │
│  │ :8000    │    │                                └──────────┘
│  └─────────┘    │
│                  │     Ethernet (別サブネット)
│                  │◄──────────────── Internet
└─────────────────┘
```

**ポイント**: UDPソケットを `192.168.10.x` のローカルIPにバインドすることで、Ethernet経由のトラフィックと分離し、確実にWiFi（Tello側）へパケットを送信します。

---

## API リファレンス

### REST API

| メソッド | パス | 説明 |
|---------|------|------|
| POST | `/api/connect` | Tello接続 |
| POST | `/api/disconnect` | Tello切断 |
| GET | `/api/status` | ステータス取得 |
| GET | `/api/network/interfaces` | ネットワークインターフェース一覧 |
| POST | `/api/takeoff` | 離陸 |
| POST | `/api/land` | 着陸 |
| POST | `/api/emergency` | 緊急停止 |
| POST | `/api/move` | 移動 `{direction, distance}` |
| POST | `/api/rotate` | 回転 `{direction, angle}` |
| POST | `/api/rc` | RC制御 `{lr, fb, ud, yaw}` |
| POST | `/api/video/start` | 映像開始 |
| POST | `/api/video/stop` | 映像停止 |
| POST | `/api/video/quality` | 映像品質 `{width, height, quality}` |
| GET | `/video_stream` | MJPEGストリーム |
| POST | `/api/linetrace/start` | LineTrace開始 |
| POST | `/api/linetrace/stop` | LineTrace停止 |
| POST | `/api/linetrace/params` | LineTraceパラメータ設定 |
| POST | `/api/linetrace/preset/{name}` | 色プリセット適用 |
| GET | `/api/linetrace/presets` | プリセット一覧 |
| POST | `/api/qr/scan` | QRコードスキャン |
| GET | `/api/qr/links` | 保存済みリンク一覧 |
| DELETE | `/api/qr/links/{num}` | リンク削除 |

### WebSocket

| パス | 説明 |
|------|------|
| `ws://localhost:8000/ws/control` | 制御用（コマンド送受信） |
| `ws://localhost:8000/ws/telemetry` | テレメトリ配信（1秒間隔） |

---

## トラブルシューティング

### Telloに接続できない

1. WiFiがTelloネットワーク（`TELLO-XXXXXX`）に接続されているか確認
2. ネットワーク設定で正しいインターフェースが選択されているか確認
3. ファイアウォールがUDPポート 8889, 8890, 11111 をブロックしていないか確認
4. 別のアプリケーションがポート 8889 を使用していないか確認

### 映像が表示されない

1. ドローンが接続状態であることを確認
2. 「映像開始」ボタンを再度クリック
3. ブラウザの開発者ツールでコンソールエラーを確認
4. Telloのバッテリー残量が十分であることを確認

### LineTraceが反応しない

1. 映像ストリーミングが開始されていることを確認
2. HSVパラメータが追跡対象の色に合っているか確認（プリセットで試行）
3. 照明条件が十分であることを確認

### 有線LAN接続時にTelloと通信できない

1. ネットワーク設定パネルで「★Tello」マークのインターフェースを明示的に選択
2. 「再検出」ボタンでインターフェースを再読み込み
3. `192.168.10.x` のIPが表示されない場合、WiFi接続を確認

---

## プロジェクト構造

```
web_drone_controller/
├── pyproject.toml          # 依存関係定義
├── start.bat               # Windows ランチャー
├── start.sh                # macOS/Linux ランチャー
├── docs/
│   ├── README.md           # このファイル
│   └── README_EN.md        # 英語版ドキュメント
└── src/
    ├── __init__.py
    ├── __main__.py          # エントリーポイント
    ├── tello/
    │   ├── udp_controller.py   # 生UDP通信
    │   ├── state_receiver.py   # テレメトリ受信
    │   └── video_receiver.py   # 映像受信
    ├── linetrace/
    │   └── engine.py        # LineTraceエンジン
    ├── qr/
    │   └── reader.py        # QRコード読み取り
    └── server/
        ├── app.py           # FastAPIアプリ
        ├── ws_handler.py    # WebSocketハンドラー
        ├── templates/
        │   └── index.html   # メインUI
        └── static/
            ├── css/main.css
            └── js/
                ├── app.js
                ├── controls.js
                ├── linetrace.js
                └── video.js
```

---

## ライセンス

MIT License
