import asyncio
import os
import logging
import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from supabase import create_client, Client
from app.core.config import settings
from app.core.rakuten_client import RakutenRMSClient
from app.services.thread_context import fetch_and_format_inquiry_thread

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# スケジューラー グローバル インスタンス
scheduler = AsyncIOScheduler()
SYNC_STATUS_KEY = "rakuten_reconcile"


def _get_admin_supabase_client() -> Client:
    from dotenv import load_dotenv
    load_dotenv()
    admin_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not admin_key:
        raise RuntimeError("SUPABASE_SERVICE_ROLE_KEY is required for sync reconciliation.")
    return create_client(settings.SUPABASE_URL, admin_key)


def _record_sync_status(
    supabase: Client,
    *,
    status: str,
    started_at: str | None = None,
    completed_at: str | None = None,
    summary: str | None = None,
    error_message: str | None = None,
    inserted: int | None = None,
    deleted: int | None = None,
    unchanged: int | None = None,
    run_source: str | None = None,
) -> None:
    payload = {
        "sync_key": SYNC_STATUS_KEY,
        "status": status,
        "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    if started_at is not None:
        payload["last_started_at"] = started_at
    if completed_at is not None:
        payload["last_completed_at"] = completed_at
    if summary is not None:
        payload["summary"] = summary
    if error_message is not None:
        payload["error_message"] = error_message
    if inserted is not None:
        payload["inserted_count"] = inserted
    if deleted is not None:
        payload["deleted_count"] = deleted
    if unchanged is not None:
        payload["unchanged_count"] = unchanged
    if run_source is not None:
        payload["run_source"] = run_source

    try:
        supabase.table("sync_status").upsert(payload).execute()
    except Exception as sync_status_err:
        logger.error(f"[Sync Status] Failed to persist sync status: {sync_status_err}")


async def reconcile_shop_inquiries(shop: dict, supabase: Client) -> dict:
    """
    単一ショップのRMS未返信リストとDBを照合して同期化します。
    - RMSのみに存在 → INSERT (新規)
    - DBのみに存在 → DELETE (RMSで完了/返信済み)
    - 両方に存在 → 維持
    """
    platform = shop["platform"]
    shop_name = shop["shop_name"]
    shop_id = shop.get("id")
    company_id = shop.get("company_id")

    result = {
        "shop": shop_name,
        "rms_count": 0,
        "db_count": 0,
        "inserted": 0,
        "deleted": 0,
        "unchanged": 0,
        "to_insert": [],
        "to_delete": [],
        "errors": [],
    }

    # 1. RMSから現在の未返信リストを取得
    rms_inquiries = []
    if platform == "rakuten":
        rakuten = RakutenRMSClient(
            service_secret=shop.get("api_key", ""),
            license_key=shop.get("api_secret", "")
        )
        rms_inquiries = await rakuten.get_inquiry_list()

    rms_map = {inq["rakuten_inquiry_id"]: inq for inq in rms_inquiries}
    rms_ids = set(rms_map.keys())
    result["rms_count"] = len(rms_ids)
    print(f"  [RMS] {shop_name}: 未返信 {len(rms_ids)}件 受信", flush=True)

    # 2. DBから現在の該当ショップのお問い合わせリストを照会
    db_res = supabase.table("inquiries") \
        .select("id, rakuten_inquiry_id") \
        .eq("shop_id", shop_id) \
        .execute()
    db_data = db_res.data or []
    db_map = {row["rakuten_inquiry_id"]: row["id"] for row in db_data if row.get("rakuten_inquiry_id")}
    db_ids = set(db_map.keys())
    result["db_count"] = len(db_ids)
    print(f"  [DB]  {shop_name}: 既存 {len(db_ids)}件 保有", flush=True)

    # 3. 照合比較
    to_insert = rms_ids - db_ids    # RMSのみ → 新規
    to_delete = db_ids - rms_ids    # DBのみ → RMSで完了済み
    unchanged = rms_ids & db_ids    # 両方 → 維持

    if not rms_ids and db_ids:
        warning = (
            f"{shop_name}: RMS returned 0 inquiries while DB has {len(db_ids)}. "
            "Deletion skipped to avoid transient API data loss."
        )
        result["errors"].append(warning)
        print(f"  [WARN] {warning}", flush=True)
        to_delete = set()

    result["to_insert"] = sorted(to_insert)
    result["to_delete"] = sorted(to_delete)

    print(f"  [照合] 新規={len(to_insert)}件, 削除={len(to_delete)}件, 維持={len(unchanged)}件", flush=True)
    if to_insert:
        print(f"  [照合] 新規ID: {', '.join(sorted(to_insert))}", flush=True)
    if to_delete:
        print(f"  [照合] 削除ID: {', '.join(sorted(to_delete))}", flush=True)

    # 4. 新規 お問い合わせ INSERT
    for rakuten_id in to_insert:
        ext_inq = rms_map[rakuten_id]
        try:
            new_data = {
                "company_id": company_id,
                "shop_id": shop_id,
                "rakuten_inquiry_id": rakuten_id,
                "customer_id": ext_inq.get("customer_id", "Unknown"),
                "title": ext_inq.get("title", "No Title"),
                "content": ext_inq.get("content", ""),
                "received_at": ext_inq.get("received_at", datetime.datetime.utcnow().isoformat()),
                "status": "pending",
                "order_number": ext_inq.get("order_number"),
                "item_name": ext_inq.get("item_name"),
                "item_number": ext_inq.get("item_number"),
                "category": ext_inq.get("category"),
                "inquiry_type": ext_inq.get("type"),
            }
            inq_res = supabase.table("inquiries").insert(new_data).execute()
            if inq_res.data:
                result["inserted"] += 1
                new_inq_id = inq_res.data[0]["id"]
                print(f"    [SUCCESS] INSERT #{rakuten_id} ({ext_inq.get('customer_id')})", flush=True)
                
                # AI下書き生成 + カテゴリー/感情分析
                try:
                    from app.core.ai_client import ai_client
                    ai_context = dict(new_data)
                    ai_context["connected_shops"] = shop
                    ai_context["inquiry_thread"] = await fetch_and_format_inquiry_thread(ai_context)
                    ai_result = await ai_client.generate_reply(
                        inquiry_text=new_data["content"],
                        context=ai_context
                    )
                    
                    # カテゴリー, 感情, タグ, 優先度 アップデート
                    supabase.table("inquiries").update({
                        "category": ai_result.get("category", "その他"),
                        "sentiment": ai_result.get("sentiment"),
                        "sentiment_score": ai_result.get("sentiment_score"),
                        "ai_tags": ai_result.get("tags"),
                        "priority": ai_result.get("priority_suggestion")
                    }).eq("id", new_inq_id).execute()
                    
                    # AI下書き保存
                    supabase.table("reply_drafts").insert({
                        "company_id": company_id,
                        "inquiry_id": new_inq_id,
                        "ai_suggested_reply": ai_result.get("reply", "エラー"),
                        "status": "draft"
                    }).execute()
                    
                    print(f"    [AI] 下書き生成完了 #{rakuten_id}", flush=True)
                except Exception as ai_err:
                    print(f"    [AI] 下書き生成失敗 #{rakuten_id}: {ai_err}", flush=True)
        except Exception as e:
            result["errors"].append(f"INSERT {rakuten_id}: {str(e)}")
            print(f"    [ERROR] INSERT 失敗 #{rakuten_id}: {e}", flush=True)

    # 5. RMSで完了/返信済みのお問い合わせ DELETE (関連データ含む)
    for rakuten_id in to_delete:
        db_id = db_map[rakuten_id]
        try:
            # 関連データを先に削除 (外部キー制約)
            supabase.table("reply_drafts").delete().eq("inquiry_id", db_id).execute()
            supabase.table("internal_notes").delete().eq("inquiry_id", db_id).execute()
            # お問い合わせ 削除
            supabase.table("inquiries").delete().eq("id", db_id).execute()
            result["deleted"] += 1
            print(f"    [DEL] DELETE #{rakuten_id} (RMSで完了済み)", flush=True)
        except Exception as e:
            result["errors"].append(f"DELETE {rakuten_id}: {str(e)}")
            print(f"    [ERROR] DELETE 失敗 #{rakuten_id}: {e}", flush=True)

    result["unchanged"] = len(unchanged)
    return result


async def reconcile_all_shops():
    """
    全ての連携ショップについてreconciliationを実行します。
    """
    print("\n[Sync] === Reconciliation 同期化開始 ===", flush=True)
    started_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    supabase: Client = _get_admin_supabase_client()
    _record_sync_status(
        supabase,
        status="running",
        started_at=started_at,
        summary="同期化を開始しました。",
        error_message=None,
        run_source="scheduler",
    )

    try:
        shops_res = supabase.table("connected_shops").select("*").execute()
        now = datetime.datetime.now(datetime.timezone.utc)
        rakuten_shops = []
        for s in (shops_res.data or []):
            if s.get("platform") == "rakuten":
                # APIキーの有効期限をチェック
                if s.get("expires_at"):
                    try:
                        exp_date = datetime.datetime.fromisoformat(s["expires_at"].replace('Z', '+00:00'))
                        if exp_date < now:
                            print(f"[Sync] ショップ {s['shop_name']} はAPIキーが期限切れです。同期をスキップします。", flush=True)
                            continue
                    except:
                        pass
                rakuten_shops.append(s)

        print(f"[Sync] Rakuten ショップ {len(rakuten_shops)}件 対象 (有効期限内)", flush=True)

        all_results = []
        for shop in rakuten_shops:
            shop_result = await reconcile_shop_inquiries(shop, supabase)
            all_results.append(shop_result)

        # 全体集計
        total_inserted = sum(r["inserted"] for r in all_results)
        total_deleted = sum(r["deleted"] for r in all_results)
        total_unchanged = sum(r["unchanged"] for r in all_results)
        total_errors = sum(len(r["errors"]) for r in all_results)

        shop_summaries = [
            (
                f"{r['shop']}: RMS{r.get('rms_count', 0)} / DB{r.get('db_count', 0)} / "
                f"新規{r['inserted']} / 削除{r['deleted']} / 維持{r['unchanged']}"
            )
            for r in all_results
        ]
        summary = (
            f"同期化完了: 新規 {total_inserted}件, 削除 {total_deleted}件, 維持 {total_unchanged}件"
            f" | {'; '.join(shop_summaries)}"
        )
        if total_errors > 0:
            summary += f", エラー {total_errors}件"
        error_message = None
        if total_errors > 0:
            error_message = " | ".join(
                error
                for result in all_results
                for error in result.get("errors", [])
            )

        print(f"[Sync] === {summary} ===\n", flush=True)
        completed_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
        _record_sync_status(
            supabase,
            status="warning" if total_errors > 0 else "success",
            started_at=started_at,
            completed_at=completed_at,
            summary=summary,
            error_message=error_message,
            inserted=total_inserted,
            deleted=total_deleted,
            unchanged=total_unchanged,
            run_source="scheduler",
        )

        return {
            "summary": summary,
            "shops": all_results,
            "totals": {
                "inserted": total_inserted,
                "deleted": total_deleted,
                "unchanged": total_unchanged,
                "errors": total_errors,
            }
        }

    except Exception as e:
        import traceback
        print(f"[ERROR] [Sync] Critical Error: {e}", flush=True)
        traceback.print_exc()
        completed_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
        _record_sync_status(
            supabase,
            status="error",
            started_at=started_at,
            completed_at=completed_at,
            summary="同期化中にエラーが発生しました。",
            error_message=str(e),
            run_source="scheduler",
        )
        return {"summary": f"エラーが発生しました: {str(e)}", "shops": [], "totals": {}}


async def start_bot():
    """
    FastAPIサーバー開始時に呼び出されスケジューラーを開始します。
    """
    async def delayed_start():
        await asyncio.sleep(5)
        print("[Sync Bot] サーバー安定化完了。初回同期化開始...", flush=True)
        await reconcile_all_shops()

    asyncio.create_task(delayed_start())

    # スケジューラー登録 (10分間隔)
    if not scheduler.running:
        scheduler.add_job(reconcile_all_shops, 'interval', minutes=settings.SYNC_INTERVAL_MINUTES)
        scheduler.start()
        print(f"[Sync Bot] スケジューラー開始 ({settings.SYNC_INTERVAL_MINUTES}分周期 reconciliation)", flush=True)
