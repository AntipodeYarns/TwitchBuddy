# ClickHouse DDLs and guidance

Recommended table for Twitch chat / mod / trigger logging:

```sql
CREATE TABLE IF NOT EXISTS twitch_logs (
  ts DateTime64(3),
  event_type String,
  channel String,
  user String,
  triggered UInt8,
  name Nullable(String),
  details String
) ENGINE = MergeTree()
PARTITION BY toYYYYMMDD(ts)
ORDER BY (channel, ts)
TTL ts + INTERVAL 90 DAY
```

Notes:
- Keep free-form metadata in `details` as JSON. Extract into materialized columns for hot fields.
- Use Kafka/Vector for buffering if you have bursty traffic. ClickHouse supports Kafka engine and HTTP insert.
- Create materialized views for per-minute aggregates:

```sql
CREATE MATERIALIZED VIEW twitch_logs_per_minute
ENGINE = SummingMergeTree
PARTITION BY toYYYYMMDD(ts)
ORDER BY (channel, toStartOfMinute(ts))
AS
SELECT
  toStartOfMinute(ts) as minute,
  channel,
  name,
  count(*) as cnt
FROM twitch_logs
GROUP BY minute, channel, name;
```

- Adjust TTL to your retention policy. Consider moving older partitions to cheaper storage.
