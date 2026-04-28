# Rakuten InquiryManagementAPI Reference Guide

이 ガイド는 라쿠텐 RMS InquiryManagementAPI(JSON 버전)의 핵심 명세를 정리한 ドキュメントです.

## 1. 件요
라쿠텐 ショップ몰의 お客様のお問い合わせ를 照会, 返信, 관리하기 ための APIです.

## 2. お問い合わせ リスト 照会 (inquirymngapi.inquiries.get)
지정된 조件에 맞는 お問い合わせリスト를 가져옵니다.

- **Endpoint**: `https://api.rms.rakuten.co.jp/es/1.0/inquirymng-api/inquiries`
- **Method**: `GET`
- **주요 リクエスト パラメータ**:
  | パラメータ명 | タイプ | 필수 여부 | 説明 |
  | :--- | :--- | :--- | :--- |
  | `fromDate` | date | Yes | 開始 日時 (`yyyy-MM-ddTHH:mm:ss+09:00`) |
  | `toDate` | date | Yes | 終了 日時 (`yyyy-MM-ddTHH:mm:ss+09:00`) |
  | `noMerchantReply` | boolean | No | `true` 設定 시 **미返信 お問い合わせ**만 返却 |
  | `limit` | int | No | ページ당 件수 (1~100, 基本 10) |
  | `page` | int | No | ページ 番号 (1~10000) |

- **注意사항**: `fromDate`와 `toDate`의 간격은 最大 **31일** 이내여야 します.

## 3. 返信 登録 (inquirymngapi.reply.post)
특정 お問い合わせについて 返信을 送信します.

- **Endpoint**: `https://api.rms.rakuten.co.jp/es/1.0/inquirymng-api/inquiry/reply`
- **Method**: `POST`
- **주요 Request Body**:
  ```json
  {
    "inquiryNumber": "お問い合わせ番号",
    "shopId": "점포ID",
    "message": "返信 内容 (最大 2000자)",
    "attachments": []
  }
  ```
- **URL 制限**: メッセージ에 含む되는 URL은 반드시 `https`여야 하며 라쿠텐 허용 도메인(`rakuten.co.jp` 등)만 가능します.

## 4. レスポンス フィールド (Inquiry Object)
- `inquiryNumber`: お問い合わせ 고유 番号
- `userName`: 顧客 성함
- `message`: お問い合わせ内容
- `regDate`: お問い合わせ 登録 日時
- `isCompleted`: 処理 完了 여부 (true/false)
- `readByMerchant`: 상점 기독 여부
- `replies`: 既存 返信 リスト (配列)

## 5. 認証 方式
- **Header**: `Authorization: ESA Base64(serviceSecret:licenseKey)`
- **Content-Type**: `application/json; charset=utf-8`
