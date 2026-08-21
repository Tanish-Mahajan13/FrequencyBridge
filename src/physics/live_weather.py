import requests

# Used whenever the Open-Meteo API can't be reached (offline, rate-limited,
# blocked network, CI sandbox, etc). Keeps the sim runnable without a live
# network dependency instead of hard-crashing the whole simulation.
DEFAULT_SOLAR_CF = 0.55
DEFAULT_WIND_CF = 0.55


def get_live_weather_baselines(timeout_s: float = 5.0):
    """
    Fetches real-time cloud cover and wind speed for Tokyo (East) and Osaka (West)
    from Open-Meteo API. Returns tuple: (solar_cf_east, wind_cf_east, solar_cf_west, wind_cf_west)

    Falls back to fixed default capacity factors if the API is unreachable,
    times out, or returns an error, rather than crashing the simulation.
    """
    tokyo_url = "https://api.open-meteo.com/v1/forecast?latitude=35.6895&longitude=139.6917&current=cloudcover,windspeed_10m&timezone=Asia%2FTokyo"
    osaka_url = "https://api.open-meteo.com/v1/forecast?latitude=34.6937&longitude=135.5023&current=cloudcover,windspeed_10m&timezone=Asia%2FTokyo"

    try:
        # Fetch Tokyo
        res_t = requests.get(tokyo_url, timeout=timeout_s)
        res_t.raise_for_status()
        data_t = res_t.json()["current"]

        # Fetch Osaka
        res_o = requests.get(osaka_url, timeout=timeout_s)
        res_o.raise_for_status()
        data_o = res_o.json()["current"]

        # Convert cloudcover (0-100%) to Solar Capacity Factor (0.4 to 0.8 max)
        # Enforce minimum 0.40 so agents sit in PROFIT mode for the demo
        solar_cf_east = max(0.40, 0.8 * (1.0 - (data_t["cloudcover"] / 100.0)))
        solar_cf_west = max(0.40, 0.8 * (1.0 - (data_o["cloudcover"] / 100.0)))

        # Convert windspeed (km/h) to Wind Capacity Factor (0.4 to 0.9 max)
        wind_cf_east = max(0.40, min(0.9, data_t["windspeed_10m"] / 30.0))
        wind_cf_west = max(0.40, min(0.9, data_o["windspeed_10m"] / 30.0))

        print(f"[Live Weather] Fetched from Open-Meteo API.")
        print(f"  Tokyo (East) -> Solar Base: {solar_cf_east:.2f}, Wind Base: {wind_cf_east:.2f}")
        print(f"  Osaka (West) -> Solar Base: {solar_cf_west:.2f}, Wind Base: {wind_cf_west:.2f}")

        return solar_cf_east, wind_cf_east, solar_cf_west, wind_cf_west

    except (requests.RequestException, KeyError, ValueError) as e:
        print(f"[Live Weather] WARNING: Open-Meteo fetch failed ({e}). "
              f"Falling back to default baselines "
              f"(solar={DEFAULT_SOLAR_CF}, wind={DEFAULT_WIND_CF}).")
        return DEFAULT_SOLAR_CF, DEFAULT_WIND_CF, DEFAULT_SOLAR_CF, DEFAULT_WIND_CF