import streamlit as st
import pandas as pd
from uszipcode import SearchEngine

# ================= 1. 核心配置 (V4.0) =================
CONFIG = {
    'FILE_NAME': '马士基LTL成本测算模型 V1.7.xlsx',  # 你的Excel文件名
    'DIM_FACTOR': 200,
    'MIN_BILLABLE_WEIGHT': 173,
    'FUEL_RATE': 0.315,
    'REMOTE_RATE': 28,
    'OVERSIZE_FEE': 50,
    'WAREHOUSE_MAP': {
        '08820': 'NJ', 
        '77494': 'HOU',
        '31326': 'GA', 
        '90046': 'CA'
    }
}

search = SearchEngine()

# ================= 2. 数据加载 (Excel 版) =================
@st.cache_data
def load_data():
    try:
        # 1. 读取分区表 (指定 Sheet 名为 '分区')
        df_zone = pd.read_excel(CONFIG['FILE_NAME'], sheet_name='分区')
        
        # 2. 读取费率表 (指定 Sheet 名为 '基础运费',同样不需要表头因为我们要自己找)
        df_rates_raw = pd.read_excel(CONFIG['FILE_NAME'], sheet_name='基础运费', header=None)
        
        # 3. 读取偏远邮编 (指定 Sheet 名为 '偏远邮编')
        df_remote = pd.read_excel(CONFIG['FILE_NAME'], sheet_name='偏远邮编')
        
        # --- 数据清洗逻辑 (保持不变) ---
        
        # 清洗费率表
        header_idx = 0
        for r in range(20): # 稍微多找几行，防止Excel格式变动
            # Excel读取后可能是NaN，转为str判断
            row_values = df_rates_raw.iloc[r].astype(str).values
            if '分区' in row_values:
                header_idx = r
                break
        
        # 截取有效数据区域
        rates = df_rates_raw.iloc[header_idx+1:, 10:17]
        rates.columns = ['Zone', 'Min_West', 'Rate_West_Low', 'Rate_West_High', 'Min_NonWest', 'Rate_NonWest_Low', 'Rate_NonWest_High']
        rates = rates.dropna(subset=['Zone'])
        rates = rates[rates['Zone'].isin(['A','B','C','D','E','F'])]
        
        # 清洗偏远邮编
        # Excel读取的邮编可能是数字类型，强制转字符串
        remote_zips = set(df_remote.iloc[:, 0].astype(str).str.replace('.0', '', regex=False).str.strip().tolist())
        
        return df_zone, rates, remote_zips
    except Exception as e:
        return None, None, None

# ================= 3. 核心计算函数 (V4.0 逻辑) =================
def get_state_from_zip(zipcode):
    try:
        res = search.by_zipcode(zipcode)
        if res: return res.state
        return None
    except: return None

