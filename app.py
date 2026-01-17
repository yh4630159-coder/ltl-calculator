import streamlit as st
import pandas as pd
import os
import io

# ================= 1. 核心配置 (V4.7 - 极速内核版) =================
# 定义仓库主数据
WAREHOUSE_DB = [
    {"name": "AI美西001 (Ontario)", "zip": "91761", "zone_code": "CA"},
    {"name": "AI美西002 (Ontario)", "zip": "91761", "zone_code": "CA"},
    {"name": "AI美东NJ003 (Edison)", "zip": "08820", "zone_code": "NJ"},
    {"name": "AI美南GA002 (Ellenwood)", "zip": "30294", "zone_code": "SAV"},
    {"name": "AI美南SAV仓002 (Pooler)", "zip": "31322", "zone_code": "SAV"},
    {"name": "AI美南GA001仓 (Braselton)", "zip": "30517", "zone_code": "SAV"},
    {"name": "AI美南TX仓001 (Houston)", "zip": "77064", "zone_code": "HOU"},
    
    {"name": "乐歌美南SAV (Rincon)", "zip": "31326", "zone_code": "SAV"},
    {"name": "乐歌美西CAP仓 (Perris)", "zip": "92571", "zone_code": "CA"},
    {"name": "乐歌美东NJF (Burlington)", "zip": "08016", "zone_code": "NJ"},
    {"name": "乐歌美中南HOU07 (Katy)", "zip": "77494", "zone_code": "HOU"}
]

WAREHOUSE_OPTIONS = {f"{w['name']} - {w['zip']}": w['zip'] for w in WAREHOUSE_DB}
ZIP_TO_ZONE_MAP = {w['zip']: w['zone_code'] for w in WAREHOUSE_DB}

CONFIG = {
    'FILE_NAME': 'data.xlsx',
    'DIM_FACTOR': 200,
    'MIN_BILLABLE_WEIGHT': 173,
    'FUEL_RATE': 0.315,
    'REMOTE_RATE': 28,
    'OVERSIZE_FEE': 50,
}

# ================= 2. 数据加载 (极速优化) =================
@st.cache_data
def load_data_optimized():
    if not os.path.exists(CONFIG['FILE_NAME']):
        return None, None, None, f"找不到文件 '{CONFIG['FILE_NAME']}'"

    try:
        # 读取 Excel
        df_zone = pd.read_excel(CONFIG['FILE_NAME'], sheet_name='分区', engine='openpyxl')
        df_rates_raw = pd.read_excel(CONFIG['FILE_NAME'], sheet_name='基础运费', header=None, engine='openpyxl')
        df_remote = pd.read_excel(CONFIG['FILE_NAME'], sheet_name='偏远邮编', engine='openpyxl')
        
        # --- 🚀 提速优化 1: 构建分区字典 (Lookup Dictionary) ---
        # 将 DataFrame 转换为字典: key=(州代码, 仓库分区列名), value=分区代码
        # 这样以后查询就不需要 filter dataframe 了，速度提升 100倍
        zone_dict = {}
        # 预先处理好需要的列
        needed_cols = ['state', 'CA发货分区', 'NJ发货分区', 'SAV发货分区', 'HOU发货分区']
        # 检查列是否存在
        valid_cols = [c for c in needed_cols if c in df_zone.columns]
        
        # 遍历每一行构建索引
        for _, row in df_zone[valid_cols].iterrows():
            state = str(row['state']).strip().upper()
            if 'CA发货分区' in valid_cols: zone_dict[(state, 'CA')] = row['CA发货分区']
            if 'NJ发货分区' in valid_cols: zone_dict[(state, 'NJ')] = row['NJ发货分区']
            if 'SAV发货分区' in valid_cols: zone_dict[(state, 'SAV')] = row['SAV发货分区']
            if 'HOU发货分区' in valid_cols: zone_dict[(state, 'HOU')] = row['HOU发货分区']

        # --- 🚀 提速优化 2: 构建费率字典 ---
        # 清洗费率表
        header_idx = 0
        for r in range(20): 
            row_values = df_rates_raw.iloc[r].fillna('').astype(str).values
            if '分区' in row_values:
                header_idx = r
                break
        rates_df = df_rates_raw.iloc[header_idx+1:, 10:17]
        rates_df.columns = ['Zone', 'Min_West', 'Rate_West_Low', 'Rate_West_High', 'Min_NonWest', 'Rate_NonWest_Low', 'Rate_NonWest_High']
        rates_df = rates_df.dropna(subset=['Zone'])
        rates_df = rates_df[rates_df['Zone'].isin(['A','B','C','D','E','F'])]
        
        # 转为字典: key=Zone, value={各项费率}
        rate_dict = rates_df.set_index('Zone').to_dict('index')

        # --- 🚀 提速优化 3: 偏远邮编 Set ---
        remote_zips = set(df_remote.iloc[:, 0].astype(str).str.replace('.0', '', regex=False).str.strip().tolist())
        
        return zone_dict, rate_dict, remote_zips, None
    except Exception as e:
        return None, None, None, f"数据读取错误: {str(e)}"

