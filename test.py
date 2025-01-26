from datetime import datetime, timedelta, timezone

now = datetime.now(timezone.utc)
print(now.isoformat())

parsed = datetime.fromisoformat(now.isoformat()) - timedelta(hours=2)
print(parsed.isoformat())

print((now - parsed) > timedelta(hours=1))
