import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import os

st.set_page_config(page_title="BESS Annual Simulator", layout="wide")

st.markdown("""<style>[data-testid='stMetricValue'] { font-size: 2.0rem; color: #58a6ff; } .main-header { font-size: 28px; font-weight: bold; color: #58a6ff; margin-bottom: 20px; }</style>""", unsafe_allow_html=True)

@st.cache_data
def load_data(file_path):
    df = pd.read_csv(file_path)
    df['TimeStamp'] = pd.to_datetime(df['TimeStamp'])
    return df

@st.cache_data
def simulate_annual_recovery(df_values, battery_mwh, battery_mw, one_way_eff, timestamps):
    dt = 1/60
    n = len(df_values)
    solar_pv = df_values[:, 0] # E_Grid (MW)
    curtailment = np.nan_to_num(df_values[:, 1]) # Curtailed Energy
    
    bess_p = np.zeros(n)
    soc_mwh = np.zeros(n)
    final_grid = np.zeros(n)
    curr_soc = 0.0
    
    for i in range(n):
        ts = timestamps[i]
        hour = ts.hour
        # Discharge strictly between 7 PM and 11 PM
        is_discharge_window = 19 <= hour < 23
        
        max_ch_power = 0.0
        if not is_discharge_window:
            charge_room = (battery_mwh - curr_soc) / one_way_eff
            max_ch_power = min(curtailment[i], battery_mw, charge_room / dt)
        
        max_dis_power = 0.0
        if is_discharge_window:
            soc_available_power = (curr_soc * one_way_eff) / dt
            max_dis_power = min(battery_mw, soc_available_power)
        
        p_bess = 0.0
        if max_ch_power > 0:
            p_bess = -max_ch_power
            curr_soc += max_ch_power * dt * one_way_eff
        elif max_dis_power > 0:
            p_bess = max_dis_power
            curr_soc -= (max_dis_power / one_way_eff) * dt
            
        # Reset SOC at exactly midnight as a safeguard
        if hour == 0 and ts.minute == 0: 
            curr_soc = 0.0
            
        bess_p[i] = p_bess
        soc_mwh[i] = curr_soc
        final_grid[i] = solar_pv[i] + (p_bess if p_bess > 0 else 0)
        
    return final_grid, bess_p, soc_mwh

st.markdown('<div class="main-header">🔋 BESS Annual Recovery Simulator</div>', unsafe_allow_html=True)

with st.sidebar:
    st.header("BESS Parameters")
    cap_mwh = st.number_input("Capacity (MWh)", 0.0, 1000.0, 40.0, 1.0)
    p_mw = st.number_input("Power (MW)", 0.0, 1000.0, 20.0, 1.0)
    ow_eff = st.slider("One-Way Efficiency", 0.80, 1.00, 0.96, 0.01)
    st.info("Recovery happens during day. Discharge is active 19:00-23:00 to ensure 0% SOC at start of next day.")

data_path = 'Energy-Working.csv'

if os.path.exists(data_path):
    df = load_data(data_path)
    grid, p, s = simulate_annual_recovery(
        df[['E_Grid (MW)', 'Curtailed Energy']].values, 
        cap_mwh, p_mw, ow_eff, 
        df['TimeStamp'].tolist()
    )
    
    df['BESS_Power_MW'], df['SOC_MWh'], df['Grid_POC_MW'] = p, s, grid
    rec_mwh = (df[df['BESS_Power_MW'] > 0]['BESS_Power_MW'].sum() / 60)
    total_curt_mwh = (df['Curtailed Energy'].sum() / 60)
    
    c1, c2, c3 = st.columns(3)
    c1.metric("Annual Recovered", f"{rec_mwh/1000:.3f} GWh")
    c2.metric("Daily Avg", f"{(rec_mwh/365):.1f} MWh")
    c3.metric("Recovery %", f"{(rec_mwh/total_curt_mwh*100):.1f}%" if total_curt_mwh > 0 else "0%")
    
    st.subheader("Annual Operation Profile")
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df['TimeStamp'], y=df['E_Grid (MW)'], name='Solar PV', line=dict(color='#ff7f0e', width=0.5)))
    fig.add_trace(go.Scatter(x=df['TimeStamp'], y=df['Grid_POC_MW'], name='Grid Export', line=dict(color='#2ca02c', width=0.8)))
    fig.add_trace(go.Scatter(x=df['TimeStamp'], y=df['SOC_MWh'], name='SOC (MWh)', yaxis='y2', line=dict(color='#1f77b4', width=0.5, dash='dot')))
    
    fig.update_layout(
        template="plotly_dark", 
        hovermode="x unified", 
        height=600,
        yaxis=dict(title="Power (MW)"), 
        yaxis2=dict(title="Storage (MWh)", overlaying='y', side='right', showgrid=False),
        legend=dict(orientation="h", y=1.05, x=0.5, xanchor="center")
    )
    st.plotly_chart(fig, use_container_width=True)
    st.download_button("⏬ Export Annual Results", df.to_csv(index=False).encode('utf-8'), "annual_bess_results.csv", "text/csv")
else:
    st.error("Please ensure 'Energy-Working.csv' is uploaded.")
