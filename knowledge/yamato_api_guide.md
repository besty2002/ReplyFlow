# ヤマト 운수(쿠로네코 멤버즈) Open API 통합 ガイド

이 ドキュメント는 ヤマト 운수で 제공하는 '쿠로네코 멤버즈 ID 連携 오픈 API' 및 '配送 관리 API' 連携のための 지침서です.

---

## 1. システム 件요
- **목적**: 쿠로네코 멤버즈 회원 認証(ID 連携) 및 配送 日時/장소 変更 등 サービス API 呼び出し
- **주요 기능**: 注文 照会, 配送 登録, ステータス 確認, 수취 変更 등
- **프로토콜**: OAuth 2.0 / OpenID Connect (OIDC)

---

## 2. 認証 및 権限 부여 (Auth)

### 2.1 認証 方式 (Flow)
1. **Authorization Code Flow (멤버즈 이용)**
   - 件인 회원 情報가 含む된 データ 교환 시 使用
   - ユーザー 認証 및 権限 동의 과정이 含む됨
2. **Client Credentials Flow (게스트 이용)**
   - 비회원(게스트) データ 処理 시 使用
   - 사이트 간 認証만で トークン発行

### 2.2 주요 パラメータ
- **client_id**: 이용 사이트 ID (사전 登録 필수)
- **client_secret**: 이용 사이트 パスワード (공통 비밀키)
- **redirect_uri**: 認証 후 돌아올 URL (사전 登録된 베이스 URL과 일치해야 함)
- **scope**: 使用할 API 権限 (예: `openid`, `profile`, 配送日時変更 등)

---

## 3. API エンドポイント (テスト 환경)

| 구분 | URL |
| :--- | :--- |
| **認証 サーバー (ID 連携)** | `https://test-id.kuronekoyamato.co.jp` |
| **API 実行 サーバー (수취変更 등)** | `https://dev03-api.nrcs.kuronekoyamato.co.jp` |
| **지도 API (위치 선택)** | `https://test.e-map.ne.jp/p/yamato08test/` |

---

## 4. 공통 규칙 및 ヘッダー

### 4.1 リクエスト ヘッダー
```http
Authorization: Bearer {access_token}
KuronekoYamato-API-VERSION: 1.0
Content-Type: application/json
```

### 4.2 トークン 관리
- **Access Token**: API 呼び出し 시 使用 (有効期間 존재)
- **Refresh Token**: Access Token 期限切れ 시 更新용で 使用 (1회성)
- **ID Token**: ユーザー 認証 情報를 담은 JWT 形式

---

## 5. 핵심 API 시퀀스

### 5.1 トークン発行 흐름 (Authorization Code Flow)
1. **認証 요구 (GET)**: `/authz` 呼び出し -> ログ인 화면 표시
2. **認証 レスポンス**: クエリ 스트링で `code` 수신
3. **トークン リクエスト (POST)**: `/token` 呼び出し (grant_type=authorization_code)
4. **トークン レスポンス**: `access_token`, `id_token`, `refresh_token` 수신

### 5.2 API 呼び出し
発行받은 `access_token`을 ヘッダー에 담아 각 サービス エンドポイント(配送 登録, 수취 変更 등) 呼び出し

---

## 6. 注意사항 (중요)
- **セキュリティ**: `client_secret` 및 `access_token`은 サーバー 측で 안전하게 관리해야 함
- **IP 制限**: ヤマト 환경で アクセス 허용을 ために **애플리케이션 サーバー의 공인 IP**를 사전 登録해야 함
- **버튼 구분**: KM(멤버즈) 이용과 비KM(게스트) 이용에 に従い 認証 方式이 다르므로 로직 분기 필요
- **テスト データ**: 送信 テスト를 ために서는 ヤマトで 제공하는 テスト용 **전표 番号**가 필요함

---

## 7. 関連 ドキュメント
- 04_쿠로네코 멤버즈 오픈 API 사양서【クライアント용】
- Uni-ID 쿠로네코 멤버즈 ID 連携 범용판 사양서
