import psutil
import csv
import time
import os
import platform
from datetime import datetime

# ── Output file ──────────────────────────────────────────────────────────────
OUTPUT_FILE = "device_health_log.csv"
INTERVAL_SECONDS = 30  # collect every 30 seconds

# ── CSV headers ──────────────────────────────────────────────────────────────
HEADERS = [
    "timestamp",
    "cpu_usage_percent",
    "cpu_temp_celsius",
    "cpu_freq_mhz",
    "ram_usage_percent",
    "ram_used_gb",
    "ram_total_gb",
    "disk_usage_percent",
    "disk_read_mb",
    "disk_write_mb",
    "battery_percent",
    "battery_plugged_in",
    "battery_status",
    "net_sent_mb",
    "net_recv_mb",
    "top_process",
    "health_score",
]


# ── CPU temperature ───────────────────────────────────────────────────────────
def get_cpu_temp():
    """Returns CPU temperature in Celsius. Works on Linux; Windows needs OpenHardwareMonitor."""
    try:
        temps = psutil.sensors_temperatures()
        if not temps:
            return None
        # Try common sensor names
        for key in ["coretemp", "cpu_thermal", "k10temp", "acpitz"]:
            if key in temps:
                return round(temps[key][0].current, 1)
        # Fallback: first available sensor
        first_key = list(temps.keys())[0]
        return round(temps[first_key][0].current, 1)
    except (AttributeError, NotImplementedError):
        # psutil.sensors_temperatures() not available on Windows by default
        return None


# ── Battery info ──────────────────────────────────────────────────────────────
def get_battery():
    battery = psutil.sensors_battery()
    if battery is None:
        return 100, True, "Desktop (no battery)"
    percent = round(battery.percent, 1)
    plugged = battery.power_plugged
    if plugged:
        status = "Charging" if percent < 100 else "Full"
    else:
        status = "Discharging"
    return percent, plugged, status


# ── Disk I/O ──────────────────────────────────────────────────────────────────
_last_disk_io = psutil.disk_io_counters()
_last_disk_time = time.time()

def get_disk_io():
    global _last_disk_io, _last_disk_time
    current = psutil.disk_io_counters()
    now = time.time()
    elapsed = now - _last_disk_time or 1
    read_mb  = round((current.read_bytes  - _last_disk_io.read_bytes)  / 1e6 / elapsed, 2)
    write_mb = round((current.write_bytes - _last_disk_io.write_bytes) / 1e6 / elapsed, 2)
    _last_disk_io   = current
    _last_disk_time = now
    return read_mb, write_mb


# ── Network I/O ───────────────────────────────────────────────────────────────
_last_net_io   = psutil.net_io_counters()
_last_net_time = time.time()

def get_network_io():
    global _last_net_io, _last_net_time
    current = psutil.net_io_counters()
    now = time.time()
    elapsed = now - _last_net_time or 1
    sent_mb = round((current.bytes_sent - _last_net_io.bytes_sent) / 1e6 / elapsed, 2)
    recv_mb = round((current.bytes_recv - _last_net_io.bytes_recv) / 1e6 / elapsed, 2)
    _last_net_io   = current
    _last_net_time = now
    return sent_mb, recv_mb


# ── Top CPU process ───────────────────────────────────────────────────────────
def get_top_process():
    try:
        procs = [(p.info["name"], p.info["cpu_percent"])
                 for p in psutil.process_iter(["name", "cpu_percent"])]
        procs = [(n, c) for n, c in procs if c is not None]
        if not procs:
            return "N/A"
        top = max(procs, key=lambda x: x[1])
        return f"{top[0]} ({top[1]}%)"
    except Exception:
        return "N/A"


