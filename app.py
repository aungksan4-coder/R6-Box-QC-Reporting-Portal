import requests
import base64
import json
import os
import urllib.parse
from datetime import timedelta
from PIL import Image
import pandas as pd
import plotly.express as px
import streamlit as st

# Directories for persistence
UPLOAD_DIR = "uploaded_photos"
DATA_FILE = "gallery_data.json"

if not os.path.exists(UPLOAD_DIR):
    os.makedirs(UPLOAD_DIR)

def load_gallery_store():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return {"overrides": {}, "deleted": []}
    return {"overrides": {}, "deleted": []}

def save_gallery_store(store):
    with open(DATA_FILE, "w") as f:
        json.dump(store, f, indent=2)

def save_uploaded_file(uploaded_file, key, photo_num):
    if uploaded_file is None:
        return None
    ext = os.path.splitext(uploaded_file.name)[1]
    filename = f"{key}_photo{photo_num}{ext}"
    filepath = os.path.join(UPLOAD_DIR, filename).replace("\\", "/")
    with open(filepath, "wb") as f:
        f.write(uploaded_file.getbuffer())
    return filepath

def save_box_state():
    state_data = {
        "overrides": st.session_state.get("box_gallery_overrides", {}),
        "deleted": list(st.session_state.get("box_deleted_card_keys", set())),
        "max_items": st.session_state.get("box_max_items", 10)
    }
    st.session_state.box_store = state_data
    save_gallery_store(state_data)

st.set_page_config(page_title="Operations Reporting Portal", layout="wide")

# Sheet IDs
KEY_REPORT_SHEET_ID = "1LMyLbXSJOTpZUDCjJp6RrY_6slpEmYnLGH1vPqL-VxY"
BOX_DATA_SHEET_ID = "1CIQgVNrAzm-WiuDPqcUxH59eSq5Oq15_qyts2fcX6A0"

# --- DATA FETCHING (1-minute TTL) ---
@st.cache_data(ttl=300)
def fetch_sheet_tab(sheet_id: str, tab_name: str) -> pd.DataFrame:
    encoded_tab = urllib.parse.quote(tab_name)
    csv_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:csv&sheet={encoded_tab}"
    df = pd.read_csv(csv_url)
    df.columns = df.columns.astype(str).str.strip()
    return df

# --- PERSISTENT DATE PICKER HELPER ---
def get_persistent_date_range(key_prefix: str, min_d, max_d):
    qp = st.query_params
    start_param = qp.get(f"{key_prefix}_start")
    end_param = qp.get(f"{key_prefix}_end")
    
    default_val = (min_d, max_d)
    if start_param and end_param:
        try:
            s = pd.to_datetime(start_param).date()
            e = pd.to_datetime(end_param).date()
            if min_d <= s <= max_d and min_d <= e <= max_d:
                default_val = (s, e)
        except Exception:
            pass

    date_selection = st.sidebar.date_input(
        "Filter Date Range",
        value=default_val,
        min_value=min_d,
        max_value=max_d,
        key=f"{key_prefix}_picker"
    )

    if isinstance(date_selection, (tuple, list)) and len(date_selection) == 2:
        s_d, e_d = date_selection
        st.query_params[f"{key_prefix}_start"] = s_d.strftime("%Y-%m-%d")
        st.query_params[f"{key_prefix}_end"] = e_d.strftime("%Y-%m-%d")
        return s_d, e_d
    elif isinstance(date_selection, (tuple, list)) and len(date_selection) == 1:
        s_d = date_selection[0]
        st.query_params[f"{key_prefix}_start"] = s_d.strftime("%Y-%m-%d")
        st.query_params[f"{key_prefix}_end"] = s_d.strftime("%Y-%m-%d")
        return s_d, s_d

    return min_d, max_d

# --- PERSISTENT SORTING HELPER ---
def sort_table_preserve_gt(df_table, sort_by="Grand Total", ascending=False):
    if df_table.empty or len(df_table) <= 1:
        return df_table

    is_gt = df_table.index == "Grand Total"
    data_rows = df_table[~is_gt].copy()
    gt_rows = df_table[is_gt].copy()

    if sort_by == "Team / Category Name":
        data_rows = data_rows.sort_index(ascending=ascending)
    elif sort_by in data_rows.columns:
        col = data_rows[sort_by]
        if col.dtype == object and col.astype(str).str.endswith('%').any():
            clean_num = col.astype(str).str.rstrip('%').astype(float)
            data_rows = data_rows.iloc[clean_num.argsort(kind='mergesort')]
            if not ascending:
                data_rows = data_rows.iloc[::-1]
        else:
            data_rows = data_rows.sort_values(by=sort_by, ascending=ascending)

    return pd.concat([data_rows, gt_rows])

# --- HELPER PIVOT BUILDERS ---
def build_count_and_pct_pivots(df_subset, index_col, columns_col, id_col, expected_cols=None):
    if df_subset.empty or index_col not in df_subset.columns or columns_col not in df_subset.columns:
        empty_cnt = pd.DataFrame(0, index=["No Data"], columns=(expected_cols or []) + ["Grand Total"])
        empty_pct = pd.DataFrame("0.00%", index=["No Data"], columns=(expected_cols or []) + ["Grand Total"])
        empty_cnt.index.name = index_col
        empty_pct.index.name = index_col
        return empty_cnt, empty_pct

    df_clean = df_subset.copy()
    df_clean[index_col] = df_clean[index_col].astype(str).str.strip()
    df_clean[columns_col] = df_clean[columns_col].astype(str).str.strip().str.title()
    df_clean[id_col] = df_clean[id_col].astype(str).str.strip()

    pivot_cnt = pd.pivot_table(
        df_clean, index=index_col, columns=columns_col, values=id_col, aggfunc="nunique", fill_value=0
    )

    if expected_cols:
        for col in expected_cols:
            if col not in pivot_cnt.columns:
                pivot_cnt[col] = 0
        pivot_cnt = pivot_cnt[expected_cols]

