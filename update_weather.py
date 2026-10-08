#!/usr/bin/env python3
"""
WeatherCal — Автоматическое обновление прогноза погоды в Календаре Apple (iCloud).
"""

import json
import os
import subprocess
import sys
import urllib.parse
import urllib.request
from datetime import datetime, date

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(SCRIPT_DIR, "config.json")

# Соответствие кодов погоды WMO (Open-Meteo) эмодзи и русским описаниям
WMO_CODES = {
    0: ("☀️", "Ясно"),
    1: ("🌤", "Преимущественно ясно"),
    2: ("⛅️", "Переменная облачность"),
    3: ("☁️", "Пасмурно"),
    45: ("🌫", "Туман"),
    48: ("🌫", "Иней/туман"),
    51: ("🌦", "Легкая морось"),
    53: ("🌦", "Умеренная морось"),
    55: ("🌧", "Плотная морось"),
    56: ("🌧", "Ледяная морось"),
    57: ("🌧", "Сильная ледяная морось"),
    61: ("🌧", "Небольшой дождь"),
    63: ("🌧", "Дождь"),
    65: ("🌧", "Сильный дождь"),
    66: ("🌨", "Ледяной дождь"),
    67: ("🌨", "Сильный ледяной дождь"),
    71: ("🌨", "Небольшой снег"),
    73: ("🌨", "Снегопад"),
    75: ("❄️", "Сильный снегопад"),
    77: ("🌨", "Снежные зерна"),
    80: ("🌦", "Кратковременный дождь"),
    81: ("🌧", "Умеренный ливень"),
    82: ("⛈", "Сильный ливень"),
    85: ("🌨", "Небольшой снегопад"),
    86: ("❄️", "Сильный снегопад"),
    95: ("⛈", "Гроза"),
    96: ("⛈", "Гроза с мелким градом"),
    99: ("⛈", "Гроза с крупным градом"),
}

