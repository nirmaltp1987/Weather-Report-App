"""
Upgraded Streamlit Weather App — Open-Meteo (free, no key)
Features:
- City -> geocode via Open-Meteo
- Current weather card with emojis & metrics
- 24-hour temperature chart (next 24 hours)
- 7-day daily summary (high / low)
- Better layout (columns, tabs)
- Optional basic password gate using an environment secret (for simple access control)
"""

from typing import Optional, Dict, Any, List
import os
import requests
import streamlit as st
import pandas as pd
import altair as alt
from datetime import datetime, timedelta

GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

# Map Open-Meteo weather codes to emojis + description
WEATHER_CODE_MAP = {
    0: ("Clear sky", "☀️"),
    1: ("Mainly clear", "🌤️"),
    2: ("Partly cloudy", "⛅"),
    3: ("Overcast", "☁️"),
    45: ("Fog", "🌫️"),
    48: ("Depositing rime fog", "🌫️"),
    51: ("Light drizzle", "🌦️"),
    53: ("Moderate drizzle", "🌧️"),
    55: ("Dense drizzle", "🌧️"),
    56: ("Light freezing drizzle", "🌧️❄️"),
    57: ("Dense freezing drizzle", "🌧️❄️"),
    61: ("Slight rain", "🌧️"),
    63: ("Moderate rain", "🌧️"),
    65: ("Heavy rain", "⛈️"),
    66: ("Light freezing rain", "🌧️❄️"),
    67: ("Heavy freezing rain", "🌧️❄️"),
    71: ("Slight snow fall", "❄️"),
    73: ("Moderate snow fall", "❄️"),
    75: ("Heavy snow fall", "❄️"),
    77: ("Snow grains", "❄️"),
    80: ("Slight rain showers", "🌦️"),
    81: ("Moderate rain showers", "🌧️"),
    82: ("Violent rain showers", "⛈️"),
    85: ("Slight snow showers", "🌨️"),
    86: ("Heavy snow showers", "🌨️"),
    95: ("Thunderstorm", "⛈️⚡"),
    96: ("Thunderstorm with slight hail", "⛈️⚡"),
    99: ("Thunderstorm with heavy hail", "⛈️⚡"),
}


