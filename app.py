import streamlit as st
import pandas as pd
import io
import altair as alt
import gc

# ================= 1. 配置与映射 =================
COLUMN_MAPS = {
    'WP': { 
        'SKU': 'SKU', 'Warehouse': '仓库/Warehouse', 
        'Qty': '数量/Quantity', 'Fee': '金额/Amount', 
        'Age': '库龄/Library of Age', 'Vol': '体积(m³)',
        'Full_Name': 'WesternPost'
    },
    'LG': { 
        'SKU': '乐仓货品编码', 'Warehouse': '仓库', 
        'Qty': '数量', 'Fee': '计算金额', 
        'Age': '库龄', 'Vol': '总体积',
        'Full_Name': 'Lecangs'
    },
    'AI': { 
        'SKU': 'SKU', 'Warehouse': '仓库', 
        'Qty': '库存', 'Fee': '费用', 
        'Age': '在库天数', 'Vol': '立方数',
        'Full_Name': 'AI'
    },
    'WL': { 
        'SKU': '商品SKU', 'Warehouse': '实际发货仓库', 
        'Qty': '库存总数_QTY', 'Fee': '计费总价', 
        'Age': '库存库龄_CD', 'Vol': '计费总体积_立方米',
        'Full_Name': 'WWL'
    }
}

# 库龄分段逻辑
AGE_BINS = [-1, 30, 60, 90, 120, 180, 360, 99999]
AGE_LABELS = ['0-30天', '31-60天', '61-90天', '91-120天', '121-180天', '181-360天', '360天+']
AGE_MAP = {label: i for i, label in enumerate(AGE_LABELS)}

# ================= 2. 核心处理逻辑 =================

def parse_filename(filename):
    try:
        name_body = filename.rsplit('.', 1)[0]
        parts = name_body.split('_')
        if len(parts) >= 3:
            dept = parts[0]
            raw_code = parts[1].upper()
            provider_code = None
            for key in COLUMN_MAPS.keys():
                if key in raw_code:
                    provider_code = key
                    break
            date_str = parts[2]
            return dept, provider_code, date_str
        return None, None, None
    except Exception:
        return None, None, None

@st.cache_data(ttl=3600, show_spinner=False)
def load_data_cached(file_content, file_name):
    try:
        file = io.BytesIO(file_content)
        file.name = file_name 

        dept, provider_code, date_str = parse_filename(file.name)
        
        if not dept:
            dept = "默认部门"
            for code in COLUMN_MAPS.keys():
                if code in file.name.upper():
                    provider_code = code
                    break
            date_str = "最新"

        if not provider_code:
            return pd.DataFrame()

        df = None
        try: df = pd.read_excel(file, engine='openpyxl', header=None); 
        except: pass
        if df is None:
            try: file.seek(0); df = pd.read_csv(file, encoding='utf-8', header=None)
            except: pass
        if df is None:
            try: file.seek(0); df = pd.read_csv(file, encoding='gb18030', header=None)
            except: pass
                
        if df is None:
            return pd.DataFrame()

        mapping = COLUMN_MAPS[provider_code]
        
        header_idx = 0
        expected_cols = set(mapping.values())
        expected_cols.discard(mapping.get('Full_Name'))
        
        for i in range(min(20, len(df))):
            row_values = df.iloc[i].astype(str).str.strip().tolist()
            row_values = [x.replace('\ufeff', '') for x in row_values]
            match_count = sum(1 for x in row_values if x in expected_cols)
            if match_count >= 2:
                header_idx = i
                break
        
        new_columns = df.iloc[header_idx].astype(str).str.strip().str.replace('\ufeff', '')
        df = df.iloc[header_idx+1:].copy()
        df.columns = new_columns

        if provider_code == 'WL':
            if not df.empty:
                df = df.iloc[1:]

        valid_map = {k: v for k, v in mapping.items() if v in df.columns}
        rename_dict = {v: k for k, v in valid_map.items()}
        df = df.rename(columns=rename_dict)
        
        required_cols = ['SKU', 'Warehouse', 'Qty', 'Fee', 'Age', 'Vol']
        for col in required_cols:
            if col not in df.columns: df[col] = 0 
                
        for col in ['Qty', 'Fee', 'Age', 'Vol']:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
            
        cut_series = pd.cut(df['Age'], bins=AGE_BINS, labels=AGE_LABELS, right=True)
        df['Age_Range'] = cut_series.astype(str)
        df.loc[df['Age_Range'] == 'nan', 'Age_Range'] = '360天+'
        df['Age_Range'] = df['Age_Range'].str.strip()

        df['Dept'] = str(dept)
        df['Provider'] = str(mapping['Full_Name'])
        df['Date'] = str(date_str)
        
        gc.collect()
        return df
        
    except Exception:
        return pd.DataFrame()

