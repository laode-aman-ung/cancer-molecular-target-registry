"""
CMTR Scheduler — jalankan pipeline secara terjadwal dengan APScheduler.
Jalankan: python scheduler.py
"""

import logging
import os

from dotenv import load_dotenv
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

scheduler = BlockingScheduler(timezone="UTC")


@scheduler.scheduled_job(CronTrigger(hour=2, minute=0))  # setiap hari jam 02:00 UTC
def daily_incremental():
    logger.info("Scheduler: daily incremental sync start")
    from cmtr.pipeline import run_all
    run_all(incremental=True)
    logger.info("Scheduler: daily incremental sync done")


@scheduler.scheduled_job(CronTrigger(day_of_week="sun", hour=3, minute=0))  # tiap Minggu jam 03:00 UTC
def weekly_full():
    logger.info("Scheduler: weekly full sync start")
    from cmtr.pipeline import run_all
    run_all(incremental=False)
    logger.info("Scheduler: weekly full sync done")


if __name__ == "__main__":
    logger.info("CMTR Scheduler running. Daily incremental: 02:00 UTC. Weekly full: Sunday 03:00 UTC.")
    logger.info("Press Ctrl+C to stop.")
    try:
        scheduler.start()
    except KeyboardInterrupt:
        logger.info("Scheduler stopped.")
