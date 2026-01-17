import streamlit as st
import pandas as pd
import os
import io

# ================= 1. 核心配置 (V4.3 - 批量计算版) =================
CONFIG = {
    'FILE_NAME': 'data.xlsx',
    'DIM_FACTOR': 200,
    'MIN_BILLABLE_WEIGHT': 173,
    'FUEL_RATE': 0.315,
    'REMOTE_RATE': 28,
    'OVERSIZE_FEE': 50,
    
    # 仓库映射 (V4.2 完整版)
    'WAREHOUSE_MAP': {
        # --- AI 仓系列 ---
        '91761': 'CA',   # AI美西001 / AI美西002
        '30294': 'SAV',  # AI美南GA002
        '08820': 'NJ',   # AI美东NJ003
        '31322': 'SAV',  # AI美南SAV仓002
        '77064': 'HOU',  # AI美南TX仓001
        '30517': 'SAV',  # AI美南GA001仓

        # --- 乐歌 仓系列 ---
        '31326': 'SAV',  # 乐歌美南SAV
        '92571': 'CA',   # 乐歌美西CAP仓
        '08016': 'NJ',   # 乐歌美东NJF
        '77494': 'HOU'   # 乐歌美中南HOU07
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
        
        # 清洗偏远邮编
        remote_zips = set(df_remote.iloc[:, 0].astype(str).str.replace('.0', '', regex=False).str.strip().tolist())
        
        return df_zone, rates, remote_zips, None
    except Exception as e:
        return None, None, None, f"数据读取错误: {str(e)}"

# ================= 3. 核心计算逻辑 (单行) =================
def calculate_single_row(df_zone, df_rates, remote_zips, o_zip, d_zip, d_state_input, L, W, H, weight):
    # 基础清洗
    o_zip = str(o_zip).replace('.0', '').strip()
    d_zip = str(d_zip).replace('.0', '').strip()
    d_state = str(d_state_input).upper().strip()
    
    warehouse = CONFIG['WAREHOUSE_MAP'].get(o_zip)
    if not warehouse: return None, f"未知发货邮编"

    col_name = f"{warehouse}发货分区"
    if col_name not in df_zone.columns: return None, f"缺{warehouse}数据"
    
    zone_row = df_zone[df_zone['state'] == d_state]
    if zone_row.empty: return None, f"州代码错误"
    
    zone = zone_row[col_name].values[0]

    # 计费重
    dim_weight = (L * W * H) / CONFIG['DIM_FACTOR']
    billable = max(weight, dim_weight, CONFIG['MIN_BILLABLE_WEIGHT'])

    # 费率
    is_west = (warehouse == 'CA')
    try:
        rate_row = df_rates[df_rates['Zone'] == zone].iloc[0]
    except:
        return None, f"无{zone}区费率"

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
    
    is_oversize = False
    if weight > 250: is_oversize = True
    elif (weight > 150) and (max(L,W,H) > 72): is_oversize = True
    oversize = CONFIG['OVERSIZE_FEE'] if is_oversize else 0
    
    total = base + fuel + remote + oversize
    
    return {
        '发货仓': warehouse, '分区': zone, '计费重': round(billable, 2),
        '基础运费': round(base, 2), '燃油费': round(fuel, 2),
        '偏远费': round(remote, 2), '超尺费': round(oversize, 2),
        '总费用': round(total, 2), '备注': '偏远' if is_remote else ''
    }, None

# ================= 4. 界面逻辑 =================
st.set_page_config(page_title="LTL 运费计算器 V4.3", page_icon="🚚", layout="wide")
st.title("🚚 马士基 LTL 运费计算器")

df_zone, df_rates, remote_zips, err_msg = load_data()

if err_msg:
    st.error(f"❌ 系统错误: {err_msg}")
else:
    # 创建选项卡
    tab1, tab2 = st.tabs(["🧮 单票计算", "📥 批量计算"])

    # --- TAB 1: 单票计算 ---
    with tab1:
        with st.form("calc_form"):
            col1, col2 = st.columns(2)
            with col1:
                o_zip = st.text_input("发货邮编", "08820", help="输入仓库邮编")
                d_zip = st.text_input("收货邮编", "49022")
                d_state = st.text_input("收货州代码", "MI", help="两位大写字母，如 CA, NY")
            with col2:
                c1, c2, c3 = st.columns(3)
                with c1: L = st.number_input("长 (in)", value=80.0)
                with c2: W = st.number_input("宽 (in)", value=32.2)
                with c3: H = st.number_input("高 (in)", value=24.6)
                weight = st.number_input("实重 (lbs)", value=141.0)
            
            submitted = st.form_submit_button("开始计算", type="primary")

        if submitted:
            res, err = calculate_single_row(df_zone, df_rates, remote_zips, o_zip, d_zip, d_state, L, W, H, weight)
            if err:
                st.error(f"❌ 计算失败: {err}")
            else:
                st.success(f"### 💰 预估总运费: ${res['总费用']}")
                st.info(f"📍 路线: {res['发货仓']} ➡️ {d_state} (分区 {res['分区']}) | ⚖️ 计费重: {res['计费重']} lbs")
                st.table(pd.DataFrame({
                    "费用项": ["基础运费", "燃油费", "偏远费", "超尺费"],
                    "金额": [res['基础运费'], res['燃油费'], res['偏远费'], res['超尺费']]
                }))

    # --- TAB 2: 批量计算 ---
    with tab2:
        st.markdown("### 1. 下载模板")
        st.markdown("请先下载标准模板，填好后上传。**表头名称请勿修改。**")
        
        # 生成模板文件
        template_df = pd.DataFrame(columns=["发货邮编", "收货邮编", "收货州", "长", "宽", "高", "实重"])
        # 写入 BytesIO
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
            template_df.to_excel(writer, index=False)
        
        st.download_button(
            label="📄 下载 Excel 模板",
            data=buffer.getvalue(),
            file_name="LTL_Batch_Template.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        
        st.markdown("---")
        st.markdown("### 2. 上传文件并计算")
        uploaded_file = st.file_uploader("上传填好的 Excel 文件", type=['xlsx'])
        
        if uploaded_file:
            try:
                # 读取上传的文件
                df_input = pd.read_excel(uploaded_file, engine='openpyxl')
                
                # 检查列名
                required_cols = ["发货邮编", "收货邮编", "收货州", "长", "宽", "高", "实重"]
                if not all(col in df_input.columns for col in required_cols):
                    st.error("❌ 模板格式错误！请确保包含以下列：" + ", ".join(required_cols))
                else:
                    st.write(f"✅ 成功读取 {len(df_input)} 条数据，正在计算...")
                    
                    results = []
                    progress_bar = st.progress(0)
                    
                    for i, row in df_input.iterrows():
                        res, err = calculate_single_row(
                            df_zone, df_rates, remote_zips,
                            row['发货邮编'], row['收货邮编'], row['收货州'],
                            row['长'], row['宽'], row['高'], row['实重']
                        )
                        
                        # 构建结果行
                        res_row = row.to_dict()
                        if err:
                            res_row['计算状态'] = '失败'
                            res_row['错误原因/总费用'] = err
                        else:
                            res_row['计算状态'] = '成功'
                            res_row['错误原因/总费用'] = res['总费用']
                            # 把详细费用也加上
                            res_row.update(res)
                        
                        results.append(res_row)
                        progress_bar.progress((i + 1) / len(df_input))
                    
                    # 结果展示
                    res_df = pd.DataFrame(results)
                    st.success("🎉 计算完成！")
                    
                    # 预览前5行
                    st.dataframe(res_df.head())
                    
                    # 下载结果
                    output = io.BytesIO()
                    with pd.ExcelWriter(output, engine='openpyxl') as writer:
                        res_df.to_excel(writer, index=False)
                        
                    st.download_button(
                        label="📥 下载计算结果",
                        data=output.getvalue(),
                        file_name="LTL_Calculation_Result.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        type="primary"
                    )
                    
            except Exception as e:
                st.error(f"❌ 文件处理失败: {e}")