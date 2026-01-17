import streamlit as st
import pandas as pd
import os

# ================= 1. 核心配置 (V4.2 - 全仓库版) =================
CONFIG = {
    'FILE_NAME': 'data.xlsx',
    'DIM_FACTOR': 200,
    'MIN_BILLABLE_WEIGHT': 173,
    'FUEL_RATE': 0.315,
    'REMOTE_RATE': 28,
    'OVERSIZE_FEE': 50,
    
    # 仓库映射逻辑：邮编 -> 计费分区 (CA/NJ/SAV/HOU)
    # 注意：Excel里只有这4个分区列，所以必须把所有仓库映射到这4个代码上
    'WAREHOUSE_MAP': {
        # --- AI 仓系列 ---
        '91761': 'CA',   # AI美西001 / AI美西002 (Ontario, CA)
        '30294': 'SAV',  # AI美南GA002 (Ellenwood, GA) -> 归入 SAV 分区
        '08820': 'NJ',   # AI美东NJ003 (Edison, NJ)
        '31322': 'SAV',  # AI美南SAV仓002 (Pooler, GA)
        '77064': 'HOU',  # AI美南TX仓001 (Houston, TX)
        '30517': 'SAV',  # AI美南GA001仓 (Braselton, GA) -> 归入 SAV 分区

        # --- 乐歌 仓系列 ---
        '31326': 'SAV',  # 乐歌美南SAV (Rincon, GA)
        '92571': 'CA',   # 乐歌美西CAP仓 (Perris, CA)
        '08016': 'NJ',   # 乐歌美东NJF (Burlington, NJ)
        '77494': 'HOU'   # 乐歌美中南HOU07 (Katy, TX)
    }
}
# ================= 2. 数据加载 (带排错功能) =================
@st.cache_data
def load_data():
    # --- 🔍 排错自检：检查文件是否存在 ---
    if not os.path.exists(CONFIG['FILE_NAME']):
        # 如果找不到文件，打印当前目录下的所有文件，方便找原因
        current_files = os.listdir('.')
        return None, None, None, f"找不到文件 '{CONFIG['FILE_NAME']}'。当前目录下的文件有: {current_files}"

    try:
        # 指定 engine='openpyxl' 确保读取 .xlsx
        df_zone = pd.read_excel(CONFIG['FILE_NAME'], sheet_name='分区', engine='openpyxl')
        df_rates_raw = pd.read_excel(CONFIG['FILE_NAME'], sheet_name='基础运费', header=None, engine='openpyxl')
        df_remote = pd.read_excel(CONFIG['FILE_NAME'], sheet_name='偏远邮编', engine='openpyxl')
        
        # --- 数据清洗 ---
        header_idx = 0
        for r in range(20): 
            row_values = df_rates_raw.iloc[r].fillna('').astype(str).values
            if '分区' in row_values:
                header_idx = r
                break
        
        rates = df_rates_raw.iloc[header_idx+1:, 10:17]
        rates.columns = ['Zone', 'Min_West', 'Rate_West_Low', 'Rate_West_High', 'Min_NonWest', 'Rate_NonWest_Low', 'Rate_NonWest_High']
        rates = rates.dropna(subset=['Zone'])
        rates = rates[rates['Zone'].isin(['A','B','C','D','E','F'])]
        
        remote_zips = set(df_remote.iloc[:, 0].astype(str).str.replace('.0', '', regex=False).str.strip().tolist())
        
        return df_zone, rates, remote_zips, None
    except Exception as e:
        return None, None, None, f"数据读取错误: {str(e)}"

# ================= 3. 辅助函数 =================
# 简单版：如果不使用 uszipcode 库，我们可以根据偏远表做一个简单推断，或者让用户输入州
# 为了降低报错风险，这里移除 uszipcode 依赖，改回让用户输入 State（更稳妥）
# 或者我们通过偏远表反推（如果能接受非偏远地区无法自动识别State）
# 🌟 最稳妥方案：让用户手动输入州代码 (State)，或者只通过邮编的前3位粗略匹配
# 这里为了保证 100% 运行成功，我把 State 改为“自动匹配+手动修正”