pivot_cnt["Grand Total"] = pivot_cnt.sum(axis=1)
return pivot_cnt

def upload_to_imgbb(uploaded_file):
    API_KEY = "f4e4656821274b2c9b8e99cf27e60276"
    url = "https://api.imgbb.com/1/upload"
    
    # 604800 seconds = exactly 7 days
    payload = {
        "key": API_KEY,
        "image": base64.b64encode(uploaded_file.getvalue()).decode("utf-8"),
        "expiration": 604800 
    }
    
    try:
        response = requests.post(url, data=payload)
        result = response.json()
        
        if result.get("success"):
            return result["data"]["url"]
        else:
            st.error(f"Upload failed: {result['error']['message']}")
            return None
    except Exception as e:
        st.error(f"Error connecting to cloud: {e}")
        return None
    gt_row = pivot_cnt.sum(axis=0)
    gt_row.name = "Grand Total"
    
    cnt_table = pd.concat([pivot_cnt, gt_row.to_frame().T])
    cnt_table.index.name = index_col

    val_cols = [c for c in pivot_cnt.columns if c != "Grand Total"]
    row_totals = pivot_cnt["Grand Total"].replace(0, 1)
    pct_raw = pivot_cnt[val_cols].div(row_totals, axis=0) * 100
    pct_raw["Grand Total"] = 100.0

    overall_total = gt_row["Grand Total"] if gt_row["Grand Total"] > 0 else 1
    gt_pct_row = (gt_row[val_cols] / overall_total) * 100
    gt_pct_row["Grand Total"] = 100.0
    gt_pct_row.name = "Grand Total"

    pct_table = pd.concat([pct_raw, gt_pct_row.to_frame().T])
    pct_table.index.name = index_col
    return cnt_table, pct_table.map(lambda x: f"{x:.2f}%")

def build_fail_category_pivot(df_subset, reason_col, region_col, id_col):
    if df_subset.empty:
        empty = pd.DataFrame(0, index=["No Data"], columns=["MDY", "OC", "Grand Total"])
        empty.index.name = "Fail Reason"
        return empty

    df_clean = df_subset.dropna(subset=[reason_col]).copy()
    df_clean[reason_col] = df_clean[reason_col].astype(str).str.strip()
    df_clean[region_col] = df_clean[region_col].astype(str).str.strip().str.upper()
    df_clean[id_col] = df_clean[id_col].astype(str).str.strip()

    pivot_cnt = pd.pivot_table(
        df_clean, index=reason_col, columns=region_col, values=id_col, aggfunc="nunique", fill_value=0
    )

    for reg in ["MDY", "OC"]:
        if reg not in pivot_cnt.columns:
            pivot_cnt[reg] = 0
    pivot_cnt = pivot_cnt[["MDY", "OC"]]

    pivot_cnt["Grand Total"] = pivot_cnt.sum(axis=1)

    gt_row = pivot_cnt.sum(axis=0)
    gt_row.name = "Grand Total"

    final_table = pd.concat([pivot_cnt, gt_row.to_frame().T])
    final_table.index.name = "Fail Reason"
    return final_table

# --- CHART HELPER FOR FIXED VS NOT FIX (Plotly Dark Style) ---
def render_fixed_not_fix_chart(pivot_df, category_label="City"):
    if pivot_df.empty:
        return None

    plot_data = pivot_df[pivot_df.index != "Grand Total"].reset_index()
    
    status_cols = [c for c in plot_data.columns if c != plot_data.columns[0] and c != "Grand Total"]
    active_cols = [c for c in status_cols if plot_data[c].sum() > 0]
    if not active_cols:
        active_cols = status_cols

    x_col = plot_data.columns[0]
    long_df = plot_data.melt(
        id_vars=[x_col],
        value_vars=active_cols,
        var_name="Fix Status",
        value_name="Count"
    )

    fig = px.bar(
        long_df,
        x=x_col,
        y="Count",
        color="Fix Status",
        barmode="group",
        text="Count",
        title="Fixed vs. City" if len(active_cols) == 1 else "Fixed and not Fix",
        color_discrete_map={"Fixed": "#4285F4", "Not Fix": "#EA4335", "not Fix": "#EA4335"}
    )

    fig.update_traces(textposition="outside", textfont_size=12)
    fig.update_layout(
        xaxis_title=category_label,
        yaxis_title="",
        legend_title_text="",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=20, r=20, t=50, b=40),
        height=380
    )
    return fig