def calculate_cost(df_zone, df_rates, remote_zips, o_zip, d_zip, L, W, H, weight):
    # A. 基础信息匹配
    warehouse = CONFIG['WAREHOUSE_MAP'].get(str(o_zip))
    if not warehouse: return None, f"❌ 未知发货邮编 {o_zip}，请联系管理员添加。"

    d_state = get_state_from_zip(str(d_zip))
    if not d_state: return None, f"❌ 无法识别收货邮编 {d_zip}，请检查是否正确。"
    
    col_name = f"{warehouse}发货分区"
    if col_name not in df_zone.columns: return None, f"❌ 系统缺少 {warehouse} 仓库的分区数据。"
    
    zone_row = df_zone[df_zone['state'] == d_state]
    if zone_row.empty: return None, f"❌ 不支持发往 {d_state} 州。"
    
    zone = zone_row[col_name].values[0]

    # B. 计费重计算 (逻辑: Max(实重, 体积重, 173))
    dim_weight = (L * W * H) / CONFIG['DIM_FACTOR']
    billable = max(weight, dim_weight, CONFIG['MIN_BILLABLE_WEIGHT'])

    # C. 基础运费
    is_west = (warehouse == 'CA')
    rate_row = df_rates[df_rates['Zone'] == zone].iloc[0]
    
    if is_west:
        rate = float(rate_row['Rate_West_High'] if billable >= 500 else rate_row['Rate_West_Low'])
        min_c = float(rate_row['Min_West'])
    else:
        rate = float(rate_row['Rate_NonWest_High'] if billable >= 500 else rate_row['Rate_NonWest_Low'])
        min_c = float(rate_row['Min_NonWest'])
        
    base = max(billable * rate, min_c)
    
    # D. 附加费
    fuel = base * CONFIG['FUEL_RATE']
    
    # 处理Excel邮编格式问题 (去掉可能存在的.0)
    d_zip_clean = str(d_zip).replace('.0', '').strip()
    is_remote = d_zip_clean in remote_zips
    
    remote = (billable / 100) * CONFIG['REMOTE_RATE'] if is_remote else 0
    
    # E. 超尺费 (V4.0 严格实重逻辑)
    is_oversize = False
    # 规则1: 实重 > 250
    if weight > 250:
        is_oversize = True
    # 规则2: 实重 > 150 且 任意边 > 72
    elif (weight > 150) and (max(L,W,H) > 72):
        is_oversize = True
        
    oversize = CONFIG['OVERSIZE_FEE'] if is_oversize else 0
    
    total = base + fuel + remote + oversize
    
    return {
        'Warehouse': warehouse, 'Dest_State': d_state, 'Zone': zone,
        'Billable': billable, 'Base': base, 'Fuel': fuel,
        'Remote': remote, 'Oversize': oversize, 'Total': total,
        'Is_Remote': is_remote, 'Is_Oversize': is_oversize
    }, None

# ================= 4. 网页界面 =================
st.set_page_config(page_title="LTL 运费计算器 V4.0", page_icon="🚚")

st.markdown("## 🚚 马士基 LTL 运费计算器 (Excel直读版)")
st.caption("逻辑版本: V4.0 | 数据源: Excel 原件")

df_zone, df_rates, remote_zips = load_data()

if df_zone is None:
    st.error(f"⚠️ 读取失败！请确保文件 `{CONFIG['FILE_NAME']}` 已上传，且包含 [分区, 基础运费, 偏远邮编] 这三个工作表。")
else:
    with st.container():
        col1, col2 = st.columns(2)
        with col1:
            st.info("📍 地址信息")
            o_zip = st.text_input("发货邮编", placeholder="例: 08820")
            d_zip = st.text_input("收货邮编", placeholder="例: 49022")
        with col2:
            st.info("📦 货物规格")
            c1, c2, c3 = st.columns(3)
            with c1: L = st.number_input("长 (in)", min_value=0.0)
            with c2: W = st.number_input("宽 (in)", min_value=0.0)
            with c3: H = st.number_input("高 (in)", min_value=0.0)
            weight = st.number_input("实重 (lbs)", min_value=0.0)

    if st.button("🚀 计算费用", type="primary", use_container_width=True):
        if not (o_zip and d_zip and L and W and H and weight):
            st.warning("请填写完整信息！")
        else:
            res, err = calculate_cost(df_zone, df_rates, remote_zips, o_zip, d_zip, L, W, H, weight)
            if err:
                st.error(err)
            else:
                st.markdown("---")
                # 结果卡片
                st.success(f"### 💰 预估总运费: ${res['Total']:.2f}")
                st.markdown(f"**路线**: {res['Warehouse']}仓 ➡️ {res['Dest_State']}州 (分区 {res['Zone']}) | **计费重**: {res['Billable']:.2f} lbs")
                
                # 明细表
                detail_data = {
                    "费用项": ["基础运费", "燃油费 (31.5%)", "偏远费", "超尺费"],
                    "金额": [f"${res['Base']:.2f}", f"${res['Fuel']:.2f}", f"${res['Remote']:.2f}", f"${res['Oversize']:.2f}"],
                    "状态": ["✅", "✅", "❗ 是" if res['Is_Remote'] else "-", "❗ 是" if res['Is_Oversize'] else "-"]
                }
                st.table(pd.DataFrame(detail_data))