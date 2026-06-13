import requests
import pandas as pd
import time
import os
from PIL import Image, ImageDraw, ImageFont


ESI_BASE = "https://esi.evetech.net/latest"
TYCOON_BASE = "https://evetycoon.com/api/v1/market"
HEADERS = {"Content-Type": "application/json"}
TEMP_DIR = "temp"

if not os.path.exists(TEMP_DIR):
    os.makedirs(TEMP_DIR)

def parse_input_text(input_text):
    data = []
    for line in input_text.strip().split('\n'):
        parts = line.rsplit(None, 1)
        if len(parts) == 2:
            data.append({"name": parts[0].strip(), "quantity": int(parts[1])})
    return data


def get_type_ids(names):
    url = f"{ESI_BASE}/universe/ids/"
    res = requests.post(url, json=names, headers=HEADERS)
    res.raise_for_status()
    return {item["name"]: item["id"] for item in res.json().get("inventory_types", [])}


def get_market_stats(region_id, type_id, days=30):
    url = f"{TYCOON_BASE}/history/{region_id}/{type_id}"
    try:
        res = requests.get(url)
        history = res.json()[-days:]
        prices = [d['average'] for d in history]
        return {
            "current": prices[-1],
            "max": max(d['highest'] for d in history),
            "min": min(d['lowest'] for d in history),
            "avg": sum(prices) / len(prices)
        }
    except:
        return None



def generate_indicator(item, index):
    W, H = 300, 60
    img = Image.new('RGB', (W, H), "#1A1A1A")
    draw = ImageDraw.Draw(img)

    x_start, x_end = 20, 280
    y_top, y_bot = 20, 40

    draw.rounded_rectangle(
        [x_start, y_top, x_end, y_bot],
        radius=10,
        outline="#444444",
        width=1
    )

    p_min = item['price_min']
    p_max = item['price_max']
    p_avg = item['price_avg']
    p_cur = item['price_current']

    center_x = (x_start + x_end) / 2
    half_width = (x_end - x_start) / 2

    if p_avg <= 0:
        return None

    down_pct = (p_avg - p_min) / p_avg
    up_pct = (p_max - p_avg) / p_avg
    scale_pct = max(down_pct, up_pct, 1e-6)

    def price_to_x(price):
        pct = (price - p_avg) / p_avg
        pct = max(-scale_pct, min(scale_pct, pct))
        return center_x + (pct / scale_pct) * half_width

    x_avg = center_x
    x_cur = price_to_x(p_cur)

    if x_cur >= x_avg:
        draw.rounded_rectangle(
            [x_avg, y_top, x_cur, y_bot],
            radius=3,
            fill="#228B22"
        )
    else:
        draw.rounded_rectangle(
            [x_cur, y_top, x_avg, y_bot],
            radius=3,
            fill="#B22222"
        )

    draw.line(
        [(x_avg, y_top - 3), (x_avg, y_bot + 3)],
        fill="#FFFFFF",
        width=1
    )

    draw.polygon(
        [
            (x_cur, y_top - 2),
            (x_cur - 4, y_top - 8),
            (x_cur + 4, y_top - 8)
        ],
        fill="#00FFFF"
    )

    path = os.path.join(TEMP_DIR, f"ind_{index}.png")
    img.save(path)
    return path



def create_final_report(data_list):
    row_height = 80
    header_height = 80
    width = 1250
    total_height = header_height + (len(data_list) * row_height) + 20

    report = Image.new('RGB', (width, total_height), "#111111")
    draw = ImageDraw.Draw(report)

    try:
        font = ImageFont.truetype("arial.ttf", 18)
        font_bold = ImageFont.truetype("arial.ttf", 22)
    except:
        font = font_bold = ImageFont.load_default()

    col_x = [40, 280, 380, 480, 580, 700, 850, 950]
    headers = ["Name", "Qty", "Min", "Avg", "Max", "Current", "Diff %", "Market Visual"]

    draw.rectangle([0, 0, width, header_height], fill="#1F1F1F")
    for i, h in enumerate(headers):
        draw.text((col_x[i], header_height // 2 - 10), h, font=font_bold, fill="#FFFFFF")

    draw.line([(0, header_height), (width, header_height)], fill="#444444", width=3)

    for i, item in enumerate(data_list):
        y = header_height + (i * row_height)

        if i % 2 == 0:
            draw.rectangle([0, y, width, y + row_height], fill="#181818")

        diff = ((item['price_current'] - item['price_avg']) / item['price_avg']) * 100
        diff_text = f"{diff:+.1f}%"
        diff_color = "#00FF00" if diff >= 0 else "#FF4444"

        draw.text((col_x[0], y + 25), str(item['name']), font=font, fill="#FFFFFF")
        draw.text((col_x[1], y + 25), f"{item['quantity']:,}", font=font, fill="#CCCCCC")
        draw.text((col_x[2], y + 25), f"{item['price_min']:,.0f}", font=font, fill="#888888")
        draw.text((col_x[3], y + 25), f"{item['price_avg']:,.0f}", font=font, fill="#AAAAAA")
        draw.text((col_x[4], y + 25), f"{item['price_max']:,.0f}", font=font, fill="#888888")
        draw.text((col_x[5], y + 25), f"{item['price_current']:,.2f}", font=font, fill="#00FFFF")
        draw.text((col_x[6], y + 25), diff_text, font=font, fill=diff_color)

        draw.line([(0, y + row_height), (width, y + row_height)], fill="#222222", width=1)

        ind_path = generate_indicator(item, i)
        ind_img = Image.open(ind_path)
        report.paste(ind_img, (col_x[7], y + 10))

    final_path = "market_final_report.png"
    report.save(final_path)
    return final_path



def run_report(input_text):
    raw_items = parse_input_text(input_text)
    name_to_id = get_type_ids([it['name'] for it in raw_items])

    processed_data = []
    print("Fetching data and generating items...")

    for i, it in enumerate(raw_items):
        tid = name_to_id.get(it['name'])
        if not tid: continue

        stats = get_market_stats(10000002, tid)
        if stats:
            item_data = {
                "name": it['name'],
                "quantity": it['quantity'],
                "price_current": stats['current'],
                "price_max": stats['max'],
                "price_min": stats['min'],
                "price_avg": stats['avg']
            }
            processed_data.append(item_data)
        time.sleep(0.1)

    if processed_data:
        final_file = create_final_report(processed_data)
        print(f"Final report saved as: {final_file}")
    else:
        print("No data collected.")


test_input = """
Mexallon    409
Pyerite 6139
Tritanium   1080
Cadmium 10876
Chromium    2656
Hafnium 39812
Hydrocarbons    752
Silicates   33391
Thulium 23733
Titanium    29743
"""

if __name__ == "__main__":
    run_report(test_input)