# ------------------------
# Helpers
# ------------------------
@st.cache_data(ttl=3600)
def geocode_city(city: str, max_results: int = 5) -> Optional[List[Dict[str, Any]]]:
    """Return a list of geocoding hits (may be multiple matches)."""
    params = {"name": city, "count": max_results, "language": "en", "format": "json"}
    resp = requests.get(GEOCODING_URL, params=params, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    results = data.get("results")
    if not results:
        return None
    return results


@st.cache_data(ttl=300)
def fetch_weather(lat: float, lon: float, timezone: str = "UTC", units: str = "metric") -> Dict[str, Any]:
    """
    Fetch current + hourly + daily from Open-Meteo.
    - hourly: we request temperature_2m, apparent_temperature, precipitation
    - daily: temperature_2m_max / min
    """
    hourly_vars = "temperature_2m,apparent_temperature,precipitation,weathercode"
    daily_vars = "temperature_2m_max,temperature_2m_min,weathercode"
    params = {
        "latitude": lat,
        "longitude": lon,
        "current_weather": True,
        "hourly": hourly_vars,
        "daily": daily_vars,
        "timezone": timezone,
    }
    resp = requests.get(FORECAST_URL, params=params, timeout=10)
    resp.raise_for_status()
    return resp.json()


def hourly_to_df(payload: Dict[str, Any]) -> pd.DataFrame:
    """Convert hourly block to a datetime-indexed DataFrame."""
    hourly = payload.get("hourly", {})
    if not hourly:
        return pd.DataFrame()
    times = pd.to_datetime(hourly.get("time", []))
    df = pd.DataFrame(
        {
            "temperature_2m": hourly.get("temperature_2m", []),
            "apparent_temperature": hourly.get("apparent_temperature", []),
            "precipitation": hourly.get("precipitation", []),
            "weathercode": hourly.get("weathercode", []),
        },
        index=times,
    )
    df.index.name = "datetime"
    return df


def daily_to_df(payload: Dict[str, Any]) -> pd.DataFrame:
    """Convert daily block to a DataFrame for the next days."""
    daily = payload.get("daily", {})
    if not daily:
        return pd.DataFrame()
    dates = pd.to_datetime(daily.get("time", []))
    df = pd.DataFrame(
        {
            "temp_max": daily.get("temperature_2m_max", []),
            "temp_min": daily.get("temperature_2m_min", []),
            "weathercode": daily.get("weathercode", []),
        },
        index=dates,
    )
    df.index.name = "date"
    return df


def code_to_desc(code: int) -> str:
    return WEATHER_CODE_MAP.get(code, ("Unknown", "❓"))[0]


def code_to_emoji(code: int) -> str:
    return WEATHER_CODE_MAP.get(code, ("Unknown", "❓"))[1]


# ------------------------
# UI pieces
# ------------------------
def render_current_card(payload: Dict[str, Any], place_name: str) -> None:
    cw = payload.get("current_weather", {}) or {}
    if not cw:
        st.info("No current weather found for this location.")
        return

    temp = cw.get("temperature")
    wind = cw.get("windspeed")
    code = cw.get("weathercode")
    time = cw.get("time")
    desc = code_to_desc(code)
    emoji = code_to_emoji(code)

    st.subheader(f"{emoji}  {place_name}")
    col1, col2 = st.columns([1, 2])
    with col1:
        st.metric(label="Temperature", value=f"{temp} °C")
        st.metric(label="Wind speed", value=f"{wind} m/s")
    with col2:
        st.write(f"**Condition:** {desc}")
        st.write(f"**Observed at:** {time}")
        st.write(f"**Weather code:** {code}")


def draw_24h_chart(hourly_df: pd.DataFrame) -> None:
    if hourly_df.empty:
        st.info("No hourly data available.")
        return

    now = datetime.utcnow()
    next_24h = hourly_df[hourly_df.index >= now].head(24)
    if next_24h.empty:
        st.info("No next-24-hour data available.")
        return

    # Build altair line chart
    chart_data = next_24h.reset_index()[["datetime", "temperature_2m", "apparent_temperature"]]
    base = alt.Chart(chart_data).encode(x="datetime:T")
    temp_line = base.mark_line().encode(y=alt.Y("temperature_2m:Q", title="Temperature (°C)"), tooltip=["datetime", "temperature_2m"])
    feel_line = base.mark_line(strokeDash=[4,3]).encode(y=alt.Y("apparent_temperature:Q", title="Feels like (°C)"), tooltip=["datetime", "apparent_temperature"])
    chart = alt.layer(temp_line, feel_line).properties(width="container", height=300).resolve_scale(y='independent')
    st.altair_chart(chart, use_container_width=True)


def show_daily_summary(daily_df: pd.DataFrame) -> None:
    if daily_df.empty:
        st.info("No daily data available.")
        return

    # Display 7-day table with emoji
    df = daily_df.head(7).copy()
    df_display = df.reset_index()
    df_display["date"] = df_display["date"].dt.date.astype(str)
    df_display["emoji"] = df_display["weathercode"].map(code_to_emoji)
    df_display = df_display[["date", "emoji", "temp_max", "temp_min"]]
    df_display.columns = ["Date", "Weather", "High (°C)", "Low (°C)"]
    st.table(df_display)


# ------------------------
# Main
# ------------------------
def main():
    st.set_page_config(page_title="Weather Report", layout="centered")
    st.title("🌤️ Weather Report")

    # Optional simple password gate — useful if you want to keep a share link private
    # Set an environment variable WEATHER_APP_PASSWORD to a simple passphrase on the deploy target (or locally).
    # If empty, no gate is used.
    app_password = os.getenv("WEATHER_APP_PASSWORD", "")
    if app_password:
        st.sidebar.markdown("App access protected")
        pw = st.sidebar.text_input("Enter app password", type="password")
        if pw != app_password:
            st.sidebar.warning("Enter password to continue")
            return

    st.markdown("Enter a city name (e.g., `London, UK`). Open-Meteo is free — no API key needed.")

    city = st.text_input("City name", placeholder="e.g., London, UK")
    units = st.selectbox("Units", options=["metric", "imperial"], index=0)
    tz_choice = st.text_input("Timezone (optional, e.g., Europe/London). Leave blank for UTC", value="")
    submit = st.button("Get Weather")

    if not submit:
        st.info("Type a city and click 'Get Weather' to fetch data.")
        return

    if not city.strip():
        st.error("Please enter a city name.")
        return

    # Geocode (may return multiple matches)
    with st.spinner("Geocoding..."):
        try:
            matches = geocode_city(city)
        except Exception as e:
            st.error(f"Geocoding failed: {e}")
            return

    if not matches:
        st.warning("Location not found. Try adding country or state (e.g., 'Springfield, IL').")
        return

    # Let user pick best match (if multiple)
    if len(matches) > 1:
        options = [f"{m.get('name')}, {m.get('admin1') or ''} {m.get('country')} ({m.get('latitude'):.3f},{m.get('longitude'):.3f})" for m in matches]
        choice = st.selectbox("Multiple matches found — choose one", options=options)
        idx = options.index(choice)
        place = matches[idx]
    else:
        place = matches[0]

    name = place.get("name")
    admin1 = place.get("admin1") or ""
    country = place.get("country")
    lat = place.get("latitude")
    lon = place.get("longitude")
    place_label = f"{name}{', ' + admin1 if admin1 else ''}, {country}"

    st.markdown(f"**Selected:** {place_label}")
    st.write(f"Coordinates: {lat:.4f}, {lon:.4f}")

    timezone = tz_choice.strip() or "UTC"

    with st.spinner("Fetching weather..."):
        try:
            payload = fetch_weather(lat, lon, timezone=timezone, units=units)
        except Exception as e:
            st.error(f"Weather fetch failed: {e}")
            return

    # Layout: left = current card, right = map + small info
    col_left, col_right = st.columns([2, 1])
    with col_left:
        render_current_card(payload, place_label)
        st.markdown("### Next 24 hours")
        draw_24h_chart(hourly_to_df(payload))
    with col_right:
        try:
            st.map(pd.DataFrame({"lat": [lat], "lon": [lon]}), zoom=6)
        except Exception:
            pass
        st.markdown("### 7-day summary")
        show_daily_summary(daily_to_df(payload))

    # Optional raw data expanders
    with st.expander("Raw full API response"):
        st.json(payload)


if __name__ == "__main__":
    main()