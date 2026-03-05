import streamlit as st
import pandas as pd
import plotly.express as px
from io import BytesIO

# --- 页面基础设置 ---
st.set_page_config(page_title="亚马逊财务中台-V10.0", page_icon="📈", layout="wide")
st.title("📈 亚马逊全链路利润与审计系统 (V10.0 终极实战版)")

# --- 侧边栏：设置与上传 ---
st.sidebar.header("数据源上传")
report_file = st.sidebar.file_uploader("上传 亚马逊销售表 (CSV/TXT)", type=['csv', 'txt'])
cost_file = st.sidebar.file_uploader("上传 SKU 成本表 (Excel/CSV)", type=['csv', 'xlsx'])

# --- 醒目的运费录入区 ---
st.sidebar.markdown("""
    <hr>
    <h2 style='color: #FF4B4B; font-weight: bold;'>🚢 1. 当月头程运费录入 (CNY)</h2>
    <p style='color: #FF4B4B; font-size: 13px;'>请输入本月分摊到此账号的总运费</p>
""", unsafe_allow_html=True)
manual_freight = st.sidebar.number_input("输入人民币金额", min_value=0.0, value=0.0, step=100.0, key="freight_input")

# --- 财务参数 ---
st.sidebar.markdown("<hr><h3>2. 财务参数设定</h3>", unsafe_allow_html=True)
exchange_rate = st.sidebar.number_input("💵 结算汇率 (USD -> CNY)", min_value=1.0, value=7.00, step=0.01)
recovery_rate = st.sidebar.number_input("♻️ 退货完好可售比例 (%)", min_value=0, max_value=100, value=50, step=1)

# --- 后台逻辑部分 ---
@st.cache_data 
def process_data(file):
    content = file.getvalue().decode('utf-8', errors='ignore')
    lines = content.split('\n')
    skip_n = 0
    for i, line in enumerate(lines):
        if 'settlement id' in line.lower() and 'type' in line.lower():
            skip_n = i
            break
    file.seek(0)
    df = pd.read_csv(file, skiprows=skip_n, sep=None, engine='python')
    df.columns = df.columns.str.strip().str.lower()
    if 'sku' in df.columns:
        df['sku'] = df['sku'].astype(str).str.strip().str.upper()
    if 'date/time' in df.columns:
        df['date/time'] = df['date/time'].str.replace(' PDT', '').str.replace(' PST', '')
        df['datetime'] = pd.to_datetime(df['date/time'], errors='coerce')
        df['date'] = df['datetime'].dt.date
    for col in ['total', 'product sales', 'selling fees', 'fba fees']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col].astype(str).str.replace(',', ''), errors='coerce').fillna(0)
    if 'description' in df.columns:
        df['is_ad'] = df['description'].str.contains('Advertising', case=False, na=False)
    else:
        df['is_ad'] = False
    return df

@st.cache_data
def process_cost(file):
    if file.name.endswith('.csv'):
        cost_df = pd.read_csv(file, encoding='utf-8-sig')
    else:
        xls = pd.ExcelFile(file)
        sheet_names = xls.sheet_names
        best_sheet = sheet_names[0]
        if len(sheet_names) > 1:
            for sheet in sheet_names:
                temp_df = pd.read_excel(xls, sheet_name=sheet, nrows=3)
                cols_str = "".join(temp_df.columns.astype(str))
                if ('名' in cols_str or '产品' in cols_str) and ('成本' in cols_str or '价' in cols_str):
                    best_sheet = sheet
                    break
        cost_df = pd.read_excel(xls, sheet_name=best_sheet)
    
    cost_df.columns = cost_df.columns.astype(str).str.replace('\r', ' ').str.replace('\n', ' ').str.strip()
    cost_df.columns = cost_df.columns.str.replace(r'\s+', ' ', regex=True)
    
    col_name = '中文名'
    for name in ['中文名', '产品名称', '品名']:
        if name in cost_df.columns:
            col_name = name
            break
            
    col_inc = '销售成本'
    for c_name in ['销售成本含税', '销售成本', '成本', '含税单价', '含税成本']:
        if c_name in cost_df.columns:
            col_inc = c_name
            break
            
    col_exc = None
    has_exc = False
    for c_name in ['销售成本不含税', '不含税成本']:
        if c_name in cost_df.columns:
            col_exc = c_name
            has_exc = True
            break
            
    if col_name not in cost_df.columns: cost_df[col_name] = '未知产品'
    if col_inc not in cost_df.columns: cost_df[col_inc] = 0.0
        
    id_vars_list = [col_name, col_inc]
    if has_exc: id_vars_list.append(col_exc)
        
    exclude_cols = [col_name, col_inc, col_exc, '备注', '图片', '未命名', '序号', 'ID', 'NO', 'UNNAMED', '价', '重', '长', '宽', '高', '率', 'HS', '体积']
    sku_cols = [c for c in cost_df.columns if c not in exclude_cols and 'UNNAMED' not in c.upper()]
    
    melted = cost_df.melt(id_vars=id_vars_list, value_vars=sku_cols, value_name='sku')
    melted['sku'] = melted['sku'].astype(str).str.strip().str.upper() 
    melted = melted[~melted['sku'].isin(['NAN', 'NONE', 'NULL', ''])]
    melted[col_inc] = pd.to_numeric(melted[col_inc], errors='coerce').fillna(0.0)
    if has_exc: melted[col_exc] = pd.to_numeric(melted[col_exc], errors='coerce').fillna(0.0)
    return melted.drop_duplicates(subset=['sku'], keep='last'), col_name, col_inc, col_exc, has_exc

