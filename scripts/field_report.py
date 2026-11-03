"""Read-only summary of alert delivery and camera health for a field check."""
import argparse
from datetime import datetime
from math import ceil
from pathlib import Path
import sqlite3
from statistics import median
import time

from watchyard.runtime import data_directory


def summary(db, cutoff):
    cameras = [dict(row) for row in db.execute(
        "SELECT camera_name, label, count(*) AS events, "
        "SUM(feedback='useful') AS useful, SUM(feedback='false_alarm') AS false_alarms "
        "FROM events WHERE created>=? GROUP BY camera_name,label ORDER BY camera_name,label",
        (cutoff,))]
    delivery = dict(db.execute(
        "SELECT d.status,count(*) FROM recipient_deliveries d JOIN events e ON d.event_id=e.id "
        "WHERE e.created>=? AND d.recipient NOT LIKE 'pushover:%' AND d.recipient NOT LIKE 'webhook:%' "
        "GROUP BY d.status", (cutoff,)))
    delays = sorted(row[0] for row in db.execute(
        "SELECT d.sent_at-e.created FROM recipient_deliveries d JOIN events e ON d.event_id=e.id "
        "WHERE e.created>=? AND d.status='sent' AND d.sent_at>=e.created "
        "AND d.recipient NOT LIKE 'pushover:%' AND d.recipient NOT LIKE 'webhook:%'", (cutoff,)))
    samples, low, peak = db.execute(
        "SELECT count(*),min(online),max(memory_mb) FROM samples WHERE created>=?", (cutoff,)
    ).fetchone()
    health = db.execute("SELECT count(*) FROM health_outbox WHERE created>=?", (cutoff,)).fetchone()[0]
    return cameras, delivery, delays, (samples, low, peak), health


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--hours', type=int, default=24)
    parser.add_argument('--data', type=Path, default=data_directory())
    args = parser.parse_args()
    if not 1 <= args.hours <= 168:
        parser.error('--hours must be between 1 and 168')
    cutoff = time.time()-args.hours*3600
    uri = (args.data/'events.db').resolve().as_uri()+'?mode=ro'
    try:
        with sqlite3.connect(uri, uri=True) as db:
            db.row_factory = sqlite3.Row
            cameras, delivery, delays, resources, health = summary(db, cutoff)
    except sqlite3.Error as exc:
        parser.exit(1, f'Could not read Watchyard event data: {exc}\n')
    print(f'Watchyard field report since {datetime.fromtimestamp(cutoff).astimezone():%Y-%m-%d %H:%M %Z}')
    for row in cameras:
        print(f"{row['camera_name']} / {row['label']}: {row['events']} events, "
              f"{row['useful']} useful, {row['false_alarms']} false alarms")
    print(f"Telegram deliveries: {delivery.get('sent', 0)} accepted, {delivery.get('grouped', 0)} "
          f"repeats suppressed, {delivery.get('pending', 0)} pending, {delivery.get('cancelled', 0)} cancelled")
    if delays:
        print(f'Telegram acceptance delay: median {median(delays):.1f}s, '
              f'p95 {delays[ceil(.95*len(delays))-1]:.1f}s ({len(delays)} deliveries)')
    samples, low, peak = resources
    if samples:
        print(f'Resource samples: {samples}, fewest cameras online {low}, peak process memory {peak} MiB')
    print(f'Health notices: {health}')
    print('Use a known walk or drive and its NVR footage to measure misses and mistaken groups.')


if __name__ == '__main__':
    main()