# ================= 3. 界面逻辑 =================
st.set_page_config(page_title="海外仓库存 BI V4.8", page_icon="🏢", layout="wide")
st.title("🏢 海外仓库存分析看板 V4.8 ")

with st.sidebar:
    st.header("📂 数据中心")
    uploaded_files = st.file_uploader("批量上传文件", type=['xlsx', 'xls', 'csv'], accept_multiple_files=True)
    
    if st.button("🧹 刷新缓存"):
        st.cache_data.clear()
        st.success("缓存已清除")

    dfs = []
    if uploaded_files:
        my_bar = st.progress(0, text="正在解析...")
        for i, file in enumerate(uploaded_files):
            df = load_data_cached(file.getvalue(), file.name)
            if not df.empty:
                dfs.append(df)
            my_bar.progress((i + 1) / len(uploaded_files))
        my_bar.empty()
        st.success(f"✅ 已加载 {len(dfs)} 个有效文件")

if not dfs:
    st.info("👈 请在左侧上传数据文件")
else:
    full_df = pd.concat(dfs, ignore_index=True)
    
    for col in ['Dept', 'Provider', 'Warehouse', 'Date']:
        if col in full_df.columns:
            full_df[col] = full_df[col].astype(str)

    tab1, tab2 = st.tabs(["📊 全景详情 (SKU级)", "🆚 历史趋势 & 风险洞察"])
    
    # ================= TAB 1: 全景详情 =================
    with tab1:
        try:
            # 筛选区域
            all_depts = sorted(full_df['Dept'].unique().tolist())
            all_depts.insert(0, "全部汇总")
            
            c1, c2, c3, c4 = st.columns(4)
            with c1: sel_dept = st.selectbox("① 选择部门", all_depts, key='t1_d')
            df_l1 = full_df if sel_dept == "全部汇总" else full_df[full_df['Dept'] == sel_dept]

            avail_dates = sorted(df_l1['Date'].unique().tolist(), reverse=True)
            with c2: sel_date = st.selectbox("② 选择月份 (基准)", avail_dates, key='t1_dt')
            df_l2 = df_l1[df_l1['Date'] == sel_date]

            avail_provs = sorted(df_l2['Provider'].unique().tolist())
            avail_provs.insert(0, "全部汇总")
            with c3: sel_prov = st.selectbox("③ 选择服务商", avail_provs, key='t1_p')
            df_l3 = df_l2 if sel_prov == "全部汇总" else df_l2[df_l2['Provider'] == sel_prov]
                
            avail_whs = sorted(df_l3['Warehouse'].unique().tolist())
            with c4: sel_whs = st.multiselect("④ 选择仓库 (可多选)", avail_whs, default=avail_whs)
            
            if not sel_whs:
                st.warning("请至少选择一个仓库")
                final_df = pd.DataFrame()
            else:
                final_df = df_l3[df_l3['Warehouse'].isin(sel_whs)]
            
            if not final_df.empty:
                # 顶部 KPI
                wh_display = "多个仓库" if len(sel_whs) > 1 else sel_whs[0]
                st.markdown(f"### 📋 数据视图：{sel_dept} · {sel_prov} · {wh_display}")

                k1, k2, k3 = st.columns(3)
                k1.metric("总库存 (Qty)", f"{final_df['Qty'].sum():,.0f}")
                k2.metric("总体积 (Vol)", f"{final_df['Vol'].sum():,.2f} m³")
                k3.metric("单日总费用 (Fee)", f"${final_df['Fee'].sum():,.2f}")
                
                # 库龄分段统计表
                summary = final_df.groupby('Age_Range').agg({'Fee':'sum','Qty':'sum','Vol':'sum'}).reset_index()
                order_map = {l: i for i, l in enumerate(AGE_LABELS)}
                summary['sort'] = summary['Age_Range'].map(order_map).fillna(999)
                summary = summary.sort_values('sort').drop('sort', axis=1)
                
                total_fee = final_df['Fee'].sum()
                total_vol = final_df['Vol'].sum()
                summary['费用占比'] = (summary['Fee'] / total_fee * 100).fillna(0)
                summary['体积占比'] = (summary['Vol'] / total_vol * 100).fillna(0)
                
                st.dataframe(
                    summary.style.format({
                        'Fee':'${:.2f}', 'Vol':'{:.2f}', '费用占比':'{:.1f}%', '体积占比':'{:.1f}%'
                    }), 
                    use_container_width=True
                )
                
                st.divider()
                st.markdown("#### 🔍 异常库存深钻 (含跨月追踪)")
                
                valid_ages = [l for l in AGE_LABELS if l in final_df['Age_Range'].unique()]
                
                if valid_ages:
                    # 交互控制
                    r_col1, r_col2 = st.columns([3, 1])
                    with r_col1:
                        rng = st.radio("锁定库龄段", valid_ages, horizontal=True, index=len(valid_ages)-1, key='t1_r')
                    
                    show_agg = False
                    if sel_dept == "全部汇总" or sel_prov == "全部汇总" or len(sel_whs) > 1:
                        with r_col2:
                            st.write("")
                            st.write("") 
                            show_agg = st.checkbox("🔀 SKU 宏观聚合", value=True, key="chk_agg_mode")

                    other_dates = [d for d in full_df['Date'].unique() if d != sel_date]
                    other_dates.sort(reverse=True)
                    target_month = st.selectbox(
                        "📅 开启下月追踪 (选择一个比基准月晚的月份，留空则关闭)", 
                        ["关闭追踪"] + other_dates,
                        index=0
                    )

                    # 数据准备
                    drill = final_df[final_df['Age_Range'] == rng].copy()
                    
                    if drill.empty:
                        st.info("无数据")
                    else:
                        # 1. 准备基准数据
                        if show_agg:
                            base_df = drill.groupby('SKU').agg({
                                'Qty': 'sum', 'Vol': 'sum', 'Fee': 'sum', 'Age': 'mean',
                                'Warehouse': 'nunique', 'Dept': 'nunique', 'Provider': 'nunique'
                            }).reset_index()
                            
                            def build_info(row):
                                infos = []
                                if sel_dept == "全部汇总" and row['Dept'] > 1: infos.append(f"{row['Dept']}个部门")
                                if sel_prov == "全部汇总" and row['Provider'] > 1: infos.append(f"{row['Provider']}个服务商")
                                infos.append(f"{row['Warehouse']}个仓")
                                return " | ".join(infos)
                            base_df['分布情况'] = base_df.apply(build_info, axis=1)
                        else:
                            base_df = drill[['SKU', 'Warehouse', 'Qty', 'Vol', 'Fee', 'Age']].copy()

                        # 取 TOP 50
                        base_df = base_df.sort_values('Fee', ascending=False).head(50)

                        # 2. 追踪逻辑
                        is_tracking = (target_month != "关闭追踪")
                        
                        if is_tracking:
                            mask_track = (
                                (full_df['Date'] == target_month) & 
                                (full_df['SKU'].isin(base_df['SKU']))
                            )
                            if sel_dept != "全部汇总": mask_track &= (full_df['Dept'] == sel_dept)
                            if sel_prov != "全部汇总": mask_track &= (full_df['Provider'] == sel_prov)
                            if len(sel_whs) > 0: mask_track &= (full_df['Warehouse'].isin(sel_whs))
                            
                            track_raw = full_df[mask_track].copy()
                            
                            if show_agg:
                                track_ready = track_raw.groupby('SKU').agg({
                                    'Qty': 'sum', 'Vol': 'sum', 'Fee': 'sum', 'Age': 'mean'
                                }).reset_index()
                                merge_on = ['SKU']
                            else:
                                track_ready = track_raw[['SKU', 'Warehouse', 'Qty', 'Vol', 'Fee', 'Age']]
                                merge_on = ['SKU', 'Warehouse']

                            final_show = pd.merge(base_df, track_ready, on=merge_on, suffixes=('', '_下月'), how='left')
                            
                            # 填充0
                            for col in ['Qty_下月', 'Vol_下月', 'Fee_下月', 'Age_下月']:
                                final_show[col] = final_show[col].fillna(0)
                                
                            # 计算 Delta
                            final_show['库存变化'] = final_show['Qty_下月'] - final_show['Qty']
                            final_show['体积变化'] = final_show['Vol_下月'] - final_show['Vol']
                            final_show['费用变化'] = final_show['Fee_下月'] - final_show['Fee']
                            final_show['库龄增量'] = final_show['Age_下月'] - final_show['Age']
                            
                        else:
                            final_show = base_df.copy()

                        # 3. 字段整理
                        current_total_vol = base_df['Vol'].sum()
                        final_show['体积占比'] = (final_show['Vol'] / current_total_vol * 100) if current_total_vol > 0 else 0

                        # 定义列序和重命名
                        if show_agg:
                            base_cols = ['SKU', '分布情况', 'Qty', 'Vol', 'Fee', 'Age', '体积占比']
                            rename_map = {'Qty':'库存(基准)', 'Vol':'体积(基准)', 'Fee':'费用(基准)', 'Age':'库龄(基准)'}
                        else:
                            base_cols = ['SKU', 'Warehouse', 'Qty', 'Vol', 'Fee', 'Age', '体积占比']
                            rename_map = {'Qty':'库存(基准)', 'Vol':'体积(基准)', 'Fee':'费用(基准)', 'Age':'库龄(基准)'}
                        
                        cols_order = base_cols.copy()
                        
                        if is_tracking:
                            # 插入追踪列：按逻辑分组 Qty -> Vol -> Fee -> Age
                            cols_order.extend(['Qty_下月', '库存变化', 'Vol_下月', '体积变化', 'Fee_下月', '费用变化', 'Age_下月', '库龄增量'])
                            rename_map.update({
                                'Qty_下月': f'库存({target_month})', 
                                'Vol_下月': f'体积({target_month})',
                                'Fee_下月': f'费用({target_month})',
                                'Age_下月': f'库龄({target_month})'
                            })

                        display_df = final_show[cols_order].rename(columns=rename_map)

                        # 4. 样式渲染
                        st.write(f"📊 **TOP 50 SKU 深度分析** {'(含 ' + target_month + ' 追踪数据)' if is_tracking else ''}")
                        
                        def style_tracking(styler):
                            fmt_dict = {
                                '费用(基准)': '${:.2f}', '体积(基准)': '{:.2f}', '库龄(基准)': '{:.0f}', '体积占比': '{:.1f}%',
                                '库存(基准)': '{:.0f}'
                            }
                            if is_tracking:
                                next_qty_col = f'库存({target_month})'
                                next_vol_col = f'体积({target_month})'
                                next_fee_col = f'费用({target_month})'
                                next_age_col = f'库龄({target_month})'
                                
                                fmt_dict.update({
                                    next_qty_col: '{:.0f}', '库存变化': '{:.0f}',
                                    next_vol_col: '{:.2f}', '体积变化': '{:.2f}',
                                    next_fee_col: '${:.2f}', '费用变化': '${:.2f}',
                                    next_age_col: '{:.0f}', '库龄增量': '{:.0f}'
                                })
                            
                            styler = styler.format(fmt_dict)
                            # 基准费用色阶
                            styler = styler.background_gradient(subset=['费用(基准)'], cmap='Reds')

                            if is_tracking:
                                # 变化列的高亮逻辑
                                def highlight_good_bad(v):
                                    if v < 0: return 'color: green; font-weight: bold' # 变少(好)
                                    if v > 0: return 'color: red'   # 变多(坏)
                                    return 'color: lightgray'

                                def highlight_fee_diff(v):
                                    if v < 0: return 'background-color: #e6ffe6; color: green' # 省钱了
                                    if v > 0: return 'background-color: #ffe6e6; color: red'   # 多花钱了
                                    return ''

                                styler = styler.applymap(highlight_good_bad, subset=['库存变化', '体积变化'])
                                styler = styler.applymap(highlight_fee_diff, subset=['费用变化'])
                            
                            return styler

                        st.dataframe(
                            style_tracking(display_df.style),
                            use_container_width=True,
                            height=600
                        )

                else:
                    st.warning("该筛选条件下无数据")
        
        except Exception as e:
            st.error(f"⚠️ 界面渲染发生错误: {str(e)}")

    # ================= TAB 2: 趋势对比 (保持稳定) =================
    with tab2:
        try:
            st.markdown("#### 🆚 历史趋势 & 风险洞察")
            
            cc1, cc2, cc3 = st.columns(3)
            all_depts_t = sorted(full_df['Dept'].unique().tolist())
            all_depts_t.insert(0, "全部汇总")
            with cc1: t_dept = st.selectbox("分析部门", all_depts_t, key='t2_d')
            df_t1 = full_df if t_dept == "全部汇总" else full_df[full_df['Dept'] == t_dept]

            all_provs_t = sorted(df_t1['Provider'].unique().tolist())
            all_provs_t.insert(0, "全部汇总")
            with cc2: t_prov = st.selectbox("分析服务商", all_provs_t, key='t2_p')
            df_t2 = df_t1 if t_prov == "全部汇总" else df_t1[df_t1['Provider'] == t_prov]

            all_whs_t = sorted(df_t2['Warehouse'].unique().tolist())
            with cc3: 
                t_whs = st.multiselect("分析仓库 (可多选)", all_whs_t, default=all_whs_t, key='t2_w')
            
            if not t_whs:
                st.warning("请至少选择一个仓库")
                t_final = pd.DataFrame()
            else:
                t_final = df_t2[df_t2['Warehouse'].isin(t_whs)]
            
            if not t_final.empty:
                avail_dates = sorted(t_final['Date'].unique())
                selected_dates = st.multiselect("选择分析月份", avail_dates, default=avail_dates)
                
                if len(selected_dates) > 0:
                    chart_df = t_final[t_final['Date'].isin(selected_dates)]
                    
                    st.divider()
                    
                    # 柱状图：Vol + 标签
                    agg_df = chart_df.groupby(['Date', 'Age_Range']).agg({
                        'Qty': 'sum', 'Fee': 'sum', 'Vol': 'sum'
                    }).reset_index()
                    
                    st.markdown("##### 📦 各库龄段库存体积 (Vol) 对比")
                    
                    base_bar = alt.Chart(agg_df).encode(
                        x=alt.X('Age_Range', sort=AGE_LABELS, title="库龄分段"),
                        y=alt.Y('Vol', title="库存体积 (m³)"),
                        color=alt.Color('Date', title="月份"),
                        tooltip=['Date', 'Age_Range', 'Vol', 'Qty']
                    )
                    
                    bars = base_bar.mark_bar().encode(xOffset='Date')
                    
                    text = base_bar.mark_text(
                        align='center', baseline='bottom', dy=-5
                    ).encode(
                        xOffset='Date', text=alt.Text('Vol', format='.1f')
                    )
                    
                    st.altair_chart((bars + text).properties(height=400), use_container_width=True)
                    
                    # 折线图：单位成本 + 标签
                    st.divider()
                    st.markdown("##### 📉 单位仓租成本趋势 (Fee / Qty)")
                    
                    cpu_trend = chart_df.groupby('Date').apply(
                        lambda x: pd.Series({'CPU': x['Fee'].sum() / x['Qty'].sum() if x['Qty'].sum() > 0 else 0})
                    ).reset_index()
                    
                    base_line = alt.Chart(cpu_trend).encode(
                        x=alt.X('Date', title="月份"),
                        y=alt.Y('CPU', title='单件成本 ($)'),
                        tooltip=['Date', alt.Tooltip('CPU', format='.3f')]
                    )
                    
                    line = base_line.mark_line(point=True)
                    line_text = base_line.mark_text(align='left', dx=5, dy=-5).encode(text=alt.Text('CPU', format='.3f'))

                    st.altair_chart((line + line_text).properties(height=350), use_container_width=True)

                    # 恶化监控
                    st.divider()
                    st.markdown("#### 🚨 恶化监控")
                    if len(selected_dates) >= 2:
                        sorted_dates = sorted(selected_dates)
                        curr, prev = sorted_dates[-1], sorted_dates[-2]
                        group_cols = ['SKU', 'Warehouse', 'Dept', 'Provider']
                        
                        df_c = chart_df[chart_df['Date'] == curr][group_cols + ['Age_Range', 'Fee']]
                        df_p = chart_df[chart_df['Date'] == prev][group_cols + ['Age_Range']]
                        
                        merged = pd.merge(df_p, df_c, on=group_cols, suffixes=('_old', '_new'))
                        merged['i_old'] = merged['Age_Range_old'].map(AGE_MAP).fillna(-1)
                        merged['i_new'] = merged['Age_Range_new'].map(AGE_MAP).fillna(-1)
                        
                        bad = merged[merged['i_new'] > merged['i_old']].copy()
                        if bad.empty:
                            st.success("🎉 无恶化")
                        else:
                            bad['Fee'] = bad['Fee'].astype(float)
                            show = bad.sort_values('Fee', ascending=False).head(20)
                            st.dataframe(show[['SKU', 'Dept', 'Warehouse', 'Age_Range_old', 'Age_Range_new', 'Fee']].style.format({'Fee':'${:.2f}'}).background_gradient(subset=['Fee'], cmap='Reds'), use_container_width=True)
                else:
                    st.info("请至少选择一个月份")
        except Exception as e:
            st.error(f"趋势图表渲染错误: {str(e)}")