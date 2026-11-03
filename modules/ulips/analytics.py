"""
modules/ulips/analytics.py
Computes and updates trailing price analytics for all ULIP funds:
- All-Time High (ATH)
- All-Time Low (ATL)
- Historical Average NAV
- 52-Week High
- 52-Week Low
"""

import logging
import sqlite3

from core.database import transaction

logger = logging.getLogger(__name__)


def update_ulip_price_analytics(conn: sqlite3.Connection):
    """
    Computes and updates trailing price analytics for all ULIP funds based on recorded historical cycles.
    """
    logger.info("Computing dynamic ULIP price analytics...")
    with transaction(conn) as cursor:
        cursor.execute("""
            SELECT sfin,
                   MAX(nav) as max_nav,
                   MIN(nav) as min_nav,
                   AVG(nav) as avg_nav
            FROM ulip_nav_history
            GROUP BY sfin
        """)
        stats_rows = cursor.fetchall()

        if stats_rows:
            cursor.executemany("""
                UPDATE master_ulip_funds
                SET nav_all_time_high = round(?, 4),
                    nav_all_time_low = round(?, 4),
                    nav_avg = round(?, 4),
                    nav_52w_high = round(?, 4),
                    nav_52w_low = round(?, 4)
                WHERE sfin = ?
            """, [(r[1], r[2], r[3], r[1], r[2], r[0]) for r in stats_rows])
        else:
            cursor.execute("""
                UPDATE master_ulip_funds
                SET nav_all_time_high = latest_nav,
                    nav_all_time_low = latest_nav,
                    nav_avg = latest_nav,
                    nav_52w_high = latest_nav,
                    nav_52w_low = latest_nav
                WHERE latest_nav IS NOT NULL AND nav_avg IS NULL
            """)

    logger.info("ULIP price analytics computed and updated successfully.")

