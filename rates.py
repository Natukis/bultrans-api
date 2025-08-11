# rates.py
from functools import lru_cache
from datetime import date, timedelta
import requests

TIMEOUT_SEC = 3            # שלא יתקע את התהליך
MAX_FALLBACK_DAYS = 3      # נחפש עד +/- 3 ימים סביב התאריך

@lru_cache(maxsize=512)
def rate_to_bgn(on_date: date, currency: str) -> float:
    """
    מחזיר שער המרה למטבע BGN בתאריך נתון, עם fallback מהיר +/-3 ימים ו-cache בזיכרון.
    """
    c = (currency or "").upper()
    if c == "BGN":
        return 1.0
    if c == "EUR":
        return 1.95583  # קבוע לבולגריה

    # תאריך מדויק ואז ±1..±3 ימים (סה"כ עד 7 ניסיונות מהירים)
    for delta in range(0, MAX_FALLBACK_DAYS + 1):
        candidates = [on_date] if delta == 0 else [on_date - timedelta(days=delta), on_date + timedelta(days=delta)]
        for d in candidates:
            url = f"https://api.exchangerate.host/{d.isoformat()}?base={c}&symbols=BGN"
            try:
                r = requests.get(url, timeout=TIMEOUT_SEC)
                r.raise_for_status()
                data = r.json()
                rate = data.get("rates", {}).get("BGN")
                if rate is not None:
                    return float(rate)
            except Exception:
                continue
    raise RuntimeError(f"No FX rate for {c}->BGN near {on_date.isoformat()} (+/-{MAX_FALLBACK_DAYS}d)")
