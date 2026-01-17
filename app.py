import streamlit as st
import pandas as pd
import os
import io

# ================= 1. 核心配置 (V4.6 - 智能选仓版) =================
# 定义仓库主数据：名称、邮编、对应的计费分区逻辑(CA/NJ/SAV/HOU)
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

# 生成下拉菜单选项 (格式: "AI美东NJ003 - 08820")
WAREHOUSE_OPTIONS = {f"{w['name']} - {w['zip']}": w['zip'] for w in WAREHOUSE_DB}

# 生成邮编到分区的映射 (用于核心计算)
ZIP_TO_ZONE_MAP = {w['zip']: w['zone_code'] for w in WAREHOUSE_DB}

CONFIG = {
    'FILE_NAME': 'data.xlsx',
    'DIM_FACTOR': 200,
    'MIN_BILLABLE_WEIGHT': 173,
    'FUEL_RATE': 0.315,
    'REMOTE_RATE': 28,
    'OVERSIZE_FEE': 50,
}

# ================= 2. 数据加载 =================
@st.cache_data
def load_data():
    if not os.path.exists(CONFIG['FILE_NAME']):
        return None, None, None, f"找不到文件 '{CONFIG['FILE_NAME']}'"

    try:
        df_zone = pd.read_excel(CONFIG['FILE_NAME'], sheet_name='分区', engine='openpyxl')
        df_rates_raw = pd.read_excel(CONFIG['FILE_NAME'], sheet_name='基础运费', header=None, engine='openpyxl')
        df_remote = pd.read_excel(CONFIG['FILE_NAME'], sheet_name='偏远邮编', engine='openpyxl')
        
        # 清洗费率表
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

# ================= 3. 核心计算逻辑 =================
def calculate_shipment(df_zone, df_rates, remote_zips, shipment_data):
    """
    shipment_data: DataFrame, 必须包含 [发货邮编, 收货邮编, 收货州, 长, 宽, 高, 实重]
    """
    if shipment_data.empty: return None, "没有包裹数据"
    
    # 1. 提取基础信息
    first_item = shipment_data.iloc[0]
    # 确保邮编转为纯字符串
    o_zip = str(first_item['发货邮编']).replace('.0', '').strip()
    d_zip = str(first_item['收货邮编']).replace('.0', '').strip()
    d_state = str(first_item['收货州']).upper().strip()
    
    # 2. 匹配分区 (使用 ZIP_TO_ZONE_MAP)
    # 逻辑：通过邮编找到它是属于哪个大区 (CA/NJ/SAV/HOU)
    warehouse_zone_code = ZIP_TO_ZONE_MAP.get(o_zip)
    
    if not warehouse_zone_code:
        return None, f"发货邮编 {o_zip} 不在系统支持的仓库列表中"

    # 拼接 Excel 里的列名 (例如: "NJ发货分区")
    col_name = f"{warehouse_zone_code}发货分区"
    
    if col_name not in df_zone.columns: return None, f"Excel缺少列: {col_name}"
    
    zone_row = df_zone[df_zone['state'] == d_state]
    if zone_row.empty: return None, f"无法识别收货州: {d_state}"
    
    zone = zone_row[col_name].values[0]

    # 3. 聚合计算
    total_actual_weight = 0
    total_dim_weight = 0
    is_oversize = False
    
    for _, row in shipment_data.iterrows():
        l, w, h, weight = float(row['长']), float(row['宽']), float(row['高']), float(row['实重'])
        total_actual_weight += weight
        dim_w = (l * w * h) / CONFIG['DIM_FACTOR']
        total_dim_weight += dim_w
        
        # 超尺检查
        if weight > 250: is_oversize = True
        elif (weight > 150) and (max(l, w, h) > 72): is_oversize = True

    # 4. 费用计算
    billable = max(total_actual_weight, total_dim_weight, CONFIG['MIN_BILLABLE_WEIGHT'])

    # 费率匹配
    is_west = (warehouse_zone_code == 'CA')
    try:
        rate_row = df_rates[df_rates['Zone'] == zone].iloc[0]
    except:
        return None, f"无 {zone} 区费率"

    if is_west:
        rate = float(rate_row['Rate_West_High'] if billable >= 500 else rate_row['Rate_West_Low'])
        min_c = float(rate_row['Min_West'])
    else:
        rate = float(rate_row['Rate_NonWest_High'] if billable >= 500 else rate_row['Rate_NonWest_Low'])
        min_c = float(rate_row['Min_NonWest'])
        
    base = max(billable * rate, min_c)
    fuel = base * CONFIG['FUEL_RATE']
    
    is_remote = d_zip in remote_zips
    remote = (billable / 100) * CONFIG['REMOTE_RATE'] if is_remote else 0
    oversize = CONFIG['OVERSIZE_FEE'] if is_oversize else 0
    total = base + fuel + remote + oversize
    
    return {
        '发货仓': f"{warehouse_zone_code}区 ({o_zip})", 
        '分区': zone, '包裹数': len(shipment_data),
        '总实重': round(total_actual_weight, 2),
        '计费重': round(billable, 2),
        '基础运费': round(base, 2), '燃油费': round(fuel, 2),
        '偏远费': round(remote, 2), '超尺费': round(oversize, 2),
        '总费用': round(total, 2)
    }, None

# ================= 4. 界面逻辑 =================
st.set_page_config(page_title="LTL 运费计算器 V4.6", page_icon="🚚", layout="wide")
st.title("🚚 马士基 LTL 运费计算器")
st.caption("逻辑版本: V4.6 (智能选仓版)")

