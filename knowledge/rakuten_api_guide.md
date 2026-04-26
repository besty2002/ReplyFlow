# Rakuten InquiryManagementAPI Reference Guide

이 가이드는 라쿠텐 RMS InquiryManagementAPI(JSON 버전)의 핵심 명세를 정리한 문서입니다.

## 1. 개요
라쿠텐 쇼핑몰의 고객 문의를 조회, 답변, 관리하기 위한 API입니다.

## 2. 문의 목록 조회 (inquirymngapi.inquiries.get)
지정된 조건에 맞는 문의 리스트를 가져옵니다.

- **Endpoint**: `https://api.rms.rakuten.co.jp/es/1.0/inquirymng-api/inquiries`
- **Method**: `GET`
- **주요 요청 파라미터**:
  | 파라미터명 | 타입 | 필수 여부 | 설명 |
  | :--- | :--- | :--- | :--- |
  | `fromDate` | date | Yes | 시작 일시 (`yyyy-MM-ddTHH:mm:ss+09:00`) |
  | `toDate` | date | Yes | 종료 일시 (`yyyy-MM-ddTHH:mm:ss+09:00`) |
  | `noMerchantReply` | boolean | No | `true` 설정 시 **미답변 문의**만 반환 |
  | `limit` | int | No | 페이지당 건수 (1~100, 기본 10) |
  | `page` | int | No | 페이지 번호 (1~10000) |

- **주의사항**: `fromDate`와 `toDate`의 간격은 최대 **31일** 이내여야 합니다.

## 3. 답변 등록 (inquirymngapi.reply.post)
특정 문의에 대해 답변을 전송합니다.

- **Endpoint**: `https://api.rms.rakuten.co.jp/es/1.0/inquirymng-api/inquiry/reply`
- **Method**: `POST`
- **주요 Request Body**:
  ```json
  {
    "inquiryNumber": "문의번호",
    "shopId": "점포ID",
    "message": "답변 내용 (최대 2000자)",
    "attachments": []
  }
  ```
- **URL 제한**: 메시지에 포함되는 URL은 반드시 `https`여야 하며 라쿠텐 허용 도메인(`rakuten.co.jp` 등)만 가능합니다.

## 4. 응답 필드 (Inquiry Object)
- `inquiryNumber`: 문의 고유 번호
- `userName`: 고객 성함
- `message`: 문의 내용
- `regDate`: 문의 등록 일시
- `isCompleted`: 처리 완료 여부 (true/false)
- `readByMerchant`: 상점 기독 여부
- `replies`: 기존 답변 목록 (배열)

## 5. 인증 방식
- **Header**: `Authorization: ESA Base64(serviceSecret:licenseKey)`
- **Content-Type**: `application/json; charset=utf-8`