# ================= 3. 核心计算逻辑 (纯内存运算) =================
def calculate_shipment_fast(zone_dict, rate_dict, remote_zips, shipment_data):
    if shipment_data.empty: return None, "无数据"
    
    # 1. 基础信息
    first_item = shipment_data.iloc[0]
    o_zip = str(first_item['发货邮编']).replace('.0', '').strip()
    d_zip = str(first_item['收货邮编']).replace('.0', '').strip()
    d_state = str(first_item['收货州']).upper().strip()
    
    # 2. 匹配分区 (O(1) 字典查找)
    warehouse_zone_code = ZIP_TO_ZONE_MAP.get(o_zip)
    if not warehouse_zone_code:
        return None, f"发货邮编 {o_zip} 无效"

    # 直接查字典，不再操作 DataFrame
    zone = zone_dict.get((d_state, warehouse_zone_code))
    if not zone:
        return None, f"不支持发往 {d_state}"

    # 3. 聚合计算
    # 使用 numpy 向量化计算会更快，但为了代码可读性，这里用原生循环也足够快
    total_actual_weight = 0
    total_dim_weight = 0
    is_oversize = False
    
    for _, row in shipment_data.iterrows():
        l, w, h, weight = float(row['长']), float(row['宽']), float(row['高']), float(row['实重'])
        total_actual_weight += weight
        total_dim_weight += (l * w * h) / CONFIG['DIM_FACTOR']
        if weight > 250 or (weight > 150 and max(l,w,h) > 72):
            is_oversize = True

    # 4. 费用计算
    billable = max(total_actual_weight, total_dim_weight, CONFIG['MIN_BILLABLE_WEIGHT'])

    # 费率匹配 (O(1) 字典查找)
    is_west = (warehouse_zone_code == 'CA')
    r_data = rate_dict.get(zone)
    if not r_data: return None, f"缺 {zone} 区费率"

    if is_west:
        rate = float(r_data['Rate_West_High'] if billable >= 500 else r_data['Rate_West_Low'])
        min_c = float(r_data['Min_West'])
    else:
        rate = float(r_data['Rate_NonWest_High'] if billable >= 500 else r_data['Rate_NonWest_Low'])
        min_c = float(r_data['Min_NonWest'])
        
    base = max(billable * rate, min_c)
    fuel = base * CONFIG['FUEL_RATE']
    
    # 偏远费 (Set 查找也是 O(1))
    is_remote = d_zip in remote_zips
    remote = (billable / 100) * CONFIG['REMOTE_RATE'] if is_remote else 0
    oversize = CONFIG['OVERSIZE_FEE'] if is_oversize else 0
    total = base + fuel + remote + oversize
    
    return {
        '发货仓': f"{warehouse_zone_code}区", 
        '分区': zone, 
        '包裹数': len(shipment_data),
        '计费重': round(billable, 2),
        '基础运费': round(base, 2), '燃油费': round(fuel, 2),
        '偏远费': round(remote, 2), '超尺费': round(oversize, 2),
        '总费用': round(total, 2)
    }, None

# ================= 4. 界面逻辑 =================
st.set_page_config(page_title="LTL 运费计算器 V4.7", page_icon="⚡", layout="wide")
st.title("⚡ 马士基 LTL 运费计算器 (极速版)")

# 加载优化后的数据结构
zone_dict, rate_dict, remote_zips, err_msg = load_data_optimized()

if err_msg:
    st.error(f"❌ 系统错误: {err_msg}")