# --- REUSABLE BOX PIVOT & CHART COMPONENT ---
def render_city_status_pivot_and_chart(tab_name, city_col_idx=0, site_code_col_idx=3, fix_status_col_idx=5):
    try:
        df = fetch_sheet_tab(BOX_DATA_SHEET_ID, tab_name)

        if df.empty:
            st.warning(f"No data found in '{tab_name}'.")
            return

        cols = list(df.columns)
        city_col = cols[city_col_idx] if len(cols) > city_col_idx else cols[0]
        site_code_col = cols[site_code_col_idx] if len(cols) > site_code_col_idx else cols[min(2, len(cols)-1)]
        fix_status_col = cols[fix_status_col_idx] if len(cols) > fix_status_col_idx else cols[min(4, len(cols)-1)]

        df_proc = df.dropna(subset=[city_col, fix_status_col]).copy()
        df_proc[city_col] = df_proc[city_col].astype(str).str.strip()
        df_proc[fix_status_col] = df_proc[fix_status_col].astype(str).str.strip()
        df_proc[site_code_col] = df_proc[site_code_col].astype(str).str.strip()

        pivot_df = pd.pivot_table(
            df_proc,
            index=city_col,
            columns=fix_status_col,
            values=site_code_col,
            aggfunc="nunique",
            fill_value=0
        )

        pivot_df["Grand Total"] = pivot_df.sum(axis=1)

        gt_row = pivot_df.sum(axis=0)
        gt_row.name = "Grand Total"
        final_table = pd.concat([pivot_df, gt_row.to_frame().T])

        st.dataframe(final_table, use_container_width=True)

        fig = render_fixed_not_fix_chart(pivot_df, category_label=city_col)
        if fig:
            st.plotly_chart(fig, use_container_width=True)

    except Exception as e:
        st.error(f"Error loading '{tab_name}': {e}")

# --- REUSABLE BRACKET PIVOT & CHART COMPONENT ---
def render_bracket_pivot_and_chart(df_bracket, rootcause_val):
    if df_bracket.empty:
        st.warning("No data available.")
        return

    cols = list(df_bracket.columns)
    city_col = cols[0] if len(cols) > 0 else "City"
    site_code_col = cols[3] if len(cols) > 3 else cols[min(2, len(cols)-1)]
    rootcause_col = cols[4] if len(cols) > 4 else cols[min(3, len(cols)-1)]
    fix_status_col = cols[6] if len(cols) > 6 else cols[min(5, len(cols)-1)]

    df_sub = df_bracket[
        df_bracket[rootcause_col].astype(str).str.strip().str.lower() == rootcause_val.strip().lower()
    ].copy()

    if df_sub.empty:
        st.info(f"No records found for '{rootcause_val}'.")
        return

    df_sub[city_col] = df_sub[city_col].astype(str).str.strip()
    df_sub[fix_status_col] = df_sub[fix_status_col].astype(str).str.strip()
    df_sub[site_code_col] = df_sub[site_code_col].astype(str).str.strip()

    pivot_df = pd.pivot_table(
        df_sub,
        index=city_col,
        columns=fix_status_col,
        values=site_code_col,
        aggfunc="nunique",
        fill_value=0
    )

    col_map = {}
    for c in pivot_df.columns:
        if str(c).strip().lower() == "fixed":
            col_map[c] = "Fixed"
        elif str(c).strip().lower() in ["not fix", "notfix"]:
            col_map[c] = "not Fix"
    pivot_df = pivot_df.rename(columns=col_map)

    for col_name in ["Fixed", "not Fix"]:
        if col_name not in pivot_df.columns:
            pivot_df[col_name] = 0

    pivot_df = pivot_df[["Fixed", "not Fix"]]
    pivot_df["Grand Total"] = pivot_df.sum(axis=1)

    gt_row = pivot_df.sum(axis=0)
    gt_row.name = "Grand Total"
    final_table = pd.concat([pivot_df, gt_row.to_frame().T])

    st.dataframe(final_table, use_container_width=True)

    fig = render_fixed_not_fix_chart(pivot_df, category_label=city_col)
    if fig:
        st.plotly_chart(fig, use_container_width=True)

# --- MAIN NAVIGATION ---
st.sidebar.title("☰ Navigation Menu")

if st.sidebar.button("🔄 Refresh Data Now"):
    st.cache_data.clear()
    st.rerun()

qp = st.query_params
default_page = qp.get("page", "Key Report Data")

selected_page = st.sidebar.selectbox(
    "Select Page",
    ["Key Report Data", "MSOps6 & FiberOps6 Box Data"],
    index=0 if default_page == "Key Report Data" else 1,
    key="page_navigation_selectbox"
)
st.query_params["page"] = selected_page

st.sidebar.markdown("---")