# ── Rule-based health score (0–100) ──────────────────────────────────────────
def calculate_health_score(cpu_usage, cpu_temp, ram_usage, disk_usage, battery_pct):
    score = 100

    # CPU usage penalty
    if cpu_usage > 90:   score -= 25
    elif cpu_usage > 70: score -= 10
    elif cpu_usage > 50: score -= 5

    # CPU temperature penalty
    if cpu_temp is not None:
        if cpu_temp > 90:   score -= 25
        elif cpu_temp > 80: score -= 15
        elif cpu_temp > 70: score -= 8

    # RAM usage penalty
    if ram_usage > 90:   score -= 20
    elif ram_usage > 75: score -= 10
    elif ram_usage > 60: score -= 5

    # Disk usage penalty
    if disk_usage > 95:  score -= 15
    elif disk_usage > 85: score -= 8
    elif disk_usage > 75: score -= 3

    # Battery penalty
    if battery_pct < 20:  score -= 10
    elif battery_pct < 40: score -= 5

    return max(0, score)


# ── Health category label ─────────────────────────────────────────────────────
def health_label(score):
    if score >= 90: return "Excellent"
    if score >= 70: return "Good"
    if score >= 50: return "Warning"
    return "Critical"


# ── Collect one row of data ───────────────────────────────────────────────────
def collect():
    timestamp  = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cpu_usage  = round(psutil.cpu_percent(interval=1), 1)
    cpu_temp   = get_cpu_temp()
    cpu_freq   = round(psutil.cpu_freq().current, 1) if psutil.cpu_freq() else None

    ram        = psutil.virtual_memory()
    ram_usage  = round(ram.percent, 1)
    ram_used   = round(ram.used / 1e9, 2)
    ram_total  = round(ram.total / 1e9, 2)

    disk       = psutil.disk_usage("/")
    disk_usage = round(disk.percent, 1)
    disk_read, disk_write = get_disk_io()

    battery_pct, plugged, bat_status = get_battery()
    net_sent, net_recv = get_network_io()

    top_proc   = get_top_process()
    score      = calculate_health_score(cpu_usage, cpu_temp, ram_usage, disk_usage, battery_pct)

    return {
        "timestamp":          timestamp,
        "cpu_usage_percent":  cpu_usage,
        "cpu_temp_celsius":   cpu_temp,
        "cpu_freq_mhz":       cpu_freq,
        "ram_usage_percent":  ram_usage,
        "ram_used_gb":        ram_used,
        "ram_total_gb":       ram_total,
        "disk_usage_percent": disk_usage,
        "disk_read_mb":       disk_read,
        "disk_write_mb":      disk_write,
        "battery_percent":    battery_pct,
        "battery_plugged_in": plugged,
        "battery_status":     bat_status,
        "net_sent_mb":        net_sent,
        "net_recv_mb":        net_recv,
        "top_process":        top_proc,
        "health_score":       score,
    }


# ── Main loop ─────────────────────────────────────────────────────────────────
def main():
    print(f"Device Health Collector starting on {platform.system()} {platform.release()}")
    print(f"Logging to: {OUTPUT_FILE}  |  Interval: {INTERVAL_SECONDS}s")
    print("Press Ctrl+C to stop.\n")

    file_exists = os.path.isfile(OUTPUT_FILE)

    with open(OUTPUT_FILE, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=HEADERS)
        if not file_exists:
            writer.writeheader()

        while True:
            try:
                row = collect()
                writer.writerow(row)
                f.flush()  # write immediately, don't buffer

                label = health_label(row["health_score"])
                temp_str = f"{row['cpu_temp_celsius']}°C" if row["cpu_temp_celsius"] else "N/A"
                print(
                    f"[{row['timestamp']}] "
                    f"Health: {row['health_score']}/100 ({label}) | "
                    f"CPU: {row['cpu_usage_percent']}% {temp_str} | "
                    f"RAM: {row['ram_usage_percent']}% | "
                    f"Disk: {row['disk_usage_percent']}% | "
                    f"Battery: {row['battery_percent']}% {row['battery_status']}"
                )
                time.sleep(INTERVAL_SECONDS)

            except KeyboardInterrupt:
                print("\nCollection stopped. Data saved to", OUTPUT_FILE)
                break
            except Exception as e:
                print(f"Error: {e}")
                time.sleep(INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
