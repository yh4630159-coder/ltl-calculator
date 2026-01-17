import streamlit as st
import pandas as pd
import os
import io

# ================= 1. 核心配置 (V4.4 - 一票多件版) =================
CONFIG = {
    'FILE_NAME': 'data.xlsx',
    'DIM_FACTOR': 200,
    'MIN_BILLABLE_WEIGHT': 173,
    'FUEL_RATE': 0.315,
    'REMOTE_RATE': 28,
    'OVERSIZE_FEE': 50,
    
    # 仓库映射 (保持 V4.2 完整版)
    'WAREHOUSE_MAP': {
        '91761': 'CA', '30294': 'SAV', '08820': 'NJ', '31322': 'SAV',
        '77064': 'HOU', '30517': 'SAV', '31326': 'SAV', '92571': 'CA',
        '08016': 'NJ', '77494': 'HOU'
    }
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

# ================= 3. 核心计算逻辑 (支持合并) =================
def calculate_shipment(df_zone, df_rates, remote_zips, shipment_data):
    """
    shipment_data: 一个包含该订单所有包裹信息的 DataFrame
    """
    # 1. 提取基础信息 (取第一行数据，假设同一订单发收地址一致)
    first_item = shipment_data.iloc[0]
    o_zip = str(first_item['发货邮编']).replace('.0', '').strip()
    d_zip = str(first_item['收货邮编']).replace('.0', '').strip()
    d_state = str(first_item['收货州']).upper().strip()
    
    # 2. 匹配分区
    warehouse = CONFIG['WAREHOUSE_MAP'].get(o_zip)
    if not warehouse: return None, f"未知发货邮编 {o_zip}"

    col_name = f"{warehouse}发货分区"
    if col_name not in df_zone.columns: return None, f"缺 {warehouse} 数据"
    
    zone_row = df_zone[df_zone['state'] == d_state]
    if zone_row.empty: return None, f"州代码 {d_state} 错误"
    
    zone = zone_row[col_name].values[0]

    # 3. 聚合计算重量与尺寸 (V4.4 核心升级)
    total_actual_weight = 0
    total_dim_weight = 0
    is_oversize = False
    
    package_details = [] # 用于记录每件包裹的详情

    for _, row in shipment_data.iterrows():
        l, w, h, weight = row['长'], row['宽'], row['高'], row['实重']
        
        # 累加实重
        total_actual_weight += weight
        
        # 累加体积重
        dim_w = (l * w * h) / CONFIG['DIM_FACTOR']
        total_dim_weight += dim_w
        
        # 检查单件超尺 (只要有一件超，整票就超)
        # 规则: 实重>250 OR (实重>150 AND 任意边>72)
        if weight > 250:
            is_oversize = True
        elif (weight > 150) and (max(l, w, h) > 72):
            is_oversize = True
            
        package_details.append(f"{l}x{w}x{h}/{weight}lbs")

    # 4. 计算最终计费重 (一票只收一个起步价)
    billable = max(total_actual_weight, total_dim_weight, CONFIG['MIN_BILLABLE_WEIGHT'])

    # 5. 费率匹配
    is_west = (warehouse == 'CA')
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
        '发货仓': warehouse, '分区': zone, 
        '包裹数': len(shipment_data),
        '总实重': round(total_actual_weight, 2),
        '总体积重': round(total_dim_weight, 2),
        '计费重': round(billable, 2),
        '基础运费': round(base, 2), '燃油费': round(fuel, 2),
        '偏远费': round(remote, 2), '超尺费': round(oversize, 2),
        '总费用': round(total, 2), '备注': '偏远' if is_remote else ''
    }, None

# ================= 4. 界面逻辑 =================
st.set_page_config(page_title="LTL 运费计算器 V4.4", page_icon="🚚", layout="wide")
st.title("🚚 马士基 LTL 运费计算器")
st.caption("逻辑版本: V4.4 (支持一票多件合并计算)")

df_zone, df_rates, remote_zips, err_msg = load_data()

if err_msg:
    st.error(f"❌ 系统错误: {err_msg}")
else:
    tab1, tab2 = st.tabs(["🧮 单票计算 (快速)", "📥 批量计算 (含多件合并)"])

    # --- TAB 1: 单票计算 (保持简便) ---
    with tab1:
        st.info("💡 提示：单票计算仅支持单个包裹。如果是多件货物，请使用“批量计算”功能。")
        with st.form("calc_form"):
            col1, col2 = st.columns(2)
            with col1:
                o_zip = st.text_input("发货邮编", "08820")
                d_zip = st.text_input("收货邮编", "49022")
                d_state = st.text_input("收货州代码", "MI")
            with col2:
                c1, c2, c3 = st.columns(3)
                with c1: L = st.number_input("长 (in)", value=80.0)
                with c2: W = st.number_input("宽 (in)", value=32.2)
                with c3: H = st.number_input("高 (in)", value=24.6)
                weight = st.number_input("实重 (lbs)", value=141.0)
            submitted = st.form_submit_button("计算")
            
            if submitted:
                # 构造单行数据模拟 DataFrame
                mock_df = pd.DataFrame([{
                    '发货邮编': o_zip, '收货邮编': d_zip, '收货州': d_state,
                    '长': L, '宽': W, '高': H, '实重': weight
                }])
                res, err = calculate_shipment(df_zone, df_rates, remote_zips, mock_df)
                if err: st.error(err)
                else:
                    st.success(f"### 总费用: ${res['总费用']}")
                    st.table(pd.DataFrame({k:[v] for k,v in res.items() if k not in ['包裹数','总实重','总体积重']}))

    # --- TAB 2: 批量计算 (核心升级) ---
    with tab2:
        st.markdown("### 1. 下载 V4.4 新版模板")
        st.markdown("**⚠️ 注意：必须填写【订单号】列。订单号相同的行，会自动合并为一票计算。**")
        
        # 模板包含订单号
        template_df = pd.DataFrame(columns=["订单号", "发货邮编", "收货邮编", "收货州", "长", "宽", "高", "实重"])
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
            template_df.to_excel(writer, index=False)
        
        st.download_button("📄 下载模板", buffer.getvalue(), "LTL_Multi_Piece_Template.xlsx")
        
        st.markdown("---")
        uploaded_file = st.file_uploader("上传 Excel 文件", type=['xlsx'])
        
        if uploaded_file:
            try:
                df_input = pd.read_excel(uploaded_file, engine='openpyxl')
                required = ["订单号", "发货邮编", "收货邮编", "收货州", "长", "宽", "高", "实重"]
                
                if not all(c in df_input.columns for c in required):
                    st.error("❌ 格式错误！请务必使用新模板，确认包含【订单号】列。")
                else:
                    # 核心逻辑：按订单号分组
                    grouped = df_input.groupby('订单号')
                    results = []
                    
                    st.write(f"📊 识别到 {len(grouped)} 个独立订单，正在合并计算...")
                    progress_bar = st.progress(0)
                    
                    for i, (order_id, group_df) in enumerate(grouped):
                        res, err = calculate_shipment(df_zone, df_rates, remote_zips, group_df)
                        
                        # 结果行
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
                    st.dataframe(res_df.head())
                    
                    output = io.BytesIO()
                    with pd.ExcelWriter(output, engine='openpyxl') as writer:
                        res_df.to_excel(writer, index=False)
                    st.download_button("📥 下载合并后结果", output.getvalue(), "LTL_Result_Merged.xlsx", type="primary")
                    
            except Exception as e:
                st.error(f"❌ 处理失败: {e}")