# ==============================================================================
# PAGE 1: KEY REPORT DATA
# ==============================================================================
if selected_page == "Key Report Data":
    category = st.sidebar.radio("Select View Category", ["Key Raw", "Box Raw", "Cross Team Raw"])
    st.sidebar.markdown("---")

    st.sidebar.header("📊 Persistent Sorting")
    default_sort_by = qp.get("sort_by", "Grand Total")
    default_order = qp.get("sort_order", "Descending (High to Low)")

    sort_by_choice = st.sidebar.selectbox(
        "Sort Rows By",
        ["Grand Total", "Team / Category Name", "Pass", "Fail"],
        index=["Grand Total", "Team / Category Name", "Pass", "Fail"].index(default_sort_by) if default_sort_by in ["Grand Total", "Team / Category Name", "Pass", "Fail"] else 0,
        key="sort_by_widget"
    )

    sort_order_choice = st.sidebar.radio(
        "Sort Direction",
        ["Descending (High to Low)", "Ascending (Low to High)"],
        index=0 if default_order == "Descending (High to Low)" else 1,
        key="sort_order_widget"
    )

    is_ascending = (sort_order_choice == "Ascending (Low to High)")
    st.query_params["sort_by"] = sort_by_choice
    st.query_params["sort_order"] = sort_order_choice

    st.sidebar.markdown("---")

    if category == "Key Raw":
        st.sidebar.header("⚙️ Column Mapping (Key Raw)")
        try:
            df_raw = fetch_sheet_tab(KEY_REPORT_SHEET_ID, "Key Raw")
            cols = list(df_raw.columns)

            id_col = st.sidebar.selectbox("Count ID Column (Col C)", cols, index=min(2, len(cols)-1))
            city_col = st.sidebar.selectbox("City Column (Col D)", cols, index=min(3, len(cols)-1))
            team_col = st.sidebar.selectbox("Team Column (Col G)", cols, index=min(6, len(cols)-1))
            status_col = st.sidebar.selectbox("Status Column (Col J)", cols, index=min(9, len(cols)-1))

            date_cols = [c for c in cols if "date" in c.lower() or "time" in c.lower()]
            date_col = st.sidebar.selectbox("Date Column", date_cols if date_cols else cols)

            df_raw[date_col] = pd.to_datetime(df_raw[date_col], errors="coerce")
            valid_dates = df_raw[date_col].dropna()

            if not valid_dates.empty:
                min_d, max_d = valid_dates.min().date(), valid_dates.max().date()
                s_d, e_d = get_persistent_date_range("key_raw", min_d, max_d)
                df_filtered = df_raw[(df_raw[date_col].dt.date >= s_d) & (df_raw[date_col].dt.date <= e_d)]
                date_hdr = f"({s_d.strftime('%d-%b-%Y')} to {e_d.strftime('%d-%b-%Y')})"
            else:
                df_filtered, date_hdr = df_raw, ""

            st.markdown(f"### Key Report Data {date_hdr}")

            df_filtered = df_filtered.copy()
            df_filtered[city_col] = df_filtered[city_col].astype(str).str.strip().str.upper()

            st.markdown("#### **MDY Key QC**")
            mdy_data = df_filtered[df_filtered[city_col] == "MDY"]
            mdy_cnt, mdy_pct = build_count_and_pct_pivots(mdy_data, team_col, status_col, id_col, ["Bypass", "Fail", "Pass"])
            
            mdy_cnt = sort_table_preserve_gt(mdy_cnt, sort_by_choice, is_ascending)
            mdy_pct = sort_table_preserve_gt(mdy_pct, sort_by_choice, is_ascending)

            c1, c2 = st.columns(2)
            with c1: st.dataframe(mdy_cnt, use_container_width=True)
            with c2: st.dataframe(mdy_pct, use_container_width=True)

            st.markdown("---")

            st.markdown("#### **Regional Key QC (MEO,NPW,PAN,TIS)**")
            reg_data = df_filtered[df_filtered[city_col] == "OC"]
            reg_cnt, reg_pct = build_count_and_pct_pivots(reg_data, team_col, status_col, id_col, ["Bypass", "Fail", "Pass"])

            reg_cnt = sort_table_preserve_gt(reg_cnt, sort_by_choice, is_ascending)
            reg_pct = sort_table_preserve_gt(reg_pct, sort_by_choice, is_ascending)

            c3, c4 = st.columns(2)
            with c3: st.dataframe(reg_cnt, use_container_width=True)
            with c4: st.dataframe(reg_pct, use_container_width=True)

        except Exception as e:
            st.error(f"Error loading Key Raw view: {e}")

    elif category == "Box Raw":
        st.sidebar.header("⚙️ Column Mapping (Box Raw)")
        try:
            df_raw = fetch_sheet_tab(KEY_REPORT_SHEET_ID, "Box Raw")
            cols = list(df_raw.columns)

            box_col = st.sidebar.selectbox("Box Name Column (Col C)", cols, index=min(2, len(cols)-1))
            region_col = st.sidebar.selectbox("Region Column (Col E)", cols, index=min(4, len(cols)-1))
            final_status_col = st.sidebar.selectbox("Final Status Column (Col P)", cols, index=min(15, len(cols)-1))
            fail_status_col = st.sidebar.selectbox("Fail Status Column (Col Q)", cols, index=min(16, len(cols)-1))
            fail_reason_col = st.sidebar.selectbox("Fail Reason Column (Col R)", cols, index=min(17, len(cols)-1))

            date_cols = [c for c in cols if "date" in c.lower() or "time" in c.lower()]
            date_col = st.sidebar.selectbox("Date Column", date_cols if date_cols else cols)

            df_raw[date_col] = pd.to_datetime(df_raw[date_col], errors="coerce")
            valid_dates = df_raw[date_col].dropna()

            if not valid_dates.empty:
                min_d, max_d = valid_dates.min().date(), valid_dates.max().date()
                s_d, e_d = get_persistent_date_range("box_raw", min_d, max_d)

                df_filtered = df_raw[(df_raw[date_col].dt.date >= s_d) & (df_raw[date_col].dt.date <= e_d)]
                
                lw_s_d, lw_e_d = s_d - timedelta(days=7), e_d - timedelta(days=7)
                df_last_week = df_raw[(df_raw[date_col].dt.date >= lw_s_d) & (df_raw[date_col].dt.date <= lw_e_d)]
                
                date_hdr = f"({s_d.strftime('%d-%b-%Y')} to {e_d.strftime('%d-%b-%Y')})"
                lw_date_hdr = f"({lw_s_d.strftime('%d-%b-%Y')} to {lw_e_d.strftime('%d-%b-%Y')})"
            else:
                df_filtered = df_raw
                df_last_week = df_raw
                date_hdr, lw_date_hdr = "", ""

            top_col1, top_col2, top_col3 = st.columns([2.5, 2.5, 2])

            with top_col1:
                st.markdown("**R6 Box Touch Pass/ Fail Result**")
                cnt_pf, pct_pf = build_count_and_pct_pivots(df_filtered, region_col, final_status_col, box_col, ["Pass", "Fail"])
                st.dataframe(sort_table_preserve_gt(cnt_pf, sort_by_choice, is_ascending), use_container_width=True)
                st.dataframe(sort_table_preserve_gt(pct_pf, sort_by_choice, is_ascending), use_container_width=True)

            with top_col2:
                st.markdown("**R6 Fail Result ( Take Action and No Take Action)**")
                fail_df = df_filtered[df_filtered[final_status_col].astype(str).str.upper() == "FAIL"]
                cnt_fr, pct_fr = build_count_and_pct_pivots(fail_df, region_col, fail_status_col, box_col, ["No Take Action", "Take Action"])
                st.dataframe(sort_table_preserve_gt(cnt_fr, sort_by_choice, is_ascending), use_container_width=True)
                st.dataframe(sort_table_preserve_gt(pct_fr, sort_by_choice, is_ascending), use_container_width=True)

            with top_col3:
                st.markdown(f"**Box Ops QC (R6 MDY & R6 OC) {date_hdr}**")
                try:
                    summary_df = fetch_sheet_tab(KEY_REPORT_SHEET_ID, "R6 Box QC Summary")
                    
                    if len(summary_df.columns) >= 15:
                        sliced = summary_df.iloc[1:8, 11:15].copy()
                        if sliced.shape[1] == 4:
                            sliced.columns = ["Region", "No", "Yes", "Grand Total"]
                        
                        def clean_number(val):
                            if pd.isna(val) or str(val).strip() == "" or str(val).lower() == "nan":
                                return ""
                            try:
                                f = float(val)
                                return str(int(f)) if f.is_integer() else str(f)
                            except (ValueError, TypeError):
                                return str(val).strip()

                        sliced = sliced.map(clean_number)
                        sliced = sliced[~sliced["Region"].astype(str).str.lower().isin(["region", "", "nan"])].reset_index(drop=True)
                        st.dataframe(sliced, use_container_width=True)
                    else:
                        st.dataframe(summary_df.fillna("").astype(str).head(8), use_container_width=True)
                except Exception:
                    st.info("Loading summary table...")

            st.markdown("---")

            bot_col1, bot_col2 = st.columns(2)

            with bot_col1:
                st.markdown(f"**Fail Category** {date_hdr}")
                fc_df = build_fail_category_pivot(fail_df, fail_reason_col, region_col, box_col)
                st.dataframe(sort_table_preserve_gt(fc_df, sort_by_choice, is_ascending), use_container_width=True)

            with bot_col2:
                st.markdown(f"**Last Week Fail Category** {lw_date_hdr}")
                lw_fail_df = df_last_week[df_last_week[final_status_col].astype(str).str.upper() == "FAIL"]
                lw_fc_df = build_fail_category_pivot(lw_fail_df, fail_reason_col, region_col, box_col)
                st.dataframe(sort_table_preserve_gt(lw_fc_df, sort_by_choice, is_ascending), use_container_width=True)

        except Exception as e:
            st.error(f"Error loading Box Raw view: {e}")

    elif category == "Cross Team Raw":
        st.sidebar.header("⚙️ Column Mapping (Cross Team Raw)")
        try:
            df_raw = fetch_sheet_tab(KEY_REPORT_SHEET_ID, "Cross Team Raw")
            cols = list(df_raw.columns)

            team_col = st.sidebar.selectbox("Team Column (Col C)", cols, index=min(2, len(cols)-1))
            box_req_col = st.sidebar.selectbox("Engineer Request Box (Col D)", cols, index=min(3, len(cols)-1))
            final_status_col = st.sidebar.selectbox("Final Status Column (Col K)", cols, index=min(10, len(cols)-1))
            region_col = st.sidebar.selectbox("Region Column (Col N)", cols, index=min(13, len(cols)-1))
            fail_status_col = st.sidebar.selectbox("Fail Status Column (Col P)", cols, index=min(15, len(cols)-1))

            date_cols = [c for c in cols if "date" in c.lower() or "time" in c.lower()]
            date_col = st.sidebar.selectbox("Date Column", date_cols if date_cols else cols)

            df_raw[date_col] = pd.to_datetime(df_raw[date_col], dayfirst=True, format="mixed", errors="coerce")
            valid_dates = df_raw[date_col].dropna()

            if not valid_dates.empty:
                min_d, max_d = valid_dates.min().date(), valid_dates.max().date()
                s_d, e_d = get_persistent_date_range("cross_team_raw", min_d, max_d)
                df_filtered = df_raw[(df_raw[date_col].dt.date >= s_d) & (df_raw[date_col].dt.date <= e_d)].copy()
                date_hdr = f"({s_d.strftime('%d-%b-%Y')} to {e_d.strftime('%d-%b-%Y')})"
            else:
                df_filtered, date_hdr = df_raw.copy(), ""

            st.markdown(f"### Cross Team Analysis {date_hdr}")

            df_filtered[region_col] = df_filtered[region_col].astype(str).str.strip().str.upper()

            for reg in ["MDY", "OC"]:
                st.markdown(f"### **R6 {reg} DIA/ Fiber Ops/ FT-SBS**")
                reg_df = df_filtered[df_filtered[region_col] == reg]

                col1, col2 = st.columns(2)

                with col1:
                    st.markdown("**Box Touch Pass/ Fail Result**")
                    cnt_pf, pct_pf = build_count_and_pct_pivots(
                        reg_df, team_col, final_status_col, box_req_col, expected_cols=["Pass", "Fail"]
                    )
                    st.dataframe(sort_table_preserve_gt(cnt_pf, sort_by_choice, is_ascending), use_container_width=True)
                    st.dataframe(sort_table_preserve_gt(pct_pf, sort_by_choice, is_ascending), use_container_width=True)

                with col2:
                    st.markdown("**Fail Result ( Take Action and No Take Action)**")
                    fail_only_df = reg_df[reg_df[final_status_col].astype(str).str.strip().str.upper() == "FAIL"]
                    cnt_fr, pct_fr = build_count_and_pct_pivots(
                        fail_only_df, team_col, fail_status_col, box_req_col, expected_cols=["No Take Action", "Take Action"]
                    )
                    st.dataframe(sort_table_preserve_gt(cnt_fr, sort_by_choice, is_ascending), use_container_width=True)
                    st.dataframe(sort_table_preserve_gt(pct_fr, sort_by_choice, is_ascending), use_container_width=True)

                st.markdown("---")

        except Exception as e:
            st.error(f"Error loading Cross Team Raw view: {e}")