df_zone, df_rates, remote_zips, err_msg = load_data()

if err_msg:
    st.error(f"❌ 系统错误: {err_msg}")
else:
    tab1, tab2 = st.tabs(["🧮 交互式计算 (单票多件)", "📥 批量上传 (Excel)"])

    # --- TAB 1: 交互式计算 ---
    with tab1:
        st.info("👇 请选择发货仓库，并添加包裹明细。")
        
        # A. 地址信息区 (UI升级点)
        col_addr1, col_addr2, col_addr3 = st.columns(3)
        
        with col_addr1:
            # 🌟 核心修改：使用下拉菜单选择仓库
            selected_wh_label = st.selectbox(
                "选择发货仓库", 
                options=list(WAREHOUSE_OPTIONS.keys()),
                help="选择仓库后，系统会自动匹配对应邮编"
            )
            # 获取实际邮编值
            o_zip_val = WAREHOUSE_OPTIONS[selected_wh_label]
            
        with col_addr2: d_zip = st.text_input("收货邮编", "49022")
        with col_addr3: d_state = st.text_input("收货州代码", "MI")

        # B. 包裹录入区
        st.markdown("###### 📦 包裹明细")
        default_data = pd.DataFrame([{"长": 48.0, "宽": 40.0, "高": 50.0, "实重": 500.0}])
        edited_df = st.data_editor(
            default_data,
            num_rows="dynamic",
            column_config={
                "长": st.column_config.NumberColumn("长 (in)", min_value=0.1, required=True),
                "宽": st.column_config.NumberColumn("宽 (in)", min_value=0.1, required=True),
                "高": st.column_config.NumberColumn("高 (in)", min_value=0.1, required=True),
                "实重": st.column_config.NumberColumn("实重 (lbs)", min_value=0.1, required=True),
            },
            hide_index=True,
            use_container_width=True
        )

        # C. 触发计算
        if st.button("🚀 立即计算", type="primary", use_container_width=True):
            if not (d_zip and d_state):
                st.warning("⚠️ 请输入收货邮编和州代码！")
            elif edited_df.empty:
                st.warning("⚠️ 请至少添加一个包裹！")
            else:
                # 构造包含地址的完整数据
                calc_data = edited_df.copy()
                calc_data['发货邮编'] = o_zip_val # 使用从下拉菜单获取的邮编
                calc_data['收货邮编'] = d_zip
                calc_data['收货州'] = d_state
                
                res, err = calculate_shipment(df_zone, df_rates, remote_zips, calc_data)
                
                if err:
                    st.error(f"❌ 计算失败: {err}")
                else:
                    st.divider()
                    c1, c2, c3 = st.columns(3)
                    with c1: st.metric("💰 预估总运费", f"${res['总费用']}")
                    with c2: st.metric("⚖️ 最终计费重", f"{res['计费重']} lbs")
                    with c3: st.metric("📍 当前发货", selected_wh_label.split('-')[0]) # 只显示仓库名
                    
                    detail_df = pd.DataFrame({
                        "费用项": ["基础运费", "燃油费", "偏远费", "超尺费"],
                        "金额": [f"${res['基础运费']}", f"${res['燃油费']}", f"${res['偏远费']}", f"${res['超尺费']}"]
                    })
                    st.table(detail_df)

    # --- TAB 2: 批量上传 ---
    with tab2:
        st.markdown("### 📥 批量计算")
        st.markdown("**注意：批量表格中请依然填写【发货邮编】，系统会自动识别仓库。**")
        
        # 显示仓库邮编对照表，方便业务员查阅
        with st.expander("🔍 查看仓库邮编对照表"):
            wh_df = pd.DataFrame(WAREHOUSE_DB)
            st.dataframe(wh_df[['name', 'zip']].rename(columns={'name':'仓库名称', 'zip':'邮编'}), hide_index=True)

        template_df = pd.DataFrame(columns=["订单号", "发货邮编", "收货邮编", "收货州", "长", "宽", "高", "实重"])
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
            template_df.to_excel(writer, index=False)
        st.download_button("📄 下载模板", buffer.getvalue(), "LTL_Template_V4.xlsx")
        
        st.divider()
        uploaded_file = st.file_uploader("上传 Excel 文件", type=['xlsx'])
        
        if uploaded_file:
            try:
                df_input = pd.read_excel(uploaded_file, engine='openpyxl')
                required = ["订单号", "发货邮编", "收货邮编", "收货州", "长", "宽", "高", "实重"]
                
                if not all(c in df_input.columns for c in required):
                    st.error("❌ 格式错误！请使用新模板。")
                else:
                    grouped = df_input.groupby('订单号')
                    results = []
                    progress_bar = st.progress(0)
                    
                    for i, (order_id, group_df) in enumerate(grouped):
                        res, err = calculate_shipment(df_zone, df_rates, remote_zips, group_df)
                        row_res = {'订单号': order_id}
                        if err:
                            row_res['状态'] = '失败'
                            row_res['错误信息'] = err
                        else:
                            row_res['状态'] = '成功'
                            row_res.update(res)
                        results.append(row_res)
                        progress_bar.progress((i + 1) / len(grouped))
                    
                    res_df = pd.DataFrame(results)
                    st.success("🎉 计算完成！")
                    
                    output = io.BytesIO()
                    with pd.ExcelWriter(output, engine='openpyxl') as writer:
                        res_df.to_excel(writer, index=False)
                    st.download_button("📥 下载结果", output.getvalue(), "LTL_Result.xlsx", type="primary")
            except Exception as e:
                st.error(f"❌ 处理失败: {e}")