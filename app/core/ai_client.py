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
    お客様のお問い合わせ 処理のための AI サービス クライアントです.
    使用 가능한 最新 Gemini 모델(v2.5+)을 우선적で 使用します.
    """
    
    def __init__(self, provider: str = "auto", model_name: str = "gemini-2.5-flash"):
        self.provider = provider
        self.model_name = model_name
        
        # GEMINI_API_KEY가 있으면 基本で gemini를 使用
        if provider == "auto":
            if settings.GEMINI_API_KEY:
                self.provider = "gemini"
                genai.configure(api_key=settings.GEMINI_API_KEY)
                
                # 가용 모델 自動 체크 및 최적화
                try:
                    models = [m.name.replace("models/", "") for m in genai.list_models()]
                    if model_name not in models and models:
                        # 設定된 모델がなければ 가장 좋은 모델(普通 리스트 앞쪽) 선택
                        self.model_name = models[0]
                except Exception:
                    pass
                
                logger.info(f"AIClient initialized with provider=gemini, model={self.model_name}")
            else:
                self.provider = "mock"
                logger.warning("GEMINI_API_KEY not found. AIClient initialized with provider=mock")

    async def generate_reply(self, inquiry_text: str, context: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Gemini를 使用하여 返信 초안을 生成します. 실時間 情報를 반영します.
        感情 分析, 自動 태깅, 優先度 제안을 含むします.
        """
        if self.provider == "mock":
            return {
                "reply": "[MOCK] お問い合わせ 感謝します. 곧 返信 드리겠します.",
                "category": "일반お問い合わせ",
                "sentiment": "neutral",
                "sentiment_score": 0.5,
                "tags": ["일반お問い合わせ"],
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
        
        # 発送 판정 コンテキスト
        shipping_context = ""
        if shipping_verdict:
            shipping_context = f"■ 発送判定: {shipping_verdict}\n■ 判定理由: {shipping_reason}\n"
        
        # ヤマト 配送情報 抽出
        delivery_info = context.get("delivery_info")
        delivery_context = ""
        if delivery_info and delivery_info.get("tracking_number") != "-":
            delivery_context = (
                f"■ 전표 番号: {delivery_info.get('tracking_number')}\n"
                f"■ 配送 ステータス: {delivery_info.get('current_status')}\n"
                f"■ 現在 위치/예정: {delivery_info.get('current_location')}\n"
            )

        # システム プロンプト (일본어 대응 중심 + 感情分析 + 태깅)
        system_instruction = (
            "あなたは日本 楽天市場のショップ担当者です。\n"
            f"顧客名（{customer_name} 様）へ丁寧な日本語で対応してください。\n"
            "以下の【リアルタイム 情報】를 바탕で 返信을 작성하してください:\n"
            "--------------------------------------------------\n"
            f"■ 대상 商品: {item_name}\n"
            f"■ 注文ステータス: {order_status}\n"
            f"■ 現在の在庫: {stock_info}\n"
            f"{shipping_context}"
            f"{delivery_context}"
            "--------------------------------------------------\n\n"
            "【응대 ガイド라인】\n"
            "1. 発送可能の場合は「即日発送可能」を強調してください。\n"
            "2. 発送不可の場合は「お取り寄せとなり、7-10営業日ほどお時間をいただきます」と案内してください。\n"
            "3. 이미 発送되었다면 配送 ステータス(現在 위치 등)를 구체적で 언급하며 안심시키してください.\n"
            "4. 返信은 매우 정중하고 자연스러운 일본어로 작성하してください.\n"
            "5. 반드시 JSON 形式で만 レスポンス하してください.\n"
            "6. カテゴリー는 [配送お問い合わせ, 在庫お問い合わせ, キャンセル/환불, サイズ交換, 商品不良, その他] 중 하나로 分類하してください.\n"
            "7. 感情 分析을 수행하してください: angry(화남/불만), curious(궁금함), grateful(感謝함), neutral(普通) 중 하나.\n"
            "8. sentiment_score는 0.0~1.0 사이의 강도です (1.0이 가장 강함).\n"
            "9. tags는 お問い合わせ内容で 抽出한 핵심 キーワード タグ 配列です (예: [\"配送지연\", \"緊急\"]).\n"
            "10. priority_suggestion은 urgent, high, normal, low 중 하나です.\n\n"
        )
        
        # 会社 CS ガイド라인 주입
        if cs_guidelines:
            system_instruction += (
                "【会社CS対応ガイドライン（必ず遵守してください）】\n"
                f"{cs_guidelines}\n"
                "--------------------------------------------------\n\n"
            )
        
        system_instruction += (
            "JSON 応答形式:\n"
            "{\n"
            '  "reply": "일본어 본문",\n'
            '  "category": "カテゴリー",\n'
            '  "sentiment": "angry|curious|grateful|neutral",\n'
            '  "sentiment_score": 0.0~1.0,\n'
            '  "tags": ["タグ1", "タグ2"],\n'
            '  "priority_suggestion": "urgent|high|normal|low"\n'
            "}"
        )

        try:
            # 모델 初期化 (検証된 最新 모델 使用)
            model = genai.GenerativeModel(
                model_name=self.model_name,
                system_instruction=system_instruction
            )
            
            prompt = f"お客様のお問い合わせ: {inquiry_text}"
            
            # 返信 生成 リクエスト
            response = await model.generate_content_async(
                prompt,
                generation_config=genai.types.GenerationConfig(
                    temperature=0.7,
                    response_mime_type="application/json"
                )
            )
            
            # 結果 パーシング
            res_text = response.text.strip()
            result = json.loads(res_text)
            
            # 필수 フィールド デフォルト値 보장
            result.setdefault("sentiment", "neutral")
            result.setdefault("sentiment_score", 0.5)
            result.setdefault("tags", [])
            result.setdefault("priority_suggestion", "normal")
            result.setdefault("category", "その他")
            
            return result
            
        except Exception as e:
            logger.error(f"[Gemini API Error] {e}")
            return {
                "reply": "申し訳ございません. 現在AI回答作成が一時的に制限されています. 手動で対応をお願いいたします.",
                "category": "その他",
                "sentiment": "neutral",
                "sentiment_score": 0.5,
                "tags": [],
                "priority_suggestion": "normal"
            }

    async def analyze_metadata(self, text: str) -> Dict[str, Any]:
        """
        顧客 お問い合わせ内容을 分析하여 메타データ(カテゴリー, 感情, タグ, 優先度)를 返却します.
        Sync Bot이나 일괄 処理 작업で 使用されます.
        """
        if self.provider == "mock":
            return {
                "category": "일반お問い合わせ",
                "sentiment": "neutral",
                "sentiment_score": 0.5,
                "tags": ["テスト"],
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
                    "JSON 応答形式:\n"
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
            
            # デフォルト値 보장
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
        """하위 호환성을 ために 維持します."""
        return await self.analyze_metadata(text)

# インスタンス 生成
ai_client = AIClient(provider="auto")
