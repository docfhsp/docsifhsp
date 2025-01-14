# filename: analytics.py

import logging
import asyncio
from upstash_redis import Redis as UpstashRedis
from datetime import datetime
from collections import defaultdict
from typing import Dict
from functools import partial

logger = logging.getLogger(__name__)


class Analytics:
    def __init__(
        self, url: str, token: str, sync_interval: int = 60, max_retries: int = 5
    ):
        """
        Initializes the Analytics class with an Upstash Redis client (HTTP-based),
        wrapped in async methods by using run_in_executor.

        We maintain two dictionaries:
         - current_totals: absolute counters (loaded from Redis at startup).
         - new_increments: only the new usage since last sync.

        Both structures only track a single label "docsifer" for access/tokens.
        """
        self.url = url
        self.token = token
        self.sync_interval = sync_interval
        self.max_retries = max_retries

        # Create the synchronous Upstash Redis client over HTTP
        self.redis_client = self._create_redis_client()

        # current_totals: absolute counters from Redis
        self.current_totals = {
            "access": defaultdict(lambda: defaultdict(int)),
            "tokens": defaultdict(lambda: defaultdict(int)),
        }
        # new_increments: only new usage since the last successful sync
        self.new_increments = {
            "access": defaultdict(lambda: defaultdict(int)),
            "tokens": defaultdict(lambda: defaultdict(int)),
        }

        # Async lock to protect shared data
        self.lock = asyncio.Lock()

        # Start initial sync from Redis, then a periodic sync task
        asyncio.create_task(self._initialize())

        logger.info("Initialized Analytics with Upstash Redis: %s", url)

    def _create_redis_client(self) -> UpstashRedis:
        """Creates and returns a new Upstash Redis (synchronous) client."""
        return UpstashRedis(url=self.url, token=self.token)

    async def _initialize(self):
        """
        Fetch existing data from Redis into current_totals,
        then start the periodic sync task.
        """
        try:
            await self._sync_from_redis()
            logger.info("Initial sync from Upstash Redis completed successfully.")
        except Exception as e:
            logger.error("Error during initial Redis sync: %s", e)

        asyncio.create_task(self._start_sync_task())

    def _get_period_keys(self):
        """
        Returns day, week, month, year keys based on current UTC date.
        Also consider "total" if you want an all-time key.

        Example: ("2025-01-14", "2025-W02", "2025-01", "2025", "total")
        """
        now = datetime.utcnow()
        day_key = now.strftime("%Y-%m-%d")
        week_key = f"{now.year}-W{now.strftime('%U')}"
        month_key = now.strftime("%Y-%m")
        year_key = now.strftime("%Y")
        # For convenience, also track everything in "total".
        return day_key, week_key, month_key, year_key, "total"

    async def access(self, tokens: int):
        """
        Records an access and token usage for the "docsifer" label.
        This function updates both current_totals and new_increments.
        """
        day_key, week_key, month_key, year_key, total_key = self._get_period_keys()

        async with self.lock:
            # For each time period, increment "docsifer" usage
            for period in [day_key, week_key, month_key, year_key, total_key]:
                # Increase new usage
                self.new_increments["access"][period]["docsifer"] += 1
                self.new_increments["tokens"][period]["docsifer"] += tokens

                # Also update the absolute totals for immediate stats
                self.current_totals["access"][period]["docsifer"] += 1
                self.current_totals["tokens"][period]["docsifer"] += tokens

    async def stats(self) -> Dict[str, Dict[str, Dict[str, int]]]:
        """
        Returns a snapshot of current stats (absolute totals).
        We use current_totals, which is always up to date.
        """
        async with self.lock:
            return {
                "access": {
                    period: dict(models)
                    for period, models in self.current_totals["access"].items()
                },
                "tokens": {
                    period: dict(models)
                    for period, models in self.current_totals["tokens"].items()
                },
            }

    async def _sync_from_redis(self):
        """
        Pull existing data from Redis into current_totals and reset new_increments.
        We read "analytics:access:*" and "analytics:tokens:*" keys via SCAN.
        """
        loop = asyncio.get_running_loop()

        async with self.lock:
            # Reset both structures
            self.current_totals = {
                "access": defaultdict(lambda: defaultdict(int)),
                "tokens": defaultdict(lambda: defaultdict(int)),
            }
            self.new_increments = {
                "access": defaultdict(lambda: defaultdict(int)),
                "tokens": defaultdict(lambda: defaultdict(int)),
            }

            # ---------------------------
            # Load "access" data
            # ---------------------------
            cursor = 0
            while True:
                scan_result = await loop.run_in_executor(
                    None,
                    partial(
                        self.redis_client.scan,
                        cursor=cursor,
                        match="analytics:access:*",
                        count=1000,
                    ),
                )
                cursor, keys = scan_result[0], scan_result[1]

                for key in keys:
                    # key => "analytics:access:<period>"
                    period = key.replace("analytics:access:", "")
                    data = await loop.run_in_executor(
                        None,
                        partial(self.redis_client.hgetall, key),
                    )
                    for name_key, count_str in data.items():
                        self.current_totals["access"][period][name_key] = int(count_str)

                if cursor == 0:
                    break

            # ---------------------------
            # Load "tokens" data
            # ---------------------------
            cursor = 0
            while True:
                scan_result = await loop.run_in_executor(
                    None,
                    partial(
                        self.redis_client.scan,
                        cursor=cursor,
                        match="analytics:tokens:*",
                        count=1000,
                    ),
                )
                cursor, keys = scan_result[0], scan_result[1]

                for key in keys:
                    # key => "analytics:tokens:<period>"
                    period = key.replace("analytics:tokens:", "")
                    data = await loop.run_in_executor(
                        None,
                        partial(self.redis_client.hgetall, key),
                    )
                    for name_key, count_str in data.items():
                        self.current_totals["tokens"][period][name_key] = int(count_str)

                if cursor == 0:
                    break

    async def _sync_to_redis(self):
        """
        Push the new_increments to Redis with HINCRBY,
        then reset new_increments to zero if successful.
        """
        loop = asyncio.get_running_loop()

        async with self.lock:
            try:
                # Sync "access" increments
                for period, models in self.new_increments["access"].items():
                    redis_key = f"analytics:access:{period}"
                    for name_key, count_val in models.items():
                        if count_val != 0:
                            await loop.run_in_executor(
                                None,
                                partial(
                                    self.redis_client.hincrby,
                                    redis_key,
                                    name_key,
                                    count_val,
                                ),
                            )

                # Sync "tokens" increments
                for period, models in self.new_increments["tokens"].items():
                    redis_key = f"analytics:tokens:{period}"
                    for name_key, count_val in models.items():
                        if count_val != 0:
                            await loop.run_in_executor(
                                None,
                                partial(
                                    self.redis_client.hincrby,
                                    redis_key,
                                    name_key,
                                    count_val,
                                ),
                            )

                logger.info("Analytics data synced to Upstash Redis.")

                # Reset new_increments only
                self.new_increments = {
                    "access": defaultdict(lambda: defaultdict(int)),
                    "tokens": defaultdict(lambda: defaultdict(int)),
                }

            except Exception as e:
                logger.error("Error syncing to Redis: %s", e)
                raise e

    async def _start_sync_task(self):
        """Periodically sync local increments to Redis."""
        while True:
            await asyncio.sleep(self.sync_interval)
            try:
                await self._sync_to_redis()
            except Exception as e:
                logger.error("Error during scheduled sync: %s", e)
                await self._handle_redis_reconnection()

    async def _handle_redis_reconnection(self):
        """
        Attempts to reconnect to Redis if connection fails (HTTP-based, stateless).
        """
        loop = asyncio.get_running_loop()
        retry_count = 0
        delay = 1

        while retry_count < self.max_retries:
            try:
                logger.info(
                    "Attempting Redis reconnection (attempt %d)...", retry_count + 1
                )
                await loop.run_in_executor(None, self.redis_client.close)
                self.redis_client = self._create_redis_client()
                logger.info("Reconnected to Redis successfully.")
                return
            except Exception as e:
                logger.error("Reconnection attempt %d failed: %s", retry_count + 1, e)
                retry_count += 1
                await asyncio.sleep(delay)
                delay *= 2

        logger.critical("Max reconnection attempts reached. Redis is unavailable.")

    async def close(self):
        """
        Close the Upstash Redis client (though it's stateless over HTTP).
        """
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self.redis_client.close)
        logger.info("Redis client closed.")
