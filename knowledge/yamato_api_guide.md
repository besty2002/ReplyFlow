# 야마토 운수(쿠로네코 멤버즈) Open API 통합 가이드

이 문서는 야마토 운수에서 제공하는 '쿠로네코 멤버즈 ID 연동 오픈 API' 및 '배송 관리 API' 연동을 위한 지침서입니다.

---

## 1. 시스템 개요
- **목적**: 쿠로네코 멤버즈 회원 인증(ID 연동) 및 배송 일시/장소 변경 등 서비스 API 호출
- **주요 기능**: 주문 조회, 배송 등록, 상태 확인, 수취 변경 등
- **프로토콜**: OAuth 2.0 / OpenID Connect (OIDC)

---

## 2. 인증 및 권한 부여 (Auth)

### 2.1 인증 방식 (Flow)
1. **Authorization Code Flow (멤버즈 이용)**
   - 개인 회원 정보가 포함된 데이터 교환 시 사용
   - 사용자 인증 및 권한 동의 과정이 포함됨
2. **Client Credentials Flow (게스트 이용)**
   - 비회원(게스트) 데이터 처리 시 사용
   - 사이트 간 인증만으로 토큰 발급

### 2.2 주요 파라미터
- **client_id**: 이용 사이트 ID (사전 등록 필수)
- **client_secret**: 이용 사이트 패스워드 (공통 비밀키)
- **redirect_uri**: 인증 후 돌아올 URL (사전 등록된 베이스 URL과 일치해야 함)
- **scope**: 사용할 API 권한 (예: `openid`, `profile`, 배송일시변경 등)

---

## 3. API 엔드포인트 (테스트 환경)

| 구분 | URL |
| :--- | :--- |
| **인증 서버 (ID 연동)** | `https://test-id.kuronekoyamato.co.jp` |
| **API 실행 서버 (수취변경 등)** | `https://dev03-api.nrcs.kuronekoyamato.co.jp` |
| **지도 API (위치 선택)** | `https://test.e-map.ne.jp/p/yamato08test/` |

---

## 4. 공통 규칙 및 헤더

### 4.1 요청 헤더
```http
Authorization: Bearer {access_token}
KuronekoYamato-API-VERSION: 1.0
Content-Type: application/json
```

### 4.2 토큰 관리
- **Access Token**: API 호출 시 사용 (유효기간 존재)
- **Refresh Token**: Access Token 만료 시 갱신용으로 사용 (1회성)
- **ID Token**: 사용자 인증 정보를 담은 JWT 형식

---

## 5. 핵심 API 시퀀스

### 5.1 토큰 발급 흐름 (Authorization Code Flow)
1. **인증 요구 (GET)**: `/authz` 호출 -> 로그인 화면 표시
2. **인증 응답**: 쿼리 스트링으로 `code` 수신
3. **토큰 요청 (POST)**: `/token` 호출 (grant_type=authorization_code)
4. **토큰 응답**: `access_token`, `id_token`, `refresh_token` 수신

### 5.2 API 호출
발급받은 `access_token`을 헤더에 담아 각 서비스 엔드포인트(배송 등록, 수취 변경 등) 호출

---

## 6. 주의사항 (중요)
- **보안**: `client_secret` 및 `access_token`은 서버 측에서 안전하게 관리해야 함
- **IP 제한**: 야마토 환경에서 접근 허용을 위해 **애플리케이션 서버의 공인 IP**를 사전 등록해야 함
- **버튼 구분**: KM(멤버즈) 이용과 비KM(게스트) 이용에 따라 인증 방식이 다르므로 로직 분기 필요
- **테스트 데이터**: 전송 테스트를 위해서는 야마토에서 제공하는 테스트용 **전표 번호**가 필요함

---

## 7. 관련 문서
- 04_쿠로네코 멤버즈 오픈 API 사양서【클라이언트용】
- Uni-ID 쿠로네코 멤버즈 ID 연동 범용판 사양서
