import glob
import gzip
import json
import logging
import math
import os
import time
from datetime import datetime, timezone, timedelta

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

try:
    import pandas as pd
except ImportError:
    logging.debug("Unable to import pandas (required for ambient.loaddf)")


REST_API_BASE = "https://api.ambientweather.net/v1"
RETRIES = 5
BACKOFF_FACTOR = 1
STATUS_FORCELIST = [401, 413, 429, 503]  # defaults + 401 for flaky API
LIMIT = 288
PARAMS = {
    "apiKey": os.environ["API_KEY"],
    "applicationKey": os.environ["APPLICATION_KEY"],
    "limit": LIMIT,
}


def last_midnight_utc():
    """Returns a datetime for the most recent 23:59 UTC."""
    ago_24h = datetime.now(tz=timezone.utc) - timedelta(days=1)
    return datetime(ago_24h.year, ago_24h.month, ago_24h.day, 23, 59, tzinfo=timezone.utc)


def now_utc():
    return datetime.now(tz=timezone.utc)


def session():
    # https://www.peterbe.com/plog/best-practice-with-retries-with-requests
    s = requests.Session()
    s.params = PARAMS
    retry = Retry(
        total=RETRIES,
        read=RETRIES,
        connect=RETRIES,
        backoff_factor=BACKOFF_FACTOR,
        status_forcelist=STATUS_FORCELIST,
    )
    adapter = HTTPAdapter(max_retries=retry)
    s.mount(REST_API_BASE, adapter)
    return s


s = session()


def getdata(end: datetime, start=None):
    """Get records from start to end. Gets previous 24 hours if start is None."""
    time.sleep(1.1)  # < 1 request per second
    params = {"endDate": end.isoformat()}
    if start:
        five_min_intervals = math.ceil((end - start).total_seconds() / (5 * 60))
        params["limit"] = str(five_min_intervals)
    r = s.get(
        f"{REST_API_BASE}/devices/{os.environ['MAC']}",
        params=params,
    )
    r.raise_for_status()
    return r.json()


def overwrite_since_midnight():
    start = last_midnight_utc()
    end = now_utc()
    data = getdata(end=end, start=start)
    prettydate = f"{end.date().isoformat()}"
    logging.warning(f"Got {len(data)} records for {prettydate}. Expected up to {LIMIT}")
    with gzip.open(prettydate + ".json.gz", "wt", encoding="ascii") as f:
        f.write(json.dumps(data))


def overwrite_yesterday():
    end = last_midnight_utc()
    data = getdata(end=end)
    prettydate = f"{end.date().isoformat()}"
    logging.warning(f"Got {len(data)} records for {prettydate}. Expected {LIMIT}")
    with gzip.open(prettydate + ".json.gz", "wt", encoding="ascii") as f:
        f.write(json.dumps(data))


def loaddf():
    jsonfiles = glob.glob("*.json.gz")
    df = pd.concat(pd.read_json(jsonfile) for jsonfile in jsonfiles)
    df.index = pd.to_datetime(df.date)
    df.index = df.index.tz_convert("US/Pacific")
    df = df.sort_index()
    df = df[~df.duplicated()]
    return df
