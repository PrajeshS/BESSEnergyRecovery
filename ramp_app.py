import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import os

st.set_page_config(page_title="BESS Annual Simulator", layout="wide")

st.markdown("""<style>[data-testid='stMetricValue'] { font-size: 1.8rem; color: #58a6ff; } .main-header { font-size: 24px; font-weight: bold; color: #58a6ff; }</style>""", unsafe_allow_html=True)

@st.cache_data
def load_and_preprocess(file_path):
    if file_path.endswith('.xlsx'):
        df = pd.read_excel(file_path)
    else:
        df = pd.read_csv(file_path)
    
    # 1. Force TimeStamp to datetime and drop rows that fail (strips the GWh totals at the end)
    df['TimeStamp'] = pd.to_datetime(df['TimeStamp'], errors='coerce')
    df = df.dropna(subset=['TimeStamp'])
    
    # 2. Ensure target columns are strictly numeric
    for col in ['E_Grid (MW)', 'Curtailed Energy']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0.0)
        else:
            df[col] = 0.0
            
    # 3. Filter out any rows with valid dates but zero/invalid energy that might be summary artifacts
    df = df[df['TimeStamp'].dt.year >= 1990]
    
    return df.sort_values('TimeStamp').reset_index(drop=True)

@st.cache_data
def run_sim_vectorized(df, cap_mwh, p_mw, eff):
    dt = 1/60
    n = len(df)
    curt = df['Curtailed Energy'].values
    hours = df['TimeStamp'].dt.hour.values
    minutes = df['TimeStamp'].dt.minute.values
    
    bess_p = np.zeros(n)
    soc = np.zeros(n)
    safe_eff = max(eff, 0.01)
    curr_soc = 0.0
    
    for i in range(n):
        h = hours[i]
        m = minutes[i]
        
        # Reset at Midnight (00:00) per philosophy
        if h == 0 and m == 0: curr_soc = 0.0
        
        is_discharge = 19 <= h < 23
        
        if not is_discharge:
            # Charge Logic: Recover curtailed energy
            room_mwh = max(0.0, cap_mwh - curr_soc)
            p_in = min(curt[i], p_mw, (room_mwh / safe_eff) / dt)
            if p_in > 0:
                bess_p[i] = -p_in
                curr_soc += p_in * dt * safe_eff
        else:
            # Discharge Logic: 7 PM - 11 PM
            avail_mwh = curr_soc * safe_eff
            p_out = min(p_mw, avail_mwh / dt)
            if p_out > 0:
                bess_p[i] = p_out
                curr_soc -= (p_out / safe_eff) * dt
        
        soc[i] = curr_soc

    return bess_p, soc

st.markdown('<div class="main-header">🔋 BESS Energy Recovery: Annual Profile</div>', unsafe_allow_html=True)

with st.sidebar:
    st.header("⚙️ Physical & Simulation Parameters")
    pwr = st.number_input("BESS Power (MW)", 0, 2000, 20)
    cap = st.number_input("BESS Capacity (MWh)", 0, 5000, 40)
    eff = st.number_input("One-Way Efficiency", 0.70, 1.00, 0.96)

input_file = '/content/Energy-Working.xlsx' if os.path.exists('/content/Energy-Working.xlsx') else 'Energy-Working.csv'

if os.path.exists(input_file):
    data = load_and_preprocess(input_file)
    bp, sc = run_sim_vectorized(data, cap, pwr, eff)
    
    data['BESS_MW'] = bp
    data['SOC_MWh'] = sc
    data['SOC_%'] = (data['SOC_MWh'] / cap) * 100 if cap > 0 else 0
    data['Final_Grid_MW'] = data['E_Grid (MW)'] + np.where(bp > 0, bp, 0)
    
    recovered_gwh = (data[data['BESS_MW'] > 0]['BESS_MW'].sum() / 60) / 1000
    
    c1, c2, c3 = st.columns(3)
    c1.metric("Annual Recovered", f"{recovered_gwh:.3f} GWh")
    c2.metric("Peak SOC", f"{data['SOC_%'].max():.1f}%")
    c3.metric("Daily Cycles", "365")

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=data['TimeStamp'], y=data['Final_Grid_MW'], name="Grid Export", line=dict(color='#2ca02c', width=1)))
    fig.add_trace(go.Scatter(x=data['TimeStamp'],y=data['SOC_%'],name="BESS SOC",yaxis="y2",line=dict(color='#00d4ff', width=1.5)))
    
    fig.update_layout(
        template="plotly_dark", height=600, hovermode="x unified",
        yaxis=dict(title="Power (MW)"),
        yaxis2=dict(title="SOC (%)",range=[0, 100],overlaying="y",side="right",showgrid=False),
        legend=dict(orientation="h", y=1.1)
    )
    st.plotly_chart(fig, use_container_width=True)
    st.download_button("Download Annual Results", data.to_csv(index=False).encode('utf-8'), "bess_recovery_report.csv")
else:
    st.error("Energy-Working.xlsx not found in directory.")