# --- 主页面执行逻辑 ---
if report_file and cost_file:
    df_raw = process_data(report_file)
    cost_df, col_name, col_inc, col_exc, has_exc = process_cost(cost_file)
    rf = recovery_rate / 100.0
    
    min_date = df_raw['date'].min()
    max_date = df_raw['date'].max()
    st.sidebar.markdown("<hr>", unsafe_allow_html=True)
    st.sidebar.header("3. 时间范围选择")
    date_range = st.sidebar.date_input("筛选数据日期", [min_date, max_date], min_value=min_date, max_value=max_date)
    
    if len(date_range) == 2:
        start_date, end_date = date_range
        df = df_raw[(df_raw['date'] >= start_date) & (df_raw['date'] <= end_date)].copy()
    else:
        df = df_raw.copy()
        
    # 美元汇总
    gross_sales_usd = df['product sales'].sum()
    df_no_transfer = df[~df['type'].str.contains('Transfer', case=False, na=False)]
    total_payout_usd = df_no_transfer['total'].sum()
    ad_spend_usd = abs(df[df['is_ad']]['total'].sum())
    ad_permille = (ad_spend_usd / gross_sales_usd * 1000) if gross_sales_usd > 0 else 0
    transfer_total_usd = abs(df[df['type'].str.contains('Transfer', case=False, na=False)]['total'].sum())
    
    # 财务汇总
    df_items = df[df['type'].str.contains('Order|Refund|Adjustment', case=False, na=False)].copy()
    q_col = 'quantity' if 'quantity' in df_items.columns else 'amount-description'
    df_items['qty_val'] = pd.to_numeric(df_items[q_col], errors='coerce').fillna(0).abs()
    df_items['order_qty'] = df_items.apply(lambda x: x['qty_val'] if 'Order' in str(x['type']) else 0, axis=1)
    df_items['refund_qty'] = df_items.apply(lambda x: x['qty_val'] if 'Refund' in str(x['type']) else 0, axis=1)
    df_items['adj_qty'] = df_items.apply(lambda x: x['qty_val'] if 'Adjustment' in str(x['type']) else 0, axis=1)
    
    sku_stats = df_items.groupby('sku').agg({'order_qty':'sum', 'refund_qty':'sum', 'adj_qty':'sum', 'product sales':'sum', 'total':'sum'}).reset_index()
    sku_merged = pd.merge(sku_stats, cost_df, on='sku', how='left')
    sku_merged[col_name] = sku_merged[col_name].fillna('未知产品')
    sku_merged[col_inc] = pd.to_numeric(sku_merged[col_inc], errors='coerce').fillna(0.0)
    
    cost_inc_total = ((sku_merged['order_qty'] + sku_merged['adj_qty']) * sku_merged[col_inc]).sum()
    recovery_inc_total = (sku_merged['refund_qty'] * sku_merged[col_inc] * rf).sum()
    profit_inc_total = (total_payout_usd * exchange_rate) - cost_inc_total + recovery_inc_total - manual_freight
    
    # --- 渲染展示 ---
    st.markdown("### 💰 财务概览 (宏观汇总)")
    
    st.markdown("##### 💵 结算基础 (USD)")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("总销售额 (USD)", f"${gross_sales_usd:,.2f}")
    c2.metric("亚马逊净打款 (USD)", f"${total_payout_usd:,.2f}")
    c3.markdown(f"<div style='padding-top: 0.2rem;'><p style='font-size: 14px; margin-bottom: 0px;'>广告花费 (USD)</p><div style='font-size: 1.8rem; font-weight: 600;'>${ad_spend_usd:,.2f} <span style='font-size: 0.5em; color: gray;'>({ad_permille:.1f}‰)</span></div></div>", unsafe_allow_html=True)
    c4.metric("亚马逊转账金额 (USD)", f"${transfer_total_usd:,.2f}")
    
    st.markdown("##### 🇨🇳 核心核算基准 (CNY - 含税)")
    c5, c6, c7, c8 = st.columns(4)
    c5.metric("总销售额 (CNY)", f"¥{(gross_sales_usd * exchange_rate):,.2f}")
    c6.metric("产品总成本", f"¥{cost_inc_total:,.2f}")
    c7.metric("退货调整金额", f"¥{recovery_inc_total:,.2f}")
    c8.metric("最终预估纯利", f"¥{profit_inc_total:,.2f}")
    
    if has_exc:
        sku_merged[col_exc] = pd.to_numeric(sku_merged[col_exc], errors='coerce').fillna(0.0)
        cost_exc_total = ((sku_merged['order_qty'] + sku_merged['adj_qty']) * sku_merged[col_exc]).sum()
        recovery_exc_total = (sku_merged['refund_qty'] * sku_merged[col_exc] * rf).sum()
        profit_exc_total = (total_payout_usd * exchange_rate) - cost_exc_total + recovery_exc_total - manual_freight
        st.markdown("##### 🇨🇳 不含税核算基准 (CNY)")
        c9, c10, c11, c12 = st.columns(4)
        c9.metric("总销售额 (CNY)", f"¥{(gross_sales_usd * exchange_rate):,.2f}")
        c10.metric("产品总成本 (不含税)", f"¥{cost_exc_total:,.2f}")
        c11.metric("退货调整金额 (不含税)", f"¥{recovery_exc_total:,.2f}")
        c12.metric("最终预估纯利 (不含税)", f"¥{profit_exc_total:,.2f}")

    st.divider()
    
    # 图表
    col_chart1, col_chart2 = st.columns(2)
    with col_chart1:
        daily_trend = df.groupby(['date', 'type'])['total'].sum().reset_index()
        daily_trend = daily_trend[daily_trend['type'].isin(['Order', 'Refund'])]
        st.plotly_chart(px.bar(daily_trend, x='date', y='total', color='type', title="每日净收入分布 (USD)", color_discrete_map={'Order':'#2ecc71','Refund':'#e74c3c'}), use_container_width=True)
    with col_chart2:
        fee_selling = abs(df['selling fees'].sum()) * exchange_rate
        fee_fba = abs(df['fba fees'].sum()) * exchange_rate
        fee_ad = ad_spend_usd * exchange_rate
        st.plotly_chart(px.pie(names=['佣金','FBA费','广告','产品成本','头程运费','纯利'], values=[fee_selling, fee_fba, fee_ad, cost_inc_total, manual_freight, max(0, profit_inc_total)], title="费用结构去向 (CNY)", hole=0.4), use_container_width=True)

    st.divider()
    
    # --- 💡 核心升级：SKU 级别核心利润明细（精简重构版） ---
    st.markdown("### 📦 SKU 级别核心利润分析明细")
    
    # 计算新版指标
    sku_merged['总销售额(USD)'] = sku_merged['product sales']
    sku_merged['净销量'] = (sku_merged['order_qty'] - sku_merged['refund_qty']).astype(int)
    sku_merged['退货数量'] = sku_merged['refund_qty'].astype(int)
    
    sku_merged['销售总成本'] = ((sku_merged['order_qty'] + sku_merged['adj_qty']) * sku_merged[col_inc]) - (sku_merged['refund_qty'] * sku_merged[col_inc] * rf)
    sku_merged['产品利润-含税(CNY)'] = (sku_merged['total'] * exchange_rate) - sku_merged['销售总成本']
    
    # 安全计算利润率 (防报错处理)
    def calc_margin(row):
        sales_cny = row['总销售额(USD)'] * exchange_rate
        if sales_cny > 0:
            return row['产品利润-含税(CNY)'] / sales_cny
        return 0.0
    sku_merged['产品利润率'] = sku_merged.apply(calc_margin, axis=1)
    
    # 动态组装列名
    cols_to_show = ['sku', col_name, '总销售额(USD)', '净销量', '退货数量', '销售总成本', '产品利润率', '产品利润-含税(CNY)']
    new_col_names = ['SKU', '产品名称', '总销售额(USD)', '净销量', '退货数量', '销售总成本', '产品利润率', '产品利润-含税(CNY)']
    
    format_dict = {
        '总销售额(USD)': '${:,.2f}',
        '销售总成本': '¥{:,.2f}',
        '产品利润-含税(CNY)': '¥{:,.2f}',
        '产品利润率': '{:.1%}'
    }
    
    if has_exc:
        sku_merged['不含税销售总成本'] = ((sku_merged['order_qty'] + sku_merged['adj_qty']) * sku_merged[col_exc]) - (sku_merged['refund_qty'] * sku_merged[col_exc] * rf)
        sku_merged['产品利润-不含税(CNY)'] = (sku_merged['total'] * exchange_rate) - sku_merged['不含税销售总成本']
        cols_to_show.append('产品利润-不含税(CNY)')
        new_col_names.append('产品利润-不含税(CNY)')
        format_dict['产品利润-不含税(CNY)'] = '¥{:,.2f}'

    # 默认按含税纯利从高到低排序
    sku_perf = sku_merged.sort_values('产品利润-含税(CNY)', ascending=False)
    view_df = sku_perf[cols_to_show].copy()
    view_df.columns = new_col_names
    
    # 渲染全新表格
    st.dataframe(view_df.style.format(format_dict), use_container_width=True, height=500)

    # --- 🏆 榜单分析 ---
    st.divider()
    sku_perf['full_label'] = sku_perf['sku'].astype(str) + " | " + sku_perf[col_name].astype(str)
    
    st.markdown("#### 🏆 Top 20 利润榜单")
    st.plotly_chart(px.bar(sku_perf.head(20), x='full_label', y='产品利润-含税(CNY)', text='产品利润-含税(CNY)', color='产品利润-含税(CNY)', color_continuous_scale='Blues', height=600).update_traces(texttemplate='¥%{y:,.0f}', textposition='outside'), use_container_width=True)
    
    st.markdown("#### 🚨 Top 10 低利润/亏损预警")
    st.plotly_chart(px.bar(sku_perf.sort_values('产品利润-含税(CNY)').head(10), x='full_label', y='产品利润-含税(CNY)', text='产品利润-含税(CNY)', color='产品利润-含税(CNY)', color_continuous_scale='Reds_r', height=600).update_traces(texttemplate='¥%{y:,.0f}', textposition='outside'), use_container_width=True)