else:
    tab1, tab2 = st.tabs(["🧮 交互式计算", "📥 批量上传"])

    # --- TAB 1: 交互式 ---
    with tab1:
        st.info("👇 智能选仓 + 极速计算")
        
        c1, c2, c3 = st.columns(3)
        with c1:
            selected_wh_label = st.selectbox("选择发货仓库", list(WAREHOUSE_OPTIONS.keys()))
            o_zip_val = WAREHOUSE_OPTIONS[selected_wh_label]
        with c2: d_zip = st.text_input("收货邮编", "49022")
        with c3: d_state = st.text_input("收货州代码", "MI")

        st.markdown("###### 📦 包裹明细")
        default_data = pd.DataFrame([{"长": 48.0, "宽": 40.0, "高": 50.0, "实重": 500.0}])
        edited_df = st.data_editor(
            default_data, num_rows="dynamic",
            column_config={
                "长": st.column_config.NumberColumn("长 (in)", required=True),
                "宽": st.column_config.NumberColumn("宽 (in)", required=True),
                "高": st.column_config.NumberColumn("高 (in)", required=True),
                "实重": st.column_config.NumberColumn("实重 (lbs)", required=True),
            }, use_container_width=True
        )

        if st.button("🚀 立即计算", type="primary", use_container_width=True):
            if not (d_zip and d_state and not edited_df.empty):
                st.warning("⚠️ 请完善信息")
            else:
                calc_data = edited_df.copy()
                calc_data['发货邮编'] = o_zip_val
                calc_data['收货邮编'] = d_zip
                calc_data['收货州'] = d_state
                
                # 调用极速算法
                res, err = calculate_shipment_fast(zone_dict, rate_dict, remote_zips, calc_data)
                
                if err: st.error(err)
                else:
                    st.divider()
                    c_a, c_b, c_c = st.columns(3)
                    with c_a: st.metric("💰 预估总运费", f"${res['总费用']}")
                    with c_b: st.metric("⚖️ 最终计费重", f"{res['计费重']} lbs")
                    with c_c: st.metric("📍 分区", f"{res['分区']}区")
                    
                    st.table(pd.DataFrame({
                        "费用项": ["基础运费", "燃油费", "偏远费", "超尺费"],
                        "金额": [res['基础运费'], res['燃油费'], res['偏远费'], res['超尺费']]
                    }).T)

    # --- TAB 2: 批量上传 ---
    with tab2:
        st.markdown("### 📥 批量极速计算")
        
        with st.expander("查看仓库对照表"):
            st.dataframe(pd.DataFrame(WAREHOUSE_DB)[['name','zip']], hide_index=True)

        template_df = pd.DataFrame(columns=["订单号", "发货邮编", "收货邮编", "收货州", "长", "宽", "高", "实重"])
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
            template_df.to_excel(writer, index=False)
        st.download_button("📄 下载模板", buffer.getvalue(), "LTL_Template.xlsx")
        
        st.divider()
        uploaded_file = st.file_uploader("上传 Excel", type=['xlsx'])
        
        if uploaded_file:
            try:
                df_input = pd.read_excel(uploaded_file, engine='openpyxl')
                required = ["订单号", "发货邮编", "收货邮编", "收货州", "长", "宽", "高", "实重"]
                
                if not all(c in df_input.columns for c in required):
                    st.error("❌ 格式错误")
                else:
                    grouped = df_input.groupby('订单号')
                    results = []
                    
                    # 进度条
                    bar = st.progress(0)
                    total_groups = len(grouped)
                    
                    for i, (order_id, group_df) in enumerate(grouped):
                        # 调用极速算法
                        res, err = calculate_shipment_fast(zone_dict, rate_dict, remote_zips, group_df)
                        row_res = {'订单号': order_id}
                        if err:
                            row_res['状态'] = '失败'
                            row_res['错误信息'] = err
                        else:
                            row_res['状态'] = '成功'
                            row_res.update(res)
                        results.append(row_res)
                        bar.progress((i + 1) / total_groups)
                    
                    res_df = pd.DataFrame(results)
                    st.success(f"🎉 {len(res_df)} 个订单计算完成！")
                    
                    output = io.BytesIO()
                    with pd.ExcelWriter(output, engine='openpyxl') as writer:
                        res_df.to_excel(writer, index=False)
                    st.download_button("📥 下载结果", output.getvalue(), "LTL_Fast_Result.xlsx", type="primary")
            except Exception as e:
                st.error(f"❌: {e}")