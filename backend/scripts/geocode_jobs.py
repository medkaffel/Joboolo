"""Backfill geospatial `loc` (GeoJSON Point) on jobs missing it, using geo.api.gouv.fr.

Run in background:  python -m scripts.geocode_jobs
Postcode->center caching keeps API calls low even for thousands of jobs.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / '.env')

from database import connect_to_mongo, get_database, close_mongo_connection
from geo_service import geocode_place


async def run():
    await connect_to_mongo()
    db = await get_database()
    cursor = db.jobs.find({"loc": {"$exists": False}}, {"_id": 1, "location": 1})
    total, done, skipped = 0, 0, 0
    batch = await cursor.to_list(length=100000)
    print(f"[geocode] {len(batch)} jobs to process")
    for job in batch:
        total += 1
        center = await geocode_place(job.get("location") or "")
        if center:
            await db.jobs.update_one(
                {"_id": job["_id"]},
                {"$set": {"loc": {"type": "Point", "coordinates": center}}},
            )
            done += 1
        else:
            skipped += 1
        if total % 200 == 0:
            print(f"[geocode] {total} processed ({done} geocoded, {skipped} skipped)")
    print(f"[geocode] DONE — {done} geocoded, {skipped} skipped out of {total}")
    await close_mongo_connection()


if __name__ == "__main__":
    asyncio.run(run())