# --- 审计导出 ---
    with st.sidebar:
        st.divider()
        st.header("4. 审计导出")
        if st.button("🛡️ 生成并核验审计表"):
            audit_df = raw_export_df.copy()
            logic_cols = audit_df.columns.str.lower()
            
            type_idx = logic_cols.get_loc('type')
            sku_idx = logic_cols.get_loc('sku') if 'sku' in logic_cols else -1
            qty_idx = logic_cols.get_loc('quantity') if 'quantity' in logic_cols else logic_cols.get_loc('amount-description')
            total_idx = logic_cols.get_loc('total') if 'total' in logic_cols else -1
            
            temp_type = audit_df.iloc[:, type_idx].astype(str).fillna('')
            temp_sku = audit_df.iloc[:, sku_idx].astype(str).str.upper() if sku_idx != -1 else pd.Series([''] * len(audit_df))
            temp_qty = pd.to_numeric(audit_df.iloc[:, qty_idx], errors='coerce').fillna(0).abs()
            temp_total = pd.to_numeric(audit_df.iloc[:, total_idx].astype(str).str.replace(',',''), errors='coerce').fillna(0)
            
            cost_map = cost_df.set_index('sku')[col_inc].to_dict()
            # 审计表列名动态调整
            audit_cost_name = f'AE_单个成本({col_inc})'
            audit_df[audit_cost_name] = temp_sku.map(cost_map).fillna(0)
            
            is_cost_deducted = temp_type.str.contains('Order|Adjustment', case=False, regex=True)
            audit_df['AF_行总成本'] = 0.0
            audit_df.loc[is_cost_deducted, 'AF_行总成本'] = audit_df.loc[is_cost_deducted, audit_cost_name] * temp_qty[is_cost_deducted]
            
            is_transfer = temp_type.str.contains('Transfer', case=False)
            audit_df['AG_销售金额(CNY)'] = temp_total * exchange_rate
            audit_df.loc[is_transfer, 'AG_销售金额(CNY)'] = 0.0
            
            is_refund = temp_type.str.contains('Refund', case=False)
            audit_df['AI_退货返仓补偿'] = 0.0
            audit_df.loc[is_refund, 'AI_退货返仓补偿'] = audit_df.loc[is_refund, audit_cost_name] * temp_qty[is_refund] * rf
            
            audit_df['AH_行利润'] = audit_df['AG_销售金额(CNY)'] - audit_df['AF_行总成本'] + audit_df['AI_退货返仓补偿']
            
            audit_total_profit = audit_df['AH_行利润'].sum()
            diff = abs(audit_total_profit - profit_inc_total)
            
            if diff <= 0.05:
                st.success(f"✅ **查验通过！**\n逻辑完美匹配。")
                out = BytesIO()
                with pd.ExcelWriter(out, engine='openpyxl') as writer:
                    audit_df.to_excel(writer, index=False)
                st.download_button("💾 下载严密审计表", out.getvalue(), "Audit_Sheet_V9.xlsx")
            else:
                st.error(f"❌ **核验失败拦截！**\n请检查数据源异常！")


