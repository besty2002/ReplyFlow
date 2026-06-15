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
        inquiry_thread = context.get("inquiry_thread", "記録なし")
        
        # 복수 상품 정보 처리
        items_list = context.get("items", [])
        items_context = ""
        if items_list:
            for idx, itm in enumerate(items_list, 1):
                i_name = itm.get("item_name", "名称不明")
                i_sub = itm.get("sub_code", "コードなし")
                i_stock = itm.get("stock_count")
                i_stock_str = f"{i_stock}個" if i_stock is not None else "確認中"
                items_context += f"■ 対象商品{idx}: {i_name} (サブコード: {i_sub})\n■ 商品{idx}の在庫: {i_stock_str}\n"
        else:
            stock_info = f"{stock_count}個" if stock_count is not None else "確認中"
            items_context = f"■ 対象商品: {item_name}\n■ 現在の在庫: {stock_info}\n"
        
        # 発送 판정 コンテキスト
        shipping_context = ""
        if shipping_verdict:
            shipping_context = f"■ 発送判定: {shipping_verdict}\n■ 判定理由: {shipping_reason}\n"
        
        # ヤマト 配送情報 抽出
        delivery_info = context.get("delivery_info")
        delivery_context = ""
        if delivery_info and delivery_info.get("tracking_number") != "-":
            delivery_context = (
                f"■ 伝票番号: {delivery_info.get('tracking_number')}\n"
                f"■ 配送ステータス: {delivery_info.get('current_status')}\n"
                f"■ 現在位置/予定: {delivery_info.get('current_location')}\n"
            )

        # システム プロンプト (일본어 대응 중심 + 感情分析 + 태깅)
        system_instruction = (
            "あなたは日本 楽天市場の優秀なカスタマーサポート専門AIです。\n"
            f"顧客名（{customer_name} 様）へ丁寧かつ自然な日本語で対応してください。\n\n"
            "【厳守事項 - 曖昧な回答の禁止】\n"
            "❌ 「確認して改めてご連絡します」「担当部署に申し伝えます」「現状ではわかりかねます」等の曖昧・一時的な回答は絶対に禁止です。\n"
            "⭕ 与えられた「全対話スレッド」「リアルタイム情報」「会社CSガイドライン」のみに基づいて、即時解決できる『最終的な回答(1-shot resolution)』を作成してください。\n"
            "もし情報が不足して本当に解決できない場合は、回答を作成する代わりに category を「要確認(Human Review)」としてください。\n\n"
            "以下の【リアルタイム 情報】を基に回答を作成してください:\n"
            "--------------------------------------------------\n"
            f"■ 注文ステータス: {order_status}\n"
            f"{items_context}"
            f"{shipping_context}"
            f"{delivery_context}"
            "--------------------------------------------------\n\n"
            "【応対ガイドライン】\n"
            "1. 発送可能の場合は「即日発送可能」を強調してください。\n"
            "2. 発送不可(在庫なし)の場合は「お取り寄せとなり、7-10営業日ほどお時間をいただきます」と明確に案内してください。\n"
            "3. 既に発送済みの場合は、配送ステータス(現在の位置等)を具体的に言及し安心させてください。\n"
            "4. 顧客がスレッド(過去のやり取り)で既に伝えた情報(写真送付済み等)は再度尋ねないでください。\n"
            "5. 必ず最後のお客様メッセージに直接回答してください。\n"
            "6. 過去のショップ回答と矛盾する案内をしないでください。\n"
            "7. 注文番号、写真、希望内容など、スレッド内で既に提示済みの情報を再要求しないでください。\n"
            "8. スレッドに複数の商品や複数の論点がある場合は、漏れなく簡潔に触れてください。\n"
            "9. 必ずJSON形式でのみレスポンスしてください。\n"
            "10. カテゴリーは [配送問い合わせ, 在庫問い合わせ, キャンセル/返金, サイズ交換, 商品不良, その他, 要確認(Human Review)] から分類してください。\n"
            "11. 感情分析: angry(不満/怒り), curious(質問/確認), grateful(感謝), neutral(通常)。\n"
            "12. sentiment_scoreは 0.0~1.0 の間。\n"
            "13. tagsは問い合わせの核心キーワード配列 (例: [\"配送遅延\", \"緊急\"])。\n"
            "14. priority_suggestionは urgent, high, normal, low のいずれか。\n\n"
        )
        
        # 会社 CS ガイド라인 주입
        if cs_guidelines:
            system_instruction += (
                "【会社CS対応ガイドライン（必ず優先して遵守してください）】\n"
                f"{cs_guidelines}\n"
                "--------------------------------------------------\n\n"
            )
        
        system_instruction += (
            "JSON 応答形式:\n"
            "{\n"
            '  "reply": "日本語本文 (1-shot resolution)",\n'
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
            
            # 단일 메시지 대신 전체 스레드를 프롬프트로 전달
            prompt = (
                f"【顧客との全対話スレッド】\n{inquiry_thread}\n\n"
                "上記のスレッドを時系列で読み、最後のお客様メッセージに対するショップ側の最新返答を"
                "『reply』フィールドに作成してください。"
            )
            
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
