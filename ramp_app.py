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
            df[col] = (pd.to_numeric(df[col], errors="coerce").fillna(0.0).astype(np.float32))
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
    
    bess_p = np.zeros(n, dtype=np.float32)
    soc = np.zeros(n, dtype=np.float32)
    safe_eff = max(eff, 0.01)
    # Discharge starts at 19:00
    discharge_start = 19.0
    discharge_duration = cap_mwh / p_mw if p_mw > 0 else 0
    discharge_end = discharge_start + discharge_duration
    discharge_end = min(discharge_end, 24.0)
    curr_soc = 0.0
    charge_limited_capacity = 0
    charge_limited_power = 0
    hours_full = 0
    days_full = set()
    days_empty = set()
    
    for i in range(n):
        h = hours[i]
        m = minutes[i]
        
        # Reset at Midnight (00:00) per philosophy
        if h == 0 and m == 0: curr_soc = 0.0
        
        current_hour = h + m/60
        is_discharge = (discharge_start <= current_hour < discharge_end)
        
        if not is_discharge:
            # Charge Logic: Recover curtailed energy
            room_mwh = max(0.0, cap_mwh - curr_soc)
            # Battery already full
            if room_mwh <= 1e-6 and curt[i] > 0:
                charge_limited_capacity += 1
                hours_full += 1
                days_full.add(df["TimeStamp"].iloc[i].date())
            p_in = min(curt[i], p_mw, (room_mwh / safe_eff) / dt)
            # Curtailment exceeds battery power rating
            if curt[i] > p_mw:
                charge_limited_power += 1
            if p_in > 0:
                bess_p[i] = -p_in
                curr_soc += p_in * dt * safe_eff
        else:
            # Discharge Logic: starts at 7 PM, duration = Energy / Power
            avail_mwh = curr_soc * safe_eff
            p_out = min(p_mw, avail_mwh / dt)
            if p_out > 0:
                bess_p[i] = p_out
                curr_soc -= (p_out / safe_eff) * dt
        
        soc[i] = curr_soc
        # Record days ending empty
        if h == 23 and m == 59 and curr_soc < 1e-3:
            days_empty.add(df["TimeStamp"].iloc[i].date())

    return (
    bess_p,
    soc,
    charge_limited_capacity,
    charge_limited_power,
    hours_full,
    len(days_full),
    len(days_empty),
)

st.markdown('<div class="main-header">🔋 BESS Energy Recovery: Annual Profile</div>', unsafe_allow_html=True)

with st.sidebar:
    st.header("⚙️ Physical & Simulation Parameters")
    pwr = st.number_input("BESS Power (MW)", 0, 2000, 20)
    cap = st.number_input("BESS Capacity (MWh)", 0, 5000, 40)
    eff = st.number_input("One-Way Efficiency", 0.70, 1.00, 0.96)

input_file = '/content/Energy-Working.xlsx' if os.path.exists('/content/Energy-Working.xlsx') else 'Energy-Working.csv'