def load_config():
    default_config = {
        "calendar_name": "🌤 Погода",
        "city": "Челябинск",
        "latitude": 55.1644,
        "longitude": 61.4368,
        "forecast_days": 10,
        "hourly_step": 3
    }
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
                default_config.update(cfg)
        except Exception as e:
            print(f"Ошибка чтения config.json: {e}")

    # Если координаты не заданы, определяем их по названию города
    if "latitude" not in default_config or "longitude" not in default_config:
        city_name = default_config.get("city", "Челябинск")
        geo_url = f"https://geocoding-api.open-meteo.com/v1/search?name={urllib.parse.quote(city_name)}&count=1&language=ru&format=json"
        try:
            req = urllib.request.Request(geo_url, headers={"User-Agent": "WeatherCal/1.0"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                geo_data = json.loads(resp.read().decode())
                if "results" in geo_data and geo_data["results"]:
                    res = geo_data["results"][0]
                    default_config["latitude"] = res["latitude"]
                    default_config["longitude"] = res["longitude"]
                    default_config["city"] = res.get("name", city_name)
        except Exception as e:
            print(f"Не удалось уточнить геопозицию города {city_name}: {e}")

    return default_config

def format_temp(temp):
    rounded = round(temp)
    if rounded > 0:
        return f"+{rounded}°"
    elif rounded == 0:
        return "0°"
    else:
        return f"{rounded}°"

def get_weather_desc(code):
    return WMO_CODES.get(code, ("🌤", "Облачно"))

def fetch_weather(lat, lon, days=10):
    url = (
        f"https://api.open-meteo.com/v1/forecast?"
        f"latitude={lat}&longitude={lon}&"
        f"forecast_days={days}&"
        f"hourly=temperature_2m,precipitation_probability,weather_code&"
        f"daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,wind_speed_10m_max,uv_index_max&"
        f"timezone=auto"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "WeatherCal/1.0"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))

def escape_applescript(text):
    return text.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n')

def update_calendar(config, weather_data):
    cal_name = config["calendar_name"]
    hourly_step = config.get("hourly_step", 3)

    daily = weather_data.get("daily", {})
    hourly = weather_data.get("hourly", {})
    daily_times = daily.get("time", [])

    # Группировка почасовых данных по дням (YYYY-MM-DD)
    hourly_by_day = {}
    h_times = hourly.get("time", [])
    h_temps = hourly.get("temperature_2m", [])
    h_precs = hourly.get("precipitation_probability", [])
    h_codes = hourly.get("weather_code", [])

    for i, t_str in enumerate(h_times):
        # t_str example: "2026-10-08T14:00"
        dt = datetime.fromisoformat(t_str)
        d_key = dt.strftime("%Y-%m-%d")
        if d_key not in hourly_by_day:
            hourly_by_day[d_key] = []
        hourly_by_day[d_key].append({
            "hour": dt.strftime("%H"),  # '08', '11', '14' (без :00)
            "int_hour": dt.hour,
            "temp": h_temps[i] if i < len(h_temps) else 0,
            "prec": h_precs[i] if i < len(h_precs) else 0,
            "code": h_codes[i] if i < len(h_codes) else 0,
        })

    events_to_create = []

    for idx, d_str in enumerate(daily_times):
        dt = datetime.strptime(d_str, "%Y-%m-%d")
        w_code = daily["weather_code"][idx]
        emoji, desc = get_weather_desc(w_code)
        t_max = format_temp(daily["temperature_2m_max"][idx])
        t_min = format_temp(daily["temperature_2m_min"][idx])
        prec_max = daily["precipitation_probability_max"][idx]
        wind_max = round(daily["wind_speed_10m_max"][idx])
        uv = daily.get("uv_index_max", [None])[idx]

        summary = f"{emoji} {t_min} / {t_max} {desc}"

        # Формирование почасовых заметок
        notes_lines = [
            f"Вероятность осадков: {prec_max}%",
            f"Макс. ветер: {wind_max} км/ч",
        ]
        if uv is not None:
            notes_lines.append(f"УФ-индекс: {uv}")
        
        day_hours = hourly_by_day.get(d_str, [])
        if day_hours:
            notes_lines.append("")
            notes_lines.append("По часам:")
            # Выбираем часы с шагом hourly_step (например, 08, 11, 14, 17, 20, 23)
            for h_item in day_hours:
                if h_item["int_hour"] % hourly_step == 0 or (idx == 0 and h_item["int_hour"] >= datetime.now().hour and len(notes_lines) < 15):
                    h_emoji, _ = get_weather_desc(h_item["code"])
                    h_t = format_temp(h_item["temp"])
                    h_p = h_item["prec"]
                    prec_text = f" (осадки: {h_p}%)" if h_p > 0 else ""
                    notes_lines.append(f"{h_item['hour']}  {h_emoji} {h_t}{prec_text}")

        notes = "\n".join(notes_lines)

        events_to_create.append({
            "year": dt.year,
            "month": dt.month,
            "day": dt.day,
            "summary": summary,
            "notes": notes,
        })

    # Генерируем единый скрипт AppleScript
    as_lines = [
        'tell application "Calendar"',
        f'    set targetCals to (every calendar whose name is "{escape_applescript(cal_name)}")' ,
        '    if (count of targetCals) is 0 then',
        f'        error "Календарь \\"{escape_applescript(cal_name)}\\" не найден в приложении Календарь!"',
        '    end if',
        '    set targetCal to first item of targetCals',
        '',
        '    -- 1. Удаляем события на сегодня и будущее (сохраняя прошлую историю)',
        '    set todayStart to current date',
        '    set time of todayStart to 0',
        '    tell targetCal',
        '        set futureEvents to (every event whose start date ≥ todayStart)',
        '        repeat with ev in futureEvents',
        '            delete ev',
        '        end repeat',
        '    end tell',
        '',
        '    -- 2. Создаем новые события',
        '    tell targetCal',
    ]

    for ev in events_to_create:
        as_lines.extend([
            '        set evStart to current date',
            f'        set year of evStart to {ev["year"]}',
            f'        set month of evStart to {ev["month"]}',
            f'        set day of evStart to {ev["day"]}',
            '        set time of evStart to 0',
            '        set evEnd to evStart',
            f'        make new event with properties {{summary:"{escape_applescript(ev["summary"])}", start date:evStart, end date:evEnd, allday event:true, description:"{escape_applescript(ev["notes"])}"}}',
        ])

    as_lines.extend([
        '    end tell',
        '    return "OK"',
        'end tell'
    ])

    full_applescript = "\n".join(as_lines)
    proc = subprocess.run(["osascript", "-e", full_applescript], capture_output=True, text=True)

    if proc.returncode != 0:
        print("Ошибка при обновлении Календаря:")
        print(proc.stderr)
        return False
    
    print(f"✅ Успешно обновлено {len(events_to_create)} дней в календаре «{cal_name}»!")
    return True

def main():
    config = load_config()
    print(f"🌤 Запрос погоды для: {config['city']} ({config['latitude']}, {config['longitude']})...")
    try:
        weather_data = fetch_weather(config["latitude"], config["longitude"], days=config.get("forecast_days", 10))
    except Exception as e:
        print(f"Ошибка при получении прогноза погоды: {e}")
        sys.exit(1)

    print("📅 Обновление событий в Apple Календаре...")
    success = update_calendar(config, weather_data)
    if not success:
        sys.exit(1)

if __name__ == "__main__":
    main()