# ==============================================================================
# PAGE 2: MSOps6 & FiberOps6 Box Data
# ==============================================================================
elif selected_page == "MSOps6 & FiberOps6 Box Data":
    st.markdown("### 📦 MSOps6 & FiberOps6 Box Data Dashboard")

    view_mode = st.sidebar.radio(
        "Select Box Analysis View",
        [
            "Box Summary",
            "Bracket Summary",
            "📷 Photo Evidence Gallery"
        ]
    )
    st.sidebar.markdown("---")

    # --- VIEW 1: COMBINED BOX SUMMARY ---
    if view_mode == "Box Summary":
        
        # ROW 1: Clean Box Inside vs. Maintain Box
        r1_col1, r1_col2 = st.columns(2)

        with r1_col1:
            st.markdown("### 🩵 Need to Clean Box Inside")
            try:
                df_clean = fetch_sheet_tab(BOX_DATA_SHEET_ID, "Need To Clean Box Inside")

                if df_clean.empty:
                    st.warning("No data found in 'Need To Clean Box Inside'.")
                else:
                    cols = list(df_clean.columns)
                    city_col = cols[0] if len(cols) > 0 else "City"
                    team_col = cols[1] if len(cols) > 1 and "team" in str(cols[1]).lower() else None
                    site_code_col = cols[3] if len(cols) > 3 else cols[min(2, len(cols)-1)]
                    fix_status_col = cols[5] if len(cols) > 5 else cols[min(4, len(cols)-1)]

                    df_clean_proc = df_clean.dropna(subset=[city_col, fix_status_col]).copy()
                    df_clean_proc[city_col] = df_clean_proc[city_col].astype(str).str.strip()
                    df_clean_proc[fix_status_col] = df_clean_proc[fix_status_col].astype(str).str.strip()
                    df_clean_proc[site_code_col] = df_clean_proc[site_code_col].astype(str).str.strip()

                    index_cols = [team_col, city_col] if team_col and team_col in df_clean_proc.columns else city_col

                    pivot_clean = pd.pivot_table(
                        df_clean_proc,
                        index=index_cols,
                        columns=fix_status_col,
                        values=site_code_col,
                        aggfunc="nunique",
                        fill_value=0
                    )

                    for col_name in ["Fixed", "Not Fix"]:
                        if col_name not in pivot_clean.columns:
                            pivot_clean[col_name] = 0

                    pivot_clean = pivot_clean[["Fixed", "Not Fix"]]
                    pivot_clean["Grand Total"] = pivot_clean.sum(axis=1)

                    gt_row = pivot_clean.sum(axis=0)
                    gt_row.name = "Grand Total"
                    final_clean_table = pd.concat([pivot_clean, gt_row.to_frame().T])

                    st.dataframe(final_clean_table, use_container_width=True)

                    fig_clean = render_fixed_not_fix_chart(pivot_clean, category_label=city_col)
                    if fig_clean:
                        st.plotly_chart(fig_clean, use_container_width=True)

            except Exception as e:
                st.error(f"Error loading 'Need To Clean Box Inside': {e}")

        with r1_col2:
            st.markdown("### 🩷 Need to Maintain Box")
            render_city_status_pivot_and_chart("Need to maintain Box", city_col_idx=0, site_code_col_idx=3, fix_status_col_idx=6)

        st.markdown("---")

        # ROW 2: Install Pencil Kit Holder vs. Install Cable Holder
        r2_col1, r2_col2 = st.columns(2)

        with r2_col1:
            st.markdown("### 💛 Need To Install Pencil Kit Holder")
            render_city_status_pivot_and_chart("Need To Install Pencil Kit Holder", city_col_idx=0, site_code_col_idx=3, fix_status_col_idx=5)

        with r2_col2:
            st.markdown("### 💚 Need To Install Cable Holder")
            render_city_status_pivot_and_chart("Need To Install Cable Holder", city_col_idx=0, site_code_col_idx=3, fix_status_col_idx=5)

        st.markdown("---")

        # ROW 3: Fix Pencil Kit Holder vs. Fix Cable Holder
        r3_col1, r3_col2 = st.columns(2)

        with r3_col1:
            st.markdown("### 🩵 Need To Fix Pencil Kit Holder")
            render_city_status_pivot_and_chart("Need To Fix Pencil Kit Holder", city_col_idx=0, site_code_col_idx=3, fix_status_col_idx=5)

        with r3_col2:
            st.markdown("### 💙 Need To Fix Cable Holder")
            render_city_status_pivot_and_chart("Need To Fix Cable Holder", city_col_idx=0, site_code_col_idx=3, fix_status_col_idx=5)

    # --- VIEW 2: BRACKET SUMMARY ---
    elif view_mode == "Bracket Summary":
        st.markdown("### 🛠️ Bracket Summary Analysis")

        try:
            df_bracket_raw = fetch_sheet_tab(BOX_DATA_SHEET_ID, "Bracket Issue")

            if df_bracket_raw.empty:
                st.warning("No data found in 'Bracket Issue' tab.")
            else:
                b1_col1, b1_col2 = st.columns(2)

                with b1_col1:
                    st.markdown("### 🩵 Bracket full")
                    render_bracket_pivot_and_chart(df_bracket_raw, "Bracket full")

                with b1_col2:
                    st.markdown("### 💚 Bracket lost")
                    render_bracket_pivot_and_chart(df_bracket_raw, "Bracket lost")

                st.markdown("---")

                b2_col1, b2_col2 = st.columns(2)

                with b2_col1:
                    st.markdown("### 💛 Bracket damage")
                    render_bracket_pivot_and_chart(df_bracket_raw, "Bracket damage")

                with b2_col2:
                    st.markdown("### 🩷 Need to install Bracket")
                    render_bracket_pivot_and_chart(df_bracket_raw, "Need to install Bracket")

        except Exception as e:
            st.error(f"Error loading 'Bracket Issue': {e}")

    # --- VIEW 3: PHOTO EVIDENCE GALLERY (FOR BOX DATA PAGE) ---
    elif view_mode == "📷 Photo Evidence Gallery":
        st.markdown("### 📷 MSOps6 & FiberOps6 Photo Inspection Gallery")

        if "box_store" not in st.session_state:
            st.session_state.box_store = load_gallery_store()

        # Re-hydrate values if Streamlit pruned them when switching tabs
        if "box_gallery_overrides" not in st.session_state:
            st.session_state.box_gallery_overrides = st.session_state.box_store.get("overrides", {})
        if "box_deleted_card_keys" not in st.session_state:
            st.session_state.box_deleted_card_keys = set(st.session_state.box_store.get("deleted", []))
        if "box_max_items" not in st.session_state:
            st.session_state.box_max_items = st.session_state.box_store.get("max_items", 10)
        if "box_custom_card_counter" not in st.session_state:
            st.session_state.box_custom_card_counter = 0

        # Sidebar controls for Box Data sheet selection
        st.sidebar.header("⚙️ Data Source & Mapping (Box Gallery)")
        box_tabs = [
            "Need To Clean Box Inside", 
            "Need to maintain Box", 
            "Need To Install Pencil Kit Holder", 
            "Need To Install Cable Holder", 
            "Bracket Issue"
        ]
        selected_tab = st.sidebar.selectbox("Select Sheet Tab", box_tabs)

        try:
            df_raw = fetch_sheet_tab(BOX_DATA_SHEET_ID, selected_tab)
            cols = list(df_raw.columns)

            box_col = st.sidebar.selectbox("Box/Site ID Column", cols, index=min(3, len(cols)-1))
            ticket_col = st.sidebar.selectbox("Ticket Column (Optional)", [None] + cols, index=0)
            region_col = st.sidebar.selectbox("City/Region Column", cols, index=0)
            action_col = st.sidebar.selectbox("Action Status Column", cols, index=min(5, len(cols)-1))
            maint_col = st.sidebar.selectbox("Maintenance Status Column", cols, index=min(4, len(cols)-1))
            
            img_cols = [c for c in cols if any(k in c.lower() for k in ["photo", "img", "image", "url", "link", "picture"])]
            img1_col = st.sidebar.selectbox("Photo 1 URL Column", img_cols if img_cols else cols, index=0 if img_cols else min(len(cols)-2, len(cols)-1))
            img2_col = st.sidebar.selectbox("Photo 2 URL Column", img_cols if img_cols else cols, index=min(1, len(img_cols)-1) if len(img_cols) > 1 else min(len(cols)-1, len(cols)-1))

            # Display Controls
            def sync_max_items():
                save_box_state()

            # Display Controls
            ctrl_col1, ctrl_col2 = st.columns([3, 1])
            with ctrl_col1:
                max_items = st.slider(
                    "Max items to display",
                    min_value=1,
                    max_value=50,
                    key="box_max_items",
                    on_change=sync_max_items
                )
            with ctrl_col2:
                st.markdown("<br>", unsafe_allow_html=True)
                if st.button("➕ Add Blank Card", key="add_box_blank_card", use_container_width=True):
                    st.session_state.box_custom_card_counter += 1
                    new_key = f"box_custom_card_{st.session_state.box_custom_card_counter}"
                    st.session_state.box_gallery_overrides[new_key] = {
                        "date_hdr": "Date - 24-Aug-26 (MDY)",
                        "tkt_id": "",
                        "box_id": "CA2-UKNO91ZCNM-G03",
                        "action": "Not Fix",
                        "maint": selected_tab,
                        "img1": None,
                        "img2": None
                    }
                    st.rerun()

            cards_to_render = []

            # 1. Custom user-added cards
            for key, override_data in st.session_state.box_gallery_overrides.items():
                if key.startswith("box_custom_card_") and key not in st.session_state.box_deleted_card_keys:
                    cards_to_render.append((key, override_data))

            # 2. Sheet records up to max_items
            sheet_count = 0
            for idx, row in df_raw.iterrows():
                key = f"box_sheet_card_{selected_tab}_{idx}"
                if key in st.session_state.box_deleted_card_keys:
                    continue
                if sheet_count >= max_items:
                    break
                sheet_count += 1

                reg_str = str(row[region_col]).strip() if pd.notna(row[region_col]) else 'MDY'
                box_id_val = str(row[box_col]).strip() if pd.notna(row[box_col]) else 'CA2-041Y12ZMYM-H07'
                tkt_id_val = str(row[ticket_col]).strip() if ticket_col and pd.notna(row[ticket_col]) and str(row[ticket_col]).strip() != 'nan' else ''
                action_val = str(row[action_col]).strip() if pd.notna(row[action_col]) and str(row[action_col]).strip() != 'nan' else 'Not Fix'
                maint_val = str(row[maint_col]).strip() if pd.notna(row[maint_col]) and str(row[maint_col]).strip() != 'nan' else selected_tab

                u1 = str(row[img1_col]).strip() if pd.notna(row[img1_col]) and str(row[img1_col]).startswith('http') else None
                u2 = str(row[img2_col]).strip() if pd.notna(row[img2_col]) and str(row[img2_col]).startswith('http') else None

                default_card_data = {
                    "date_hdr": f"Date - 24-Aug-26 ({reg_str})",
                    "tkt_id": tkt_id_val,
                    "box_id": box_id_val,
                    "action": action_val,
                    "maint": maint_val,
                    "img1": u1,
                    "img2": u2
                }

                saved_override = st.session_state.box_gallery_overrides.get(key, {})
                merged_data = {**default_card_data, **saved_override}
                cards_to_render.append((key, merged_data))

            # Render Cards
            for card_idx, (card_key, card_data) in enumerate(cards_to_render, start=1):
                st.markdown("---")

                # Top Row: Stacked Vertical Editable Text Fields + Delete Button
                txt_col, del_col = st.columns([5, 1])

                with del_col:
                    if st.button("🗑️ Delete Card", key=f"del_box_{card_key}", use_container_width=True):
                        st.session_state.box_deleted_card_keys.add(card_key)
                        if card_key in st.session_state.box_gallery_overrides:
                            del st.session_state.box_gallery_overrides[card_key]
                        st.rerun()

                with txt_col:
                    val_hdr = st.text_input("Date Header", value=card_data["date_hdr"], key=f"hdr_box_{card_key}", label_visibility="collapsed")
                    val_tkt = st.text_input("Ticket ID", value=card_data["tkt_id"], key=f"tkt_box_{card_key}", label_visibility="collapsed", placeholder="Ticket ID (Optional)")
                    val_box = st.text_input("Box Code", value=card_data["box_id"], key=f"box_code_{card_key}", label_visibility="collapsed")
                    val_act = st.text_input("Action Status", value=card_data["action"], key=f"act_box_{card_key}", label_visibility="collapsed")
                    val_mnt = st.text_input("Maintenance Status", value=card_data["maint"], key=f"mnt_box_{card_key}", label_visibility="collapsed")

                # Persist text changes
                if card_key not in st.session_state.box_gallery_overrides:
                    st.session_state.box_gallery_overrides[card_key] = {}
                
                st.session_state.box_gallery_overrides[card_key].update({
                    "date_hdr": val_hdr,
                    "tkt_id": val_tkt,
                    "box_id": val_box,
                    "action": val_act,
                    "maint": val_mnt,
                })
                
                if "img1" not in st.session_state.box_gallery_overrides[card_key]:
                    st.session_state.box_gallery_overrides[card_key]["img1"] = card_data.get("img1")
                if "img2" not in st.session_state.box_gallery_overrides[card_key]:
                    st.session_state.box_gallery_overrides[card_key]["img2"] = card_data.get("img2")
                
                save_box_state()
                
                # Save changes to JSON on disk
                save_gallery_store({"overrides": st.session_state.box_gallery_overrides, "deleted": list(st.session_state.box_deleted_card_keys)})
                
                # Preserve existing uploads/deletions if already present
                if "img1" not in st.session_state.box_gallery_overrides[card_key]:
                    st.session_state.box_gallery_overrides[card_key]["img1"] = card_data.get("img1")
                if "img2" not in st.session_state.box_gallery_overrides[card_key]:
                    st.session_state.box_gallery_overrides[card_key]["img2"] = card_data.get("img2")

                # Side-by-Side Photos Below Text
                p_col1, p_col2 = st.columns(2)

                with p_col1:
                    img1_val = st.session_state.box_gallery_overrides[card_key].get("img1")
                    if img1_val:
                        st.image(img1_val, use_container_width=True)
                        if st.button("❌ Remove Photo 1", key=f"rm1_box_{card_key}"):
                            st.session_state.box_gallery_overrides[card_key]["img1"] = None
                            save_box_state()
                            st.rerun()
                            else:
                        up_img1 = st.file_uploader("Upload Left Photo", type=["png", "jpg", "jpeg"], key=f"up1_box_{card_key}", label_visibility="collapsed")
                        
                        if up_img1 is not None:
                            cloud_url = upload_to_imgbb(up_img1)
                            
                            if cloud_url:
                                st.session_state.box_gallery_overrides[card_key]["img1"] = cloud_url
                                save_box_state()
                                save_gallery_store({"overrides": st.session_state.box_gallery_overrides, "deleted": list(st.session_state.box_deleted_card_keys)})
                                st.rerun()

                with p_col2:
                    img2_val = st.session_state.box_gallery_overrides[card_key].get("img2")
                    if img2_val:
                        st.image(img2_val, use_container_width=True)
                        if st.button("❌ Remove Photo 2", key=f"rm2_box_{card_key}"):
                            st.session_state.box_gallery_overrides[card_key]["img2"] = None
                            save_box_state()
                            st.rerun()
                    else:
                up_img2 = st.file_uploader("Upload Right Photo", type=["png", "jpg", "jpeg"], key=f"up2_box_{card_key}", label_visibility="collapsed")
                if up_img2 is not None:
                    with st.spinner("Uploading to cloud..."):
                        cloud_url = upload_to_imgbb(up_img2)
                        if cloud_url:
                            st.session_state.box_gallery_overrides[card_key]["img2"] = cloud_url
                            
                            # Note: Your save_gallery_store() needs to push to Google Sheets eventually!
                            save_gallery_store({"overrides": st.session_state.box_gallery_overrides, "deleted": list(st.session_state.box_deleted_card_keys)})
                            st.rerun()

        except Exception as e:
            st.error(f"Error loading Box Data Photo Gallery: {e}")
