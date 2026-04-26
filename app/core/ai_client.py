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
        """
        if self.provider == "mock":
            return {"reply": "[MOCK] 문의 감사합니다. 곧 답변 드리겠습니다.", "category": "일반문의"}

        context = context or {}
        customer_name = context.get("customer_id") or context.get("customer_name") or "お客様"
        order_status = context.get("order_status", "確認中")
        stock_count = context.get("stock_count")
        item_name = context.get("item_name", "該当商品")
        
        stock_info = f"{stock_count}개" if stock_count is not None else "확인 중"
        
        # 야마토 배송 정보 추출
        delivery_info = context.get("delivery_info")
        delivery_context = ""
        if delivery_info and delivery_info.get("tracking_number") != "-":
            delivery_context = (
                f"■ 전표 번호: {delivery_info.get('tracking_number')}\n"
                f"■ 배송 상태: {delivery_info.get('current_status')}\n"
                f"■ 현재 위치/예정: {delivery_info.get('current_location')}\n"
            )

        # 시스템 프롬프트 (일본어 대응 중심)
        system_instruction = (
            "あなたは日本 楽天市場のショップ担当者です。\n"
            f"顧客名（{customer_name} 様）へ丁寧な日本語で対応してください。\n"
            "以下の【リアルタイム 정보】를 바탕으로 답변을 작성하세요:\n"
            "--------------------------------------------------\n"
            f"■ 대상 상품: {item_name}\n"
            f"■ 주문 상태: {order_status}\n"
            f"■ 현재 재고: {stock_info}\n"
            f"{delivery_context}"
            "--------------------------------------------------\n\n"
            "【응대 가이드라인】\n"
            "1. 재고가 있으면 '즉시 발송 가능'함을 강조하세요.\n"
            "2. 이미 발송되었다면 배송 상태(현재 위치 등)를 구체적으로 언급하며 안심시키세요.\n"
            "3. 답변은 매우 정중하고 자연스러운 일본어로 작성하세요.\n"
            "4. 반드시 JSON 형식으로만 응답하세요: {\"reply\": \"일본어 본문\", \"category\": \"카테고리\"}\n"
            "5. 카테고리는 [배송문의, 재고문의, 취소/환불, 기타] 중 하나로 분류하세요."
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
            return json.loads(res_text)
            
        except Exception as e:
            logger.error(f"[Gemini API Error] {e}")
            return {
                "reply": "申し訳ございません. 現在AI回答作成が一時的に制限されています. 手動で対応をお願いいたします.",
                "category": "기타"
            }

# 인스턴스 생성
ai_client = AIClient(provider="auto")