if os.path.exists(input_file):
    data = load_and_preprocess(input_file)
    (
    bp,
    sc,
    charge_limited_capacity,
    charge_limited_power,
    hours_full,
    days_full,
    days_empty,
) = run_sim_vectorized(data, cap, pwr, eff)
    timestamps = data["TimeStamp"].to_numpy()
    e_grid = data["E_Grid (MW)"].to_numpy()
    modified_grid = data["Modified_E_Grid_v2"].to_numpy()
    #data['BESS_MW'] = bp
    #data['SOC_MWh'] = sc
    #data['SOC_%'] = (data['SOC_MWh'] / cap) * 100 if cap > 0 else 0
    #data['Final_Grid_MW'] = data['E_Grid (MW)'] + np.where(bp > 0, bp, 0)
    e_grid = data["E_Grid (MW)"].to_numpy()
    modified_grid = data["Modified_E_Grid_v2"].to_numpy()
    soc_percent = (sc / cap) * 100
    
    #recovered_gwh = (data[data['BESS_MW'] > 0]['BESS_MW'].sum() / 60) / 1000
    recovered_gwh = (bp[bp > 0].sum() / 60) / 1000
    # Total annual curtailed energy
    curtailed_gwh = (data["Curtailed Energy"].sum() / 60) / 1000
    
    # Recovery %
    recovery_percent = (
        recovered_gwh / curtailed_gwh * 100
        if curtailed_gwh > 0 else 0
    )
    
    # Remaining curtailed energy
    remaining_gwh = curtailed_gwh - recovered_gwh
    
    # Annual throughput
    annual_throughput = (np.abs(bp).sum() / 60) / 1000
    
    # Equivalent full cycles
    equivalent_cycles = (
        (bp[bp > 0].sum() / 60) / cap
        if cap > 0 else 0
    )
    
    # Average SOC
    average_soc = soc_percent.mean()
    
    # Hours battery stayed full
    hours_at_full = hours_full / 60
    
    # Percentage of days battery became full
    days_full_percent = days_full / 365 * 100
    
    # Percentage of days battery finished empty
    days_empty_percent = days_empty / 365 * 100
    
    c1,c2,c3,c4 = st.columns(4)

    c1.metric(
        "Recovered Energy",
        f"{recovered_gwh:.2f} GWh"
    )
    
    c2.metric(
        "Recovery",
        f"{recovery_percent:.1f}%"
    )
    
    c3.metric(
        "Remaining Curtailment",
        f"{remaining_gwh:.2f} GWh"
    )
    
    c4.metric(
        "Equivalent Cycles",
        f"{equivalent_cycles:.0f}/yr"
    )
    c5,c6,c7,c8 = st.columns(4)
    
    c5.metric(
        "Peak SOC",
        f"{soc_percent.max():.1f}%"
    )
    
    c6.metric(
        "Average SOC",
        f"{average_soc:.1f}%"
    )
    
    c7.metric(
        "Annual Throughput",
        f"{annual_throughput:.2f} GWh"
    )
    
    c8.metric(
        "Days SOC Hit 100%",
        f"{days_full_percent:.1f}%"
    )
    c9,c10,c11,c12 = st.columns(4)

    c9.metric(
        "Days Ending Empty",
        f"{days_empty_percent:.1f}%"
    )
    
    c10.metric(
        "Hours at Full SOC",
        f"{hours_at_full:.1f}"
    )
    
    c11.metric(
        "Charge Limited",
        f"{charge_limited_capacity/60:.1f} hrs"
    )
    c12.metric(
    "Power Limited",
    f"{charge_limited_power/60:.1f} hrs"
    )

    fig = go.Figure()
    fig.add_trace(go.Scattergl(
    x=timestamps,
    y=e_grid,
    name="E_Grid",
    line=dict(color="royalblue", width=1)
    ))
    
    fig.add_trace(go.Scattergl(
        x=timestamps,
        y=modified_grid,
        name="Modified_E_Grid_v2",
        line=dict(color="orange", width=1)
    ))
    
    fig.add_trace(go.Scattergl(
        x=timestamps,
        y=bp,
        name="BESS Power",
        line=dict(color="#2ca02c", width=1.2)
    ))
    fig.add_trace(go.Scatter(x=data['TimeStamp'],y=soc_percent,name="BESS SOC",yaxis="y2",line=dict(color='#00d4ff', width=1.5)))
    
    fig.update_layout(
        template="plotly_dark", height=600, hovermode="closest",
        yaxis=dict(title="Power (MW)"),
        yaxis2=dict(title="SOC (%)",range=[0, 100],overlaying="y",side="right",showgrid=False),
        legend=dict(orientation="h", y=1.1)
    )
    st.plotly_chart(fig, use_container_width=True)
else:
    st.error("Energy-Working.xlsx not found in directory.")
