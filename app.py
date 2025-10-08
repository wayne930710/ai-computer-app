from flask import Flask, request, jsonify, render_template
import pymysql
import re
import os
from openai import OpenAI

app = Flask(__name__)
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
#mysql的連線
def get_db():
    return pymysql.connect(
        host=os.getenv("DB_HOST", "localhost"),  # 預設 localhost
        user=os.getenv("DB_USER", "root"),
        password=os.getenv("DB_PASSWORD", "Aa101014073"),
        database=os.getenv("DB_NAME", "ai_computer"),
        charset='utf8mb4',
        cursorclass=pymysql.cursors.DictCursor
    )

# def extract_budget(user_input):
#     match = re.search(r'(\d+(?:,\d{3})*|\d+(?:\.\d+)?萬)', user_input)
#     if match:
#         text = match.group(1)
#         if '萬' in text:
#             return int(float(text.replace('萬', '')) * 10000)
#         else:
#             return int(text.replace(',', ''))
#     return None


@app.route('/')
def index():
    return render_template("index.html")


@app.route('/api/chat', methods=['POST'])
def chat():
    # 取得使用者輸入與 Wi-Fi 選項
    user_input = request.json.get("message", "").strip()
    wifi_need = request.json.get("wifi", "any")
    
    # 設定 Wi-Fi 查詢條件
    wifi_condition = ""
    if wifi_need == "need_wifi":
        wifi_condition = " AND wifi = 1"
    elif wifi_need == "no_wifi":
        wifi_condition = " AND (wifi = 0 OR wifi IS NULL)"

    # 從輸入中擷取預算金額（4~6位數）
    match = re.search(r'(\d{4,6})', user_input)
    if not match:
        return jsonify({'reply': '請輸入正確的預算金額（例如：35000）'})

    budget = int(match.group(1))

    # 發送 prompt 給 OpenAI 要求預算比例
    prompt = f"""使用者說：「{user_input}」\n請根據以下用途（可複選）：遊戲、剪輯、繪圖、AI 模型\n列出建議配件預算分配比例，請根據使用者用途與預算分配比例，但 RAM 不要超過48GB。（總和為 100%）：\nGPU：%\nCPU：%\nRAM：%\n主機板：%\nSSD：%\n電源：%\n機殼：%\n散熱：%"""

    try:
        # 呼叫 GPT-4o 模型
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "你是一位電腦配備建議專家，請根據使用者用途與預算，回傳各硬體建議預算比例。"},
                {"role": "user", "content": prompt}
            ]
        )
        ai_reply = response.choices[0].message.content
        print("AI 回覆：", ai_reply)

        # 從 AI 回應中解析各配件百分比
        def extract_percent(part):
            match = re.search(rf"{part}[:：]\s*(\d+)%", ai_reply)
            return int(match.group(1)) if match else 0

        gpu_p = extract_percent("GPU")
        cpu_p = extract_percent("CPU")
        ram_p = extract_percent("RAM")
        mbs_p = extract_percent("主機板")
        ssd_p = extract_percent("SSD")
        power_p = extract_percent("電源")
        box_p = extract_percent("機殼")
        radiating_p = extract_percent("散熱")

    except Exception as e:
        print("OpenAI 錯誤：", e)
        return jsonify({'reply': 'AI 分析用途時發生錯誤，請稍後再試'})

    # 根據百分比分配各配件預算
    gpu_budget = int(budget * gpu_p / 100)
    cpu_budget = int(budget * cpu_p / 100)
    ram_budget = int(budget * ram_p / 100)
    mbs_budget = int(budget * mbs_p / 100)
    ssd_budget = int(budget * ssd_p / 100)
    power_budget = int(budget * power_p / 100)
    box_budget = int(budget * box_p / 100)
    radiating_budget = int(budget * radiating_p / 100)

    # 設定最低預算門檻
    min_budget = {
        "radiating": 1200,  # 散熱至少 1200
        "power": 2000,      # 電源至少 2000
        "box": 1500,         # 機殼至少 1500
    }

    # 檢查並調整
    if radiating_budget < min_budget["radiating"]:
        radiating_budget = min_budget["radiating"]
    if power_budget < min_budget["power"]:
        power_budget = min_budget["power"]
    if box_budget < min_budget["box"]:
        box_budget = min_budget["box"]

    # 重新計算剩下的預算並分配給大件（GPU / CPU / RAM / SSD / 主機板）
    used_budget = radiating_budget + power_budget + box_budget
    flexible_budget = budget - used_budget

    # 比例重新調整（只在 GPU / CPU / RAM / SSD / 主機板 之間分配）
    total_percent = gpu_p + cpu_p + ram_p + mbs_p + ssd_p
    if total_percent > 0:
        gpu_budget = int(flexible_budget * gpu_p / total_percent)
        cpu_budget = int(flexible_budget * cpu_p / total_percent)
        ram_budget = int(flexible_budget * ram_p / total_percent)
        mbs_budget = int(flexible_budget * mbs_p / total_percent)
        ssd_budget = int(flexible_budget * ssd_p / total_percent)

    conn = get_db()
    with conn.cursor() as cursor:
        # 從資料庫中選出 GPU 和主機板各前 2 筆（價高優先）
        cursor.execute("""SELECT * FROM gpus WHERE price <= %s ORDER BY price DESC LIMIT 3""",(gpu_budget))
        gpus = cursor.fetchall()

        query = f"SELECT * FROM mbs WHERE price <= %s {wifi_condition} ORDER BY price DESC LIMIT 3"
        cursor.execute(query, (mbs_budget,))
        mbs_list = cursor.fetchall()

        # 使用者是否偏好特定品牌
        brand_preference = None
        if "AMD" in user_input.upper():
            brand_preference = "AMD"
        elif "INTEL" in user_input.upper():
            brand_preference = "Intel"

        combos = []  # 所有可行的組合

        # 建立多組組合（最多依據配件數組合出三組）
        for i in range(min(len(gpus), len(mbs_list))):
            gpu = gpus[i]
            mbs = mbs_list[i]
            mbs_pin = mbs['pin']
            mbs_ddr = mbs['DDR']
            mbs_powered = mbs['POWERED'] if mbs['POWERED'] else 0

            # 查詢 CPU（配對腳位，考慮品牌偏好）
            if brand_preference:
                cursor.execute("""
                    SELECT * FROM cpus 
                    WHERE price <= %s AND pin = %s AND cpus_name LIKE %s 
                    ORDER BY price DESC LIMIT 1
                """, (cpu_budget, mbs_pin, f"%{brand_preference}%"))
            else:
                cursor.execute("""
                    SELECT * FROM cpus 
                    WHERE price <= %s AND pin = %s 
                    ORDER BY price DESC LIMIT 1
                """, (cpu_budget, mbs_pin))
            cpus = cursor.fetchall()

            for cpu in cpus:
                cpu_tdp = int(cpu['TDP']) if cpu and str(cpu['TDP']).isdigit() else 0
                # 如果主機板供電不足以支援高 TDP CPU，跳過這組
                if cpu_tdp > 125 and mbs_powered <= 8:
                    continue

                # 查詢 RAM（考慮 DDR 代數與 AMD 頻率限制）
                if 'amd' in cpu['cpus_name'].lower():
                # AMD 限制 6000，同時加上 CPU IMC 頻率限制
                    cursor.execute("""
                    SELECT * FROM ram 
                    WHERE price <= %s AND DDR = %s 
                    AND frequency = LEAST(6000, %s)
                    ORDER BY price DESC LIMIT 1
                """, (ram_budget, mbs_ddr, cpu['frequency']))
                else:
                # Intel，直接限制 RAM 頻率 <= CPU 頻率
                    cursor.execute("""
                    SELECT * FROM ram 
                    WHERE price <= %s AND DDR = %s 
                    AND frequency = %s
                    ORDER BY price DESC LIMIT 1
                """, (ram_budget, mbs_ddr, cpu['frequency']))
                rams = cursor.fetchall()

                # 其他配件（SSD、散熱器、電源、機殼）各選價格最高的 1 筆
                cursor.execute("SELECT * FROM ssd WHERE price <= %s ORDER BY price DESC LIMIT 1", (ssd_budget,))
                ssd = cursor.fetchone()
                cursor.execute("SELECT * FROM radiating WHERE price <= %s ORDER BY price DESC LIMIT 1", (radiating_budget,))
                radiating = cursor.fetchone()
                cursor.execute("SELECT * FROM power WHERE price <= %s ORDER BY price DESC LIMIT 1", (power_budget,))
                power = cursor.fetchone()
                cursor.execute("SELECT * FROM box WHERE price <= %s ORDER BY price DESC LIMIT 1", (box_budget,))
                box = cursor.fetchone()

                # 將所有元件組合起來，計算總價後加入 combos
                for ram in rams:
                    if all([gpu, cpu, ram, mbs, ssd, radiating, power, box]):
                        total = sum([
                            gpu['price'], cpu['price'], ram['price'], mbs['price'],
                            ssd['price'], radiating['price'], power['price'], box['price']
                        ])
                        combos.append({
                            'cpu': cpu, 'gpu': gpu, 'ram': ram, 'mbs': mbs,
                            'ssd': ssd, 'radiating': radiating, 'power': power,
                            'box': box, 'total': total
                        })

    conn.close()  # 關閉資料庫連線

    filtered_combos = [
    combo for combo in combos
    if abs(combo['total'] - budget) <= 1000
    ]
    if filtered_combos:
        combos = filtered_combos

    # 如果成功組出方案，回傳最多 3 組建議
    if combos:
        reply = f"根據你的預算 {budget} 元（允許 ±1000），以下是推薦的組合：<br><br>"
        for idx, combo in enumerate(combos[:1], 1):
            reply += (
            f"【方案 {idx}】<br>"
            f"🔹CPU：{combo['cpu']['cpus_name']}（{combo['cpu']['price']} 元）<br>"
            f"🔹主機板：{combo['mbs']['MBS_name']}（{combo['mbs']['price']} 元）<br>"
            f"🔹RAM：{combo['ram']['Ram_name']}（{combo['ram']['price']} 元）<br>"
            f"🔹GPU：{combo['gpu']['gpu_name']}（{combo['gpu']['price']} 元）<br>"
            f"🔹SSD：{combo['ssd']['SSD_name']}（{combo['ssd']['price']} 元）<br>"
            f"🔹散熱：{combo['radiating']['fan_name']}（{combo['radiating']['price']} 元）<br>"
            f"🔹電源：{combo['power']['power_name']}（{combo['power']['price']} 元）<br>"
            f"🔹機殼：{combo['box']['box_name']}（{combo['box']['price']} 元）<br>"
            f"💰總價：{combo['total']} 元<br><br>"
        )
    else:
        reply = "目前找不到符合你預算的組合，請提高預算或稍後再試～"

    # 回傳 JSON 給前端，<br> 可供 HTML 渲染換行
    return jsonify({
    'reply': reply,
    'ai_reply': ai_reply  # 新增這行
})


if __name__ == '__main__':
    port = int(os.getenv("PORT", 5000))  # Render 會設定 PORT 變數為 10000
    app.run(host='0.0.0.0', port=port, debug=True)
