import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import os

st.set_page_config(page_title="BESS Annual Simulator", layout="wide")

# --- Styling ---
st.markdown("""<style>[data-testid='stMetricValue'] { font-size: 1.8rem; color: #58a6ff; } .main-header { font-size: 24px; font-weight: bold; color: #58a6ff; }</style>""", unsafe_allow_html=True)

@st.cache_data
def load_and_preprocess(file_path):
    if file_path.endswith('.xlsx'):
        df = pd.read_excel(file_path)
    else:
        df = pd.read_csv(file_path)
    df['TimeStamp'] = pd.to_datetime(df['TimeStamp'])
    # Ensure required columns exist and are numeric
    for col in ['E_Grid (MW)', 'Curtailed Energy']:
        df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0.0)
    return df

@st.cache_data
def run_sim_vectorized(df, cap_mwh, p_mw, eff):
    dt = 1/60
    n = len(df)
    solar = df['E_Grid (MW)'].values
    curt = df['Curtailed Energy'].values
    hours = df['TimeStamp'].dt.hour.values
    minutes = df['TimeStamp'].dt.minute.values
    
    bess_p = np.zeros(n)
    soc = np.zeros(n)
    safe_eff = max(eff, 0.01)
    curr_soc = 0.0
    
    # Internal loop for state-dependent logic (SOC tracking)
    for i in range(n):
        h = hours[i]
        m = minutes[i]
        
        # Reset at Midnight
        if h == 0 and m == 0: curr_soc = 0.0
        
        is_discharge = 19 <= h < 23
        p = 0.0
        
        if not is_discharge:
            # Charging from curtailed energy
            room = max(0.0, (cap_mwh - curr_soc) / safe_eff)
            p_in = min(curt[i], p_mw, room / dt)
            if p_in > 0:
                p = -p_in
                curr_soc += p_in * dt * safe_eff
        else:
            # Discharging window
            avail = (curr_soc * safe_eff) / dt
            p_out = min(p_mw, avail)
            if p_out > 0:
                p = p_out
                curr_soc -= (p_out / safe_eff) * dt
        
        bess_p[i] = p
        soc[i] = curr_soc

    return bess_p, soc

st.markdown('<div class="main-header">🔋 BESS Energy Recovery: Annual Profile</div>', unsafe_allow_html=True)

with st.sidebar:
    st.header("Simulation Inputs")
    cap = st.number_input("Battery Capacity (MWh)", 0.0, 2000.0, 40.0)
    pwr = st.number_input("Battery Power (MW)", 0.0, 1000.0, 20.0)
    eff = st.slider("One-Way Efficiency", 0.70, 1.00, 0.96)

# Check for files in order of preference
input_file = 'Energy-Working.csv' if os.path.exists('Energy-Working.csv') else 'Energy-Working.xlsx'

if os.path.exists(input_file):
    data = load_and_preprocess(input_file)
    bp, sc = run_sim_vectorized(data, cap, pwr, eff)
    
    data['BESS_MW'] = bp
    data['SOC_MWh'] = sc
    data['Final_Grid_MW'] = data['E_Grid (MW)'] + np.where(bp > 0, bp, 0)
    
    # Metrics
    recovered = (data[data['BESS_MW'] > 0]['BESS_MW'].sum() / 60) / 1000 # GWh
    
    col1, col2 = st.columns(2)
    col1.metric("Annual Energy Recovered", f"{recovered:.3f} GWh")
    col2.metric("Operational Window", "19:00 - 23:00")

    # Chart
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=data['TimeStamp'], y=data['E_Grid (MW)'], name="Solar (Original)", line=dict(color='gray', width=1)))
    fig.add_trace(go.Scatter(x=data['TimeStamp'], y=data['Final_Grid_MW'], name="Grid + BESS", line=dict(color='#2ca02c', width=1.2)))
    fig.add_trace(go.Scatter(x=data['TimeStamp'], y=data['SOC_MWh'], name="BESS SOC", yaxis="y2", line=dict(color='#00d4ff', width=1, dash='dot')))
    
    fig.update_layout(
        template="plotly_dark", height=600,
        yaxis=dict(title="Power (MW)"),
        yaxis2=dict(title="SOC (MWh)", overlaying="y", side="right", showgrid=False),
        legend=dict(orientation="h", y=1.1)
    )
    st.plotly_chart(fig, use_container_width=True)
    st.download_button("Download CSV", data.to_csv(index=False).encode('utf-8'), "bess_annual_results.csv")
else:
    st.warning("Please ensure 'Energy-Working.csv' or '.xlsx' is present in the directory.")
