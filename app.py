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
                            saved_path = save_uploaded_file(up_img1, card_key, 1)
                            st.session_state.box_gallery_overrides[card_key]["img1"] = saved_path
                            save_box_state()
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
                            saved_path = save_uploaded_file(up_img2, card_key, 2)
                            st.session_state.box_gallery_overrides[card_key]["img2"] = saved_path
                            save_box_state()
                            st.rerun()

        except Exception as e:
            st.error(f"Error loading Box Data Photo Gallery: {e}")
