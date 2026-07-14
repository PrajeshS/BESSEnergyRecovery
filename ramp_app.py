import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import os

st.set_page_config(page_title='BESS Energy Recovery Simulator', layout='wide')

# --- Professional CSS ---
st.markdown("""
    <style>
    [data-testid='stMetricValue'] { font-size: 2.0rem; color: #58a6ff; }
    .main-header { font-size: 28px; font-weight: bold; color: #58a6ff; margin-bottom: 20px; }
    .stButton>button { width: 100%; border-radius: 5px; height: 3em; background-color: #238636; color: white; }
    </style>
""", unsafe_allow_html=True)

def simulate_energy_recovery(df, battery_mwh, battery_mw, one_way_eff=0.96, ramp_limit=3.0, grid_cap=100.0):
    dt = 1/60
    n = len(df)
    solar_pv = df['E_Grid (MW)'].values
    curtailment = df['Curtailed Energy'].fillna(0).values

    bess_p = np.zeros(n)
    soc_mwh = np.zeros(n)
    final_grid = np.zeros(n)
    curr_soc = 0.0
    prev_poc = solar_pv[0]

    for i in range(n):
        charge_room = (battery_mwh - curr_soc) / one_way_eff
        max_ch_power = min(curtailment[i], battery_mw, charge_room / dt)

        room_at_poc = max(0, grid_cap - solar_pv[i])
        ramp_room_at_poc = max(0, (prev_poc + ramp_limit) - solar_pv[i])
        soc_power_at_poc = (curr_soc * one_way_eff) / dt
        max_dis_power_at_poc = min(battery_mw, room_at_poc, ramp_room_at_poc, soc_power_at_poc)

        p_bess = 0.0
        if max_ch_power > 0:
            p_bess = -max_ch_power
            curr_soc += max_ch_power * dt * one_way_eff
        elif max_dis_power_at_poc > 0:
            p_bess = max_dis_power_at_poc
            curr_soc -= (max_dis_power_at_poc / one_way_eff) * dt

        bess_p[i] = p_bess
        soc_mwh[i] = curr_soc
        final_grid[i] = solar_pv[i] + (p_bess if p_bess > 0 else 0)
        prev_poc = final_grid[i]

    return final_grid, bess_p, soc_mwh

st.markdown('<div class="main-header">🔋 BESS Energy Recovery Simulator</div>', unsafe_allow_html=True)

with st.sidebar:
    st.header("BESS Configuration")
    cap_mwh = st.number_input("BESS Capacity (MWh)", value=40.0, step=1.0)
    p_mw = st.number_input("BESS Power (MW)", value=20.0, step=1.0)
    ow_eff = st.slider("One-Way Efficiency", 0.80, 1.00, 0.96, 0.01)
    grid_limit = st.number_input("Grid Export Limit (MW)", value=100.0)
    st.divider()
    
    # Default path for GitHub deployment
    default_path = 'Energy-Working.xlsx'
    uploaded_file = st.file_uploader("Upload New Data (Optional)", type=['xlsx'])

# Logic to select data source
data_source = None
if uploaded_file is not None:
    data_source = uploaded_file
elif os.path.exists(default_path):
    data_source = default_path
    st.sidebar.info("✅ Using default data from repository.")
else:
    st.sidebar.warning("⚠️ Please upload an Excel file to begin.")

if data_source:
    df = pd.read_excel(data_source)
    if st.button("⚡ Run Simulation"):
        grid, p, s = simulate_energy_recovery(df, cap_mwh, p_mw, ow_eff, grid_cap=grid_limit)
        df['BESS_Power_MW'] = p
        df['SOC_MWh'] = s
        df['Grid_POC_MW'] = grid

        rec_mwh = (df[df['BESS_Power_MW'] > 0]['BESS_Power_MW'].sum() / 60)
        total_curt_mwh = (df['Curtailed Energy'].sum() / 60)

        cols = st.columns(4)
        cols[0].metric("Energy Recovered", f"{rec_mwh/1000:.3f} GWh")
        cols[1].metric("Recovery Ratio", f"{(rec_mwh/total_curt_mwh*100):.1f}%" if total_curt_mwh > 0 else "0%")
        cols[2].metric("Annual Cycles", f"{(rec_mwh/cap_mwh):.1f}")
        cols[3].metric("Efficiency Status", f"{ow_eff*100:.0f}% One-Way")

        st.subheader("Weekly Performance Trend")
        sample = df.head(10080)
        fig = go.Figure()
        fig.add_trace(go.Scatter(y=sample['E_Grid (MW)'], name='Solar (Clipped)', line=dict(color='#ff7f0e', width=1)))
        fig.add_trace(go.Scatter(y=sample['Grid_POC_MW'], name='Final POC Output', line=dict(color='#2ca02c', width=1.5)))
        fig.add_trace(go.Scatter(y=sample['SOC_MWh'], name='BESS SOC (MWh)', yaxis='y2', line=dict(color='#1f77b4', dash='dot')))

        fig.update_layout(
            template="plotly_dark", hovermode="x unified",
            yaxis=dict(title="Power (MW)"),
            yaxis2=dict(title="Stored Energy (MWh)", overlaying='y', side='right', showgrid=False),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="center", x=0.5)
        )
        st.plotly_chart(fig, use_container_width=True)
        st.download_button("📥 Download Results", df.to_csv(index=False).encode('utf-8'), "bess_results.csv", "text/csv")
