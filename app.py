# --- VIEW: BOX ISSUE WEEKLY FIXED & BACKLOG ---
    elif view_mode == "Box Issue Weekly Fixed & Backlog":
        st.markdown("### Box Issue Weekly Fixed & Backlog")
        
        try:
            # Main Summary Tab မှ Data ဆွဲယူခြင်း
            df_main = fetch_sheet_tab(BOX_DATA_SHEET_ID, "Main Summary")
            
            # Column A (Index 0) နှင့် F မှ I (Index 5,6,7,8) ကို Row 2 မှ 9 (Index 0 မှ 7) အထိ ဖြတ်ယူခြင်း
            df_target = df_main.iloc[0:8, [0, 5, 6, 7, 8]].copy()
            
            # Chart အတွက် Header နာမည်များ သတ်မှတ်ခြင်း
            df_target.columns = ["Rootcause", "1st Week", "2nd Week", "3rd Week", "4th Week"]
            
            # (၁) Rootcause နေရာတွင် NaN ဖြစ်နေသော အပို Row များကို ဖျက်ရန် (ပုံထဲမှ အောက်ဆုံး Row အလွတ်ကို ဖျောက်ရန်)
            df_target = df_target.dropna(subset=["Rootcause"])
            
            # (၂) Data မရှိသော နေရာများ (NaN) ကို 0 ဖြင့် အစားထိုးရန် နှင့် Point (.0) များဖျောက်ရန် Integer ပြောင်းရန်
            week_cols = ["1st Week", "2nd Week", "3rd Week", "4th Week"]
            for col in week_cols:
                df_target[col] = pd.to_numeric(df_target[col], errors="coerce").fillna(0).astype(int)
            
            # ဇယား (Table) ကို အရင်ပြသခြင်း (ဒီဇယားမှာ Total အထိ ပါပါမယ်)
            st.dataframe(df_target, use_container_width=True)
            
            st.markdown("---")
            
            # (၃) Chart တွင် "Total" Bar မပြစေရန် 'Total' Row ကို ဖယ်ထုတ်ခြင်း 
            # (တခြား "Box No Cover Total" စသည်တို့ မပါသွားစေရန် Exact match သုံးထားပါသည်)
            df_chart = df_target[df_target["Rootcause"].astype(str).str.strip().str.lower() != "total"]
            
            # Chart အတွက် Data ကို Long Format (Melt) ပြောင်းခြင်း
            df_melted = df_chart.melt(
                id_vars=["Rootcause"],
                value_vars=week_cols,
                var_name="Week",
                value_name="Count"
            )
            
            # Plotly Grouped Bar Chart ဆွဲခြင်း
            fig = px.bar(
                df_melted,
                x="Rootcause",
                y="Count",
                color="Week",
                barmode="group",
                text="Count",
                title="Box Issues Weekly Fixed Report",
                # ပုံ (၃) မှ အရောင်များအတိုင်း သတ်မှတ်ခြင်း
                color_discrete_map={
                    "1st Week": "#4285F4", 
                    "2nd Week": "#EA4335", 
                    "3rd Week": "#FBBC04", 
                    "4th Week": "#34A853"
                }
            )
            
            # Chart Design ပြင်ဆင်ခြင်း
            fig.update_traces(textposition="outside", textfont_size=12)
            fig.update_layout(
                xaxis_title="Rootcause",
                yaxis_title="",
                legend_title_text="",
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                margin=dict(l=20, r=20, t=50, b=40),
                height=450
            )
            
            # Chart ကို Web ပေါ်တင်ခြင်း
            st.plotly_chart(fig, use_container_width=True)
            
        except Exception as e:
            st.error(f"Error loading 'Main Summary' data: {e}")
