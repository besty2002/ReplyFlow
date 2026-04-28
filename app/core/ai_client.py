import os
import logging
import json
import asyncio
from typing import Dict, Any, List
import google.generativeai as genai
from app.core.config import settings

logger = logging.getLogger(__name__)

class AIClient:
    """
    고객 문의 처리를 위한 AI 서비스 클라이언트입니다.
    사용 가능한 최신 Gemini 모델(v2.5+)을 우선적으로 사용합니다.
    """
    
    def __init__(self, provider: str = "auto", model_name: str = "gemini-2.5-flash"):
        self.provider = provider
        self.model_name = model_name
        
        # GEMINI_API_KEY가 있으면 기본으로 gemini를 사용
        if provider == "auto":
            if settings.GEMINI_API_KEY:
                self.provider = "gemini"
                genai.configure(api_key=settings.GEMINI_API_KEY)
                
                # 가용 모델 자동 체크 및 최적화
                try:
                    models = [m.name.replace("models/", "") for m in genai.list_models()]
                    if model_name not in models and models:
                        # 설정된 모델이 없으면 가장 좋은 모델(보통 리스트 앞쪽) 선택
                        self.model_name = models[0]
                except Exception:
                    pass
                
                logger.info(f"AIClient initialized with provider=gemini, model={self.model_name}")
            else:
                self.provider = "mock"
                logger.warning("GEMINI_API_KEY not found. AIClient initialized with provider=mock")

    async def generate_reply(self, inquiry_text: str, context: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Gemini를 사용하여 답변 초안을 생성합니다. 실시간 정보를 반영합니다.
        감정 분석, 자동 태깅, 우선순위 제안을 포함합니다.
        """
        if self.provider == "mock":
            return {
                "reply": "[MOCK] 문의 감사합니다. 곧 답변 드리겠습니다.",
                "category": "일반문의",
                "sentiment": "neutral",
                "sentiment_score": 0.5,
                "tags": ["일반문의"],
                "priority_suggestion": "normal"
            }

        context = context or {}
        customer_name = context.get("customer_id") or context.get("customer_name") or "お客様"
        order_status = context.get("order_status", "確認中")
        stock_count = context.get("stock_count")
        item_name = context.get("item_name", "該当商品")
        shipping_verdict = context.get("shipping_verdict", "")
        shipping_reason = context.get("shipping_reason", "")
        cs_guidelines = context.get("cs_guidelines", "")
        
        stock_info = f"{stock_count}個" if stock_count is not None else "確認中"
        
        # 발송 판정 컨텍스트
        shipping_context = ""
        if shipping_verdict:
            shipping_context = f"■ 発送判定: {shipping_verdict}\n■ 判定理由: {shipping_reason}\n"
        
        # 야마토 배송 정보 추출
        delivery_info = context.get("delivery_info")
        delivery_context = ""
        if delivery_info and delivery_info.get("tracking_number") != "-":
            delivery_context = (
                f"■ 전표 번호: {delivery_info.get('tracking_number')}\n"
                f"■ 배송 상태: {delivery_info.get('current_status')}\n"
                f"■ 현재 위치/예정: {delivery_info.get('current_location')}\n"
            )

        # 시스템 프롬프트 (일본어 대응 중심 + 감정분석 + 태깅)
        system_instruction = (
            "あなたは日本 楽天市場のショップ担当者です。\n"
            f"顧客名（{customer_name} 様）へ丁寧な日本語で対応してください。\n"
            "以下の【リアルタイム 정보】를 바탕으로 답변을 작성하세요:\n"
            "--------------------------------------------------\n"
            f"■ 대상 상품: {item_name}\n"
            f"■ 주문 상태: {order_status}\n"
            f"■ 현재 재고: {stock_info}\n"
            f"{shipping_context}"
            f"{delivery_context}"
            "--------------------------------------------------\n\n"
            "【응대 가이드라인】\n"
            "1. 発送可能の場合は「即日発送可能」を強調してください。\n"
            "2. 発送不可の場合は「お取り寄せとなり、7-10営業日ほどお時間をいただきます」と案内してください。\n"
            "3. 이미 발송되었다면 배송 상태(현재 위치 등)를 구체적으로 언급하며 안심시키세요.\n"
            "4. 답변은 매우 정중하고 자연스러운 일본어로 작성하세요.\n"
            "5. 반드시 JSON 형식으로만 응답하세요.\n"
            "6. 카테고리는 [배송문의, 재고문의, 취소/환불, サイズ交換, 商品不良, 기타] 중 하나로 분류하세요.\n"
            "7. 감정 분석을 수행하세요: angry(화남/불만), curious(궁금함), grateful(감사함), neutral(보통) 중 하나.\n"
            "8. sentiment_score는 0.0~1.0 사이의 강도입니다 (1.0이 가장 강함).\n"
            "9. tags는 문의 내용에서 추출한 핵심 키워드 태그 배열입니다 (예: [\"배송지연\", \"긴급\"]).\n"
            "10. priority_suggestion은 urgent, high, normal, low 중 하나입니다.\n\n"
        )
        
        # 회사 CS 가이드라인 주입
        if cs_guidelines:
            system_instruction += (
                "【会社CS対応ガイドライン（必ず遵守してください）】\n"
                f"{cs_guidelines}\n"
                "--------------------------------------------------\n\n"
            )
        
        system_instruction += (
            "JSON 응답 형식:\n"
            "{\n"
            '  "reply": "일본어 본문",\n'
            '  "category": "카테고리",\n'
            '  "sentiment": "angry|curious|grateful|neutral",\n'
            '  "sentiment_score": 0.0~1.0,\n'
            '  "tags": ["태그1", "태그2"],\n'
            '  "priority_suggestion": "urgent|high|normal|low"\n'
            "}"
        )

        try:
            # 모델 초기화 (검증된 최신 모델 사용)
            model = genai.GenerativeModel(
                model_name=self.model_name,
                system_instruction=system_instruction
            )
            
            prompt = f"고객 문의: {inquiry_text}"
            
            # 답변 생성 요청
            response = await model.generate_content_async(
                prompt,
                generation_config=genai.types.GenerationConfig(
                    temperature=0.7,
                    response_mime_type="application/json"
                )
            )
            
            # 결과 파싱
            res_text = response.text.strip()
            result = json.loads(res_text)
            
            # 필수 필드 기본값 보장
            result.setdefault("sentiment", "neutral")
            result.setdefault("sentiment_score", 0.5)
            result.setdefault("tags", [])
            result.setdefault("priority_suggestion", "normal")
            result.setdefault("category", "기타")
            
            return result
            
        except Exception as e:
            logger.error(f"[Gemini API Error] {e}")
            return {
                "reply": "申し訳ございません. 現在AI回答作成が一時的に制限されています. 手動で対応をお願いいたします.",
                "category": "기타",
                "sentiment": "neutral",
                "sentiment_score": 0.5,
                "tags": [],
                "priority_suggestion": "normal"
            }

    async def analyze_metadata(self, text: str) -> Dict[str, Any]:
        """
        고객 문의 내용을 분석하여 메타데이터(카테고리, 감정, 태그, 우선순위)를 반환합니다.
        Sync Bot이나 일괄 처리 작업에서 사용됩니다.
        """
        if self.provider == "mock":
            return {
                "category": "일반문의",
                "sentiment": "neutral",
                "sentiment_score": 0.5,
                "tags": ["테스트"],
                "priority_suggestion": "normal"
            }
        
        try:
            model = genai.GenerativeModel(
                model_name=self.model_name,
                system_instruction=(
                    "あなたは日本EC（楽天市場）のカスタマーサポート専門AIです。\n"
                    "顧客からの問い合わせ内容を分析し, 以下のJSON形式で回答してください。\n"
                    "1. category: [配送, 在庫, キャンセル, 返品/返金, 交換, 商品不良, 領収書, その他] から選択\n"
                    "2. sentiment: [angry(不満/怒り), curious(質問/確認), grateful(感謝), neutral(通常)] から選択\n"
                    "3. sentiment_score: 0.0(負) ~ 1.0(正) の範囲で数値化\n"
                    "4. tags: 問い合わせの核心キーワード（例: ['配送遅延', 'サイズ間違い', '至急']）\n"
                    "5. priority_suggestion: [urgent, high, normal, low] から緊急度を判定\n\n"
                    "JSON 응답 형식:\n"
                    "{\n"
                    '  "category": "...",\n'
                    '  "sentiment": "...",\n'
                    '  "sentiment_score": 0.0,\n'
                    '  "tags": ["...", "..."],\n'
                    '  "priority_suggestion": "..."\n'
                    "}"
                )
            )
            response = await model.generate_content_async(
                f"分析対象テキスト: {text}",
                generation_config=genai.types.GenerationConfig(
                    temperature=0.2,
                    response_mime_type="application/json"
                )
            )
            result = json.loads(response.text.strip())
            
            # 기본값 보장
            result.setdefault("category", "その他")
            result.setdefault("sentiment", "neutral")
            result.setdefault("sentiment_score", 0.5)
            result.setdefault("tags", [])
            result.setdefault("priority_suggestion", "normal")
            
            return result
        except Exception as e:
            logger.error(f"[Metadata Analysis Error] {e}")
            return {
                "category": "その他",
                "sentiment": "neutral",
                "sentiment_score": 0.5,
                "tags": [],
                "priority_suggestion": "normal"
            }

    async def analyze_sentiment_only(self, text: str) -> Dict[str, Any]:
        """하위 호환성을 위해 유지합니다."""
        return await self.analyze_metadata(text)

# 인스턴스 생성
ai_client = AIClient(provider="auto")