def calculate_cost(df_zone, df_rates, remote_zips, o_zip, d_zip, d_state_input, L, W, H, weight):
    warehouse = CONFIG['WAREHOUSE_MAP'].get(str(o_zip))
    if not warehouse: return None, f"❌ 未知发货邮编 {o_zip}"

    # 优先使用用户输入的 State
    d_state = d_state_input.upper().strip()
    
    col_name = f"{warehouse}发货分区"
    if col_name not in df_zone.columns: return None, f"❌ 缺少 {warehouse} 仓库数据"
    
    zone_row = df_zone[df_zone['state'] == d_state]
    if zone_row.empty: return None, f"❌ 无法匹配到州: {d_state}"
    
    zone = zone_row[col_name].values[0]

    dim_weight = (L * W * H) / CONFIG['DIM_FACTOR']
    billable = max(weight, dim_weight, CONFIG['MIN_BILLABLE_WEIGHT'])

    is_west = (warehouse == 'CA')
    # 费率匹配
    try:
        rate_row = df_rates[df_rates['Zone'] == zone].iloc[0]
    except:
        return None, f"❌ 无法找到分区 {zone} 的费率"

    if is_west:
        rate = float(rate_row['Rate_West_High'] if billable >= 500 else rate_row['Rate_West_Low'])
        min_c = float(rate_row['Min_West'])
    else:
        rate = float(rate_row['Rate_NonWest_High'] if billable >= 500 else rate_row['Rate_NonWest_Low'])
        min_c = float(rate_row['Min_NonWest'])
        
    base = max(billable * rate, min_c)
    fuel = base * CONFIG['FUEL_RATE']
    
    d_zip_clean = str(d_zip).replace('.0', '').strip()
    is_remote = d_zip_clean in remote_zips
    remote = (billable / 100) * CONFIG['REMOTE_RATE'] if is_remote else 0
    
    is_oversize = False
    if weight > 250: is_oversize = True
    elif (weight > 150) and (max(L,W,H) > 72): is_oversize = True
    oversize = CONFIG['OVERSIZE_FEE'] if is_oversize else 0
    
    total = base + fuel + remote + oversize
    
    return {
        'Warehouse': warehouse, 'Dest_State': d_state, 'Zone': zone,
        'Billable': billable, 'Base': base, 'Fuel': fuel,
        'Remote': remote, 'Oversize': oversize, 'Total': total,
        'Is_Remote': is_remote, 'Is_Oversize': is_oversize
    }, None

# ================= 4. 界面 =================
st.set_page_config(page_title="LTL 运费计算器 V4.1", page_icon="🚚")
st.title("🚚 马士基 LTL 运费计算器")

# 加载数据
df_zone, df_rates, remote_zips, err_msg = load_data()

if err_msg:
    st.error(f"⚠️ 系统错误: {err_msg}")
    st.info("请检查：1. Excel文件是否已重命名为 data.xlsx 并上传？ 2. GitHub仓库里是否有这个文件？")
else:
    with st.form("calc_form"):
        col1, col2 = st.columns(2)
        with col1:
            o_zip = st.text_input("发货邮编", "08820")
            d_zip = st.text_input("收货邮编", "49022")
            # 恢复 State 输入框，防止 uszipcode 库报错导致全崩
            d_state = st.text_input("收货州代码 (如 MI, CA, TX)", "MI")
        with col2:
            c1, c2, c3 = st.columns(3)
            with c1: L = st.number_input("长 (in)", value=80.0)
            with c2: W = st.number_input("宽 (in)", value=32.2)
            with c3: H = st.number_input("高 (in)", value=24.6)
            weight = st.number_input("实重 (lbs)", value=141.0)
        
        submitted = st.form_submit_button("开始计算", type="primary")

    if submitted:
        res, err = calculate_cost(df_zone, df_rates, remote_zips, o_zip, d_zip, d_state, L, W, H, weight)
        if err:
            st.error(err)
        else:
            st.success(f"### 预估总运费: ${res['Total']:.2f}")
            st.write(f"分区: {res['Zone']} | 计费重: {res['Billable']:.2f} lbs")
            st.table(pd.DataFrame({
                "费用项": ["基础运费", "燃油费", "偏远费", "超尺费"],
                "金额": [res['Base'], res['Fuel'], res['Remote'], res['Oversize']]
            }))