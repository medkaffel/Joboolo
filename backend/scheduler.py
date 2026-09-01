import os
import logging
from datetime import datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from database import get_database
from email_service import build_alert_html, send_alert_email
from campaign_lifecycle import fetch_public_job_filter, is_campaign_diffusible

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()

APP_URL = os.environ.get("FRONTEND_URL", "https://job-platform-next.preview.emergentagent.com")


def _build_job_query(alert: dict, since: datetime, public_filter: dict) -> dict:
    query = {**public_filter, "created_at": {"$gt": since}}
    if alert.get("search"):
        s = alert["search"]
        query["$or"] = [
            {"title": {"$regex": s, "$options": "i"}},
            {"description": {"$regex": s, "$options": "i"}},
        ]
    if alert.get("location"):
        query["location"] = {"$regex": alert["location"], "$options": "i"}
    if alert.get("job_type"):
        query["job_type"] = alert["job_type"]
    if alert.get("is_remote") is not None:
        query["is_remote"] = alert["is_remote"]
    if alert.get("salary_min"):
        query["salary_min"] = {"$gte": alert["salary_min"]}
    return query


async def process_alerts():
    """Daily job: for each active alert, email new matching jobs."""
    db = await get_database()
    now = datetime.utcnow()
    cursor = db.alerts.find({"is_active": True, "frequency": {"$ne": "never"}})
    alerts = await cursor.to_list(length=1000)
    logger.info(f"[alerts] Processing {len(alerts)} active alerts")

    for alert in alerts:
        freq = alert.get("frequency", "daily")
        last_sent = alert.get("last_sent_at")

        if freq == "weekly":
            window = timedelta(days=7)
        else:  # daily and instant handled daily
            window = timedelta(days=1)

        if last_sent:
            if isinstance(last_sent, str):
                last_sent = datetime.fromisoformat(last_sent)
            # weekly: skip if less than 7 days since last send
            if freq == "weekly" and (now - last_sent) < timedelta(days=7):
                continue
            since = last_sent
        else:
            since = now - window

        # P0-006 : les alertes ne doivent jamais exposer les offres de
        # campagnes non diffusibles.
        public_filter = await fetch_public_job_filter(db, now)
        query = _build_job_query(alert, since, public_filter)
        jobs = await db.jobs.find(query).sort([("created_at", -1)]).limit(10).to_list(length=10)

        if not jobs:
            continue

        user = await db.users.find_one({"_id": alert["user_id"]})
        if not user or not user.get("email"):
            continue

        html = build_alert_html(alert.get("name", "Alerte"), jobs, APP_URL, alert.get("_id"))
        subject = f"{len(jobs)} nouvelle(s) offre(s) — {alert.get('name', 'Joboolo')}"
        await send_alert_email(user["email"], subject, html)

        await db.alerts.update_one(
            {"_id": alert["_id"]},
            {"$set": {"last_sent_at": now}},
        )


async def refresh_campaign_feeds():
    """Hourly check: auto-refresh each active campaign's XML feed when due
    (based on the admin-configured frequency in general settings)."""
    db = await get_database()
    settings = await db.settings.find_one({"_id": "global"}) or {}
    refresh_hours = int(settings.get("feed_refresh_hours", 24) or 24)
    now = datetime.utcnow()
    due = now - timedelta(hours=refresh_hours)

    campaigns = await db.campaigns.find({
        "status": "active",
        "xml_feed_url": {"$nin": [None, ""]},
    }).to_list(length=1000)
    logger.info(f"[feeds] Checking {len(campaigns)} campaigns for auto-refresh (every {refresh_hours}h)")

    from partner_feed import import_campaign_feed
    from email_service import build_auto_import_email, send_alert_email
    auto_email = bool(settings.get("auto_import_email", True))
    for camp in campaigns:
        # P0-006 : une campagne paused/future/expirée/budget épuisé n'est pas
        # diffusible => on saute son import auto sans rien réimporter.
        if not is_campaign_diffusible(camp, now):
            continue
        last = camp.get("last_import_at")
        if isinstance(last, str):
            try:
                last = datetime.fromisoformat(last)
            except Exception:
                last = None
        if last and last > due:
            continue  # not due yet
        try:
            res = await import_campaign_feed(db, camp, None, trigger="auto")
            logger.info(f"[feeds] Campaign {camp['_id']}: +{res['imported']} new, {res['updated']} updated")
            # Récapitulatif email au partenaire (uniquement s'il y a de l'activité)
            if auto_email and (res.get("imported", 0) or res.get("updated", 0)):
                try:
                    partner = await db.users.find_one({"_id": camp["partner_id"]})
                    profile = await db.partner_profiles.find_one({"user_id": camp["partner_id"]}) or {}
                    if partner and partner.get("email"):
                        subject, html = build_auto_import_email(
                            profile.get("company_name") or "Partenaire",
                            camp.get("name", "Campagne"),
                            res.get("imported", 0), res.get("updated", 0), APP_URL,
                        )
                        await send_alert_email(partner["email"], subject, html)
                except Exception as e:
                    logger.warning(f"[feeds] auto-import email failed for {camp['_id']}: {e}")
        except Exception as e:
            logger.warning(f"[feeds] Campaign {camp['_id']} import failed: {e}")


def start_scheduler():
    if scheduler.running:
        return
    # Daily digest at 08:00 UTC
    scheduler.add_job(process_alerts, "cron", hour=8, minute=0, id="daily_alerts", replace_existing=True)
    # Hourly feed-refresh check (respects admin frequency)
    scheduler.add_job(refresh_campaign_feeds, "interval", hours=1, id="feed_refresh", replace_existing=True)
    scheduler.start()
    logger.info("[scheduler] Started (alerts 08:00 UTC, feed refresh hourly)")
