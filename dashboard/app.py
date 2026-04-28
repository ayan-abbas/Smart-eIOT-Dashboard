"""
app.py  –  eiot Dashboard v2
"""

import time
import logging
import threading
import datetime

import streamlit as st
import plotly.graph_objects as go
from streamlit_autorefresh import st_autorefresh

import utils
import scheduler

# ─── LOGGING ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s.%(msecs)03d [%(levelname)s] %(funcName)s – %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("eiot.app")

st.set_page_config(page_title="eIoT Dashboard", layout="wide")
_t_script_start = time.perf_counter()
log.debug("── script rerun started ──")


# ─── POOL WARM-UP ─────────────────────────────────────────────────────────────
@st.cache_resource
def _start_pool_warmup():
    def _warmup():
        t0 = time.perf_counter()
        try:
            conn = utils.get_connection()
            conn.close()
            log.info("Pool warm-up done [%.0f ms]", (time.perf_counter() - t0) * 1000)
        except Exception as e:
            log.error("Pool warm-up failed: %s", e)
    threading.Thread(target=_warmup, daemon=True, name="pool-warmup").start()
    return True

_start_pool_warmup()


# ─── SESSION STATE DEFAULTS ───────────────────────────────────────────────────
_DEFAULTS = {
    "logged_in":        False,
    "username":         None,
    "role":             None,
    "selected_device":  None,
    "auto_refresh":     False,
}
for k, v in _DEFAULTS.items():
    if k not in st.session_state:
        st.session_state[k] = v


# ─── ROLE HELPERS ─────────────────────────────────────────────────────────────
def is_admin()    -> bool: return st.session_state.role == "admin"
def is_operator() -> bool: return st.session_state.role in ("admin", "operator")
def is_viewer()   -> bool: return True


# ─── CACHED DATA ──────────────────────────────────────────────────────────────
@st.cache_data(ttl=30)
def cached_get_devices(username, admin):
    return utils.get_devices(username, is_admin=admin)

@st.cache_data(ttl=30)
def cached_get_latest_power():
    return utils.get_latest_power_usage()

@st.cache_data(ttl=60)
def cached_device_power(deviceid, start_iso, end_iso):
    start = datetime.datetime.fromisoformat(start_iso)
    end   = datetime.datetime.fromisoformat(end_iso)
    return utils.get_device_power_usage(deviceid, start, end)

@st.cache_data(ttl=30)
def cached_get_groups(username, admin):
    return utils.get_groups(username, is_admin=admin)

@st.cache_data(ttl=60)
def cached_group_power(username, groupid, start_iso, end_iso, admin):
    start = datetime.datetime.fromisoformat(start_iso)
    end   = datetime.datetime.fromisoformat(end_iso)
    return utils.get_group_power_usage(username, groupid, start, end, is_admin=admin)

@st.cache_data(ttl=120)
def cached_all_users():
    return utils.get_all_users()


# ─── DATE RANGE SIDEBAR WIDGET ────────────────────────────────────────────────
def render_date_range_selector() -> tuple[datetime.datetime, datetime.datetime]:
    st.sidebar.markdown("---")
    st.sidebar.subheader("📅 Date Range")

    IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
    now = datetime.datetime.now(IST).replace(tzinfo=None)

    preset = st.sidebar.selectbox(
        "Quick range",
        ["Last hour", "Last 6 hours", "Last 24 hours",
         "Last 7 days", "Last 30 days", "Custom"],
        index=4,
        key="date_preset",
    )

    presets = {
        "Last hour":     now - datetime.timedelta(hours=1),
        "Last 6 hours":  now - datetime.timedelta(hours=6),
        "Last 24 hours": now - datetime.timedelta(hours=24),
        "Last 7 days":   now - datetime.timedelta(days=7),
        "Last 30 days":  now - datetime.timedelta(days=30),
    }

    if preset != "Custom":
        start_dt = presets[preset]
        end_dt   = now
    else:
        thirty_ago = (now - datetime.timedelta(days=30)).date()
        today      = now.date()
        start_date = st.sidebar.date_input(
            "From", value=thirty_ago,
            min_value=thirty_ago, max_value=today,
            key="custom_start",
        )
        end_date = st.sidebar.date_input(
            "To", value=today,
            min_value=thirty_ago, max_value=today,
            key="custom_end",
        )
        start_dt = datetime.datetime.combine(start_date, datetime.time.min)
        end_dt   = datetime.datetime.combine(end_date, datetime.time.max)
        if (end_dt - start_dt).total_seconds() < 3600:
            st.sidebar.warning("Range must be at least 1 hour — adjusting.")
            end_dt = start_dt + datetime.timedelta(hours=1)

    st.sidebar.caption(
        f"From: {start_dt.strftime('%Y-%m-%d %H:%M')} IST\n"
        f"To:   {end_dt.strftime('%Y-%m-%d %H:%M')} IST"
    )
    return start_dt, end_dt


# ─── CHART HELPERS ────────────────────────────────────────────────────────────
_CHART_LAYOUT = dict(
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(15,15,25,0.8)",
    font=dict(color="#a0a8c0", family="JetBrains Mono"),
    margin=dict(l=50, r=20, t=45, b=45),
)

def _line_fig(df, x_col, y_col, title="", y_label="Power (W)") -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df[x_col], y=df[y_col],
        mode="lines",
        connectgaps=False,
        line=dict(width=2, color="#00e5ff"),
        fill="tozeroy",
        fillcolor="rgba(0,229,255,0.06)",
        name=y_label,
    ))
    fig.update_layout(
        title=dict(text=title, font=dict(size=14, color="#e0e8ff")),
        xaxis_title="Time",
        yaxis_title=y_label,
        xaxis=dict(gridcolor="rgba(255,255,255,0.05)", linecolor="rgba(255,255,255,0.1)"),
        yaxis=dict(range=[0, 900], gridcolor="rgba(255,255,255,0.05)", linecolor="rgba(255,255,255,0.1)"),
        height=350,
        **_CHART_LAYOUT,
    )
    return fig


def _multi_line_fig(df, x_col, device_cols, title="") -> go.Figure:
    fig = go.Figure()
    colors = ["#00e5ff","#69ff47","#ff6d00","#d500f9","#ffea00",
              "#ff1744","#00e676","#2979ff","#ff9100","#e040fb"]
    for i, col in enumerate(device_cols):
        series = df[col]
        if series.isna().all():
            continue
        fig.add_trace(go.Scatter(
            x=df[x_col], y=series,
            mode="lines",
            connectgaps=False,
            line=dict(width=1.5, color=colors[i % len(colors)]),
            name=f"Dev {col}",
        ))
    fig.update_layout(
        title=dict(text=title, font=dict(size=14, color="#e0e8ff")),
        xaxis_title="Time",
        yaxis_title="Power (W)",
        xaxis=dict(gridcolor="rgba(255,255,255,0.05)", linecolor="rgba(255,255,255,0.1)"),
        yaxis=dict(range=[0, 900], gridcolor="rgba(255,255,255,0.05)", linecolor="rgba(255,255,255,0.1)"),
        legend=dict(orientation="h", y=-0.25, font_size=10),
        height=450,
        **_CHART_LAYOUT,
    )
    return fig


# ─── GLOBAL CSS ───────────────────────────────────────────────────────────────
def _inject_global_css():
    st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;700&family=Syne:wght@500;600;700;800&display=swap');

    html, body, [class*="css"] {
        font-family: 'Syne', sans-serif !important;
    }

    /* Main background */
    .stApp {
        background: #080810 !important;
    }

    /* Sidebar */
    section[data-testid="stSidebar"] {
        background: #0d0d1a !important;
        border-right: 1px solid rgba(255,255,255,0.06) !important;
    }
    section[data-testid="stSidebar"] * {
        color: #a0a8c0 !important;
    }
    section[data-testid="stSidebar"] h2 {
        color: #e0e8ff !important;
        font-size: 1.1rem !important;
    }

    /* Headers */
    h1, h2, h3 {
        font-family: 'Syne', sans-serif !important;
        color: #e0e8ff !important;
        letter-spacing: -0.02em !important;
    }

    /* Metrics */
    [data-testid="stMetric"] {
        background: rgba(255,255,255,0.03) !important;
        border: 1px solid rgba(255,255,255,0.07) !important;
        border-radius: 12px !important;
        padding: 16px !important;
    }
    [data-testid="stMetricValue"] {
        font-family: 'JetBrains Mono', monospace !important;
        color: #00e5ff !important;
    }

    /* Buttons (default) */
    .stButton > button {
        background: rgba(255,255,255,0.05) !important;
        border: 1px solid rgba(255,255,255,0.1) !important;
        color: #c0c8e0 !important;
        border-radius: 8px !important;
        font-family: 'Syne', sans-serif !important;
        font-weight: 600 !important;
        transition: all 0.15s ease !important;
    }
    .stButton > button:hover {
        background: rgba(255,255,255,0.1) !important;
        border-color: rgba(255,255,255,0.2) !important;
        color: #ffffff !important;
    }

    /* Primary button */
    .stButton > button[kind="primary"] {
        background: linear-gradient(135deg, #0066ff, #00ccff) !important;
        border: none !important;
        color: white !important;
    }

    /* Divider */
    hr {
        border-color: rgba(255,255,255,0.06) !important;
    }

    /* Radio */
    .stRadio label {
        color: #a0a8c0 !important;
    }

    /* Selectbox */
    .stSelectbox > div > div {
        background: rgba(255,255,255,0.04) !important;
        border-color: rgba(255,255,255,0.1) !important;
        color: #e0e8ff !important;
    }

    /* Info/warning boxes */
    .stAlert {
        background: rgba(255,255,255,0.04) !important;
        border-radius: 10px !important;
    }

    /* Hide Streamlit branding */
    #MainMenu {visibility: hidden !important;}
    footer {visibility: hidden !important;}
    header {visibility: hidden !important;}
    .stDeployButton {display: none !important;}
    [data-testid="stToolbar"] {display: none !important;}
    </style>
    """, unsafe_allow_html=True)


# ─── DEVICE GRID CSS ──────────────────────────────────────────────────────────
# One CSS block injected once — styles ALL device buttons by state class
# Individual buttons get their class via key, styled below
_DEVICE_GRID_CSS = """
<style>
/* Make all device button columns equal width */
div[data-testid="stHorizontalBlock"] > div {{
    flex: 1 1 0 !important;
    min-width: 0 !important;
}}

/* ON state buttons */
{on_rules}

/* OFF state buttons */
{off_rules}
</style>
"""

_BTN_RULE = """.st-key-device_{id} button {{
    height: 68px !important;
    width: 100% !important;
    min-width: 0 !important;
    border-radius: 10px !important;
    background: {bg} !important;
    color: {fg} !important;
    font-family: 'JetBrains Mono', monospace !important;
    font-weight: 700 !important;
    font-size: 11px !important;
    border: 1px solid {border} !important;
    line-height: 1.4 !important;
    padding: 6px 2px !important;
    white-space: pre-wrap !important;
    box-sizing: border-box !important;
    transition: all 0.15s ease !important;
}}
.st-key-device_{id} button:hover {{
    filter: brightness(1.15) !important;
    transform: translateY(-1px) !important;
    box-shadow: 0 4px 16px {shadow} !important;
}}"""


def _build_device_css(page_devices, latest_pwr):
    rules = []
    for deviceid, groupid, state, owner in page_devices:
        if bool(state):
            bg     = "linear-gradient(160deg, #00873a, #00c853)"
            fg     = "#d0ffe8"
            border = "rgba(0,200,83,0.4)"
            shadow = "rgba(0,200,83,0.35)"
        else:
            bg     = "linear-gradient(160deg, #7f0000, #c62828)"
            fg     = "#ffd0d0"
            border = "rgba(198,40,40,0.4)"
            shadow = "rgba(198,40,40,0.35)"
        rules.append(_BTN_RULE.format(
            id=deviceid, bg=bg, fg=fg, border=border, shadow=shadow
        ))
    return "<style>" + "\n".join(rules) + "</style>"


# ─── LOGIN PAGE ───────────────────────────────────────────────────────────────
def login_page():
    _inject_global_css()

    # Centered login card
    st.markdown("""
    <div style="text-align:center; padding: 60px 0 20px 0;">
        <div style="font-family:'Syne',sans-serif; font-size:2.4rem; font-weight:800;
                    color:#e0e8ff; letter-spacing:-0.03em;">
            eIoT Dashboard
        </div>
        <div style="color:#505870; font-size:0.9rem; margin-top:4px;">
            Enterprise IoT Management
        </div>
    </div>
    """, unsafe_allow_html=True)

    pool_ready = utils._connector_pool is not None
    if not pool_ready:
        st.info("Connecting to database… (first load ~15–20 s)", icon="🔌")
        st_autorefresh(interval=2000, key="pool_check")

    col = st.columns([1, 1.2, 1])[1]
    with col:
        username = st.text_input("Username", placeholder="your@email.com")
        password = st.text_input("Password", type="password", placeholder="••••••••")
        btn_label = "Sign In" if pool_ready else "Connecting to DB…"
        if st.button(btn_label, disabled=not pool_ready, type="primary", use_container_width=True):
            result = utils.authenticate_user(username, password)
            if result:
                st.session_state.logged_in = True
                st.session_state.username  = result["username"]
                st.session_state.role      = result["role"]
                st.rerun()
            else:
                st.error("Invalid credentials")
        st.caption("Account creation is managed by an administrator.")


# ─── DEVICE PAGE ──────────────────────────────────────────────────────────────
def device_page(start_dt: datetime.datetime, end_dt: datetime.datetime):
    st.header("Devices")

    col1, col2, col3 = st.columns([1, 1, 2])
    with col1:
        if st.button("↺ Refresh States"):
            cached_get_devices.clear()
            cached_get_latest_power.clear()
            st.rerun()
    with col2:
        if st.button("↺ Refresh Power"):
            cached_get_latest_power.clear()
            st.rerun()
    with col3:
        st.session_state.auto_refresh = st.toggle(
            "Auto Refresh (5 s)", value=st.session_state.auto_refresh
        )

    if st.session_state.auto_refresh:
        st_autorefresh(interval=5000, key="refresh")

    devices    = cached_get_devices(st.session_state.username, is_admin())
    latest_pwr = cached_get_latest_power()
    devices    = sorted(devices, key=lambda x: x[0])
    total      = len(devices)

    st.caption(f"{total} devices total")

    # Detail panel (shown above the grid)
    device_modal(devices, start_dt, end_dt)

    # Inject per-device button CSS
    st.markdown(_build_device_css(devices, latest_pwr), unsafe_allow_html=True)

    # Grid — 10 columns
    GRID_COLS = 10
    rows = [devices[i:i+GRID_COLS] for i in range(0, len(devices), GRID_COLS)]
    for row in rows:
        cols = st.columns(GRID_COLS)
        for i, (deviceid, groupid, state, owner) in enumerate(row):
            state = bool(state)
            # FIX: use `is not None` so 0W devices still show power
            power = latest_pwr.get(str(deviceid), None)
            ptext = f"{power:.0f}W" if power is not None else "—"
            tip   = f"Group {groupid} | {'ON' if state else 'OFF'} | {ptext} | {owner}"
            if cols[i].button(f"{deviceid}\n{ptext}", key=f"device_{deviceid}", help=tip):
                st.session_state.selected_device = deviceid
                st.rerun()


def device_modal(devices, start_dt, end_dt):
    deviceid = st.session_state.get("selected_device")
    if deviceid is None:
        return

    current = next((d for d in devices if d[0] == deviceid), None)
    if current is None:
        return

    deviceid, groupid, state, owner = current
    state = bool(state)

    st.divider()

    # Header row
    status_color = "#00c853" if state else "#e53935"
    status_label = "ON" if state else "OFF"
    st.markdown(f"""
    <div style="display:flex; align-items:center; gap:16px; margin-bottom:8px;">
        <div style="font-family:'Syne',sans-serif; font-size:1.3rem;
                    font-weight:700; color:#e0e8ff;">
            Device {deviceid}
        </div>
        <div style="background:{status_color}22; border:1px solid {status_color}66;
                    color:{status_color}; border-radius:20px; padding:2px 12px;
                    font-size:0.8rem; font-weight:700; font-family:'JetBrains Mono',monospace;">
            {status_label}
        </div>
        <div style="color:#505870; font-size:0.85rem;">
            Group {groupid} &nbsp;·&nbsp; {owner}
        </div>
    </div>
    """, unsafe_allow_html=True)

    start_iso = start_dt.isoformat()
    end_iso   = end_dt.isoformat()
    df = cached_device_power(deviceid, start_iso, end_iso)

    if not df.empty:
        # Quick stats
        c1, c2, c3 = st.columns(3)
        c1.metric("Avg Power",  f"{df['power'].mean():.0f} W")
        c2.metric("Peak Power", f"{df['power'].max():.0f} W")
        c3.metric("Readings",   f"{len(df):,}")

        fig = _line_fig(df, "time", "power", title=f"Device {deviceid} – Power Usage")
        st.plotly_chart(fig, width="stretch")
    else:
        st.info("No power data for selected range.")

    if is_operator():
        new_state = st.toggle("Device ON", value=state, key=f"device_toggle_{deviceid}")
        if new_state != state:
            utils.update_device_state(owner, deviceid, int(new_state))
            cached_get_devices.clear()
            st.success("Device state updated")
            st.rerun()

        c1, c2 = st.columns([1, 5])
        with c1:
            if st.button("🗑 Delete Device"):
                utils.delete_device(owner, deviceid)
                cached_get_devices.clear()
                st.session_state.selected_device = None
                st.rerun()
    else:
        st.info(f"State: {'ON' if state else 'OFF'}  (viewer — no controls)")

    if st.button("✕ Close"):
        st.session_state.selected_device = None
        st.rerun()

    st.divider()


# ─── GROUP PAGE ───────────────────────────────────────────────────────────────
_GRP_BTN_CSS = """<style>
{rules}
</style>"""

_GRP_RULE = """.st-key-group_{id} button {{
    height: 80px !important;
    width: 100% !important;
    border-radius: 12px !important;
    background: {bg} !important;
    color: {fg} !important;
    font-family: 'Syne', sans-serif !important;
    font-size: 15px !important;
    font-weight: 700 !important;
    border: 1px solid {border} !important;
    transition: all 0.15s ease !important;
}}
.st-key-group_{id} button:hover {{
    filter: brightness(1.15) !important;
    transform: translateY(-2px) !important;
    box-shadow: 0 6px 20px {shadow} !important;
}}"""


def group_page(start_dt, end_dt):
    st.header("Groups")
    if st.button("↺ Refresh Groups"):
        cached_get_groups.clear()
        st.rerun()

    groups = cached_get_groups(st.session_state.username, is_admin())
    groups = sorted(groups, key=lambda x: x[0])

    rules = []
    for groupid, state, owner in groups:
        if bool(state):
            bg, fg = "linear-gradient(160deg,#00873a,#00c853)", "#d0ffe8"
            border, shadow = "rgba(0,200,83,0.4)", "rgba(0,200,83,0.3)"
        else:
            bg, fg = "linear-gradient(160deg,#7f0000,#c62828)", "#ffd0d0"
            border, shadow = "rgba(198,40,40,0.4)", "rgba(198,40,40,0.3)"
        rules.append(_GRP_RULE.format(
            id=groupid, bg=bg, fg=fg, border=border, shadow=shadow
        ))
    st.markdown("<style>" + "\n".join(rules) + "</style>", unsafe_allow_html=True)

    GRID_COLS = 5
    rows = [groups[i:i+GRID_COLS] for i in range(0, len(groups), GRID_COLS)]
    for row in rows:
        cols = st.columns(GRID_COLS)
        for i, (groupid, state, owner) in enumerate(row):
            state = bool(state)
            label = f"Group {groupid}\n{'ON' if state else 'OFF'}"
            if is_operator():
                if cols[i].button(label, key=f"group_{groupid}",
                                  help=f"Click to toggle group {groupid}"):
                    utils.update_group_state(owner, groupid, not state)
                    cached_get_groups.clear()
                    cached_get_devices.clear()
                    st.rerun()
            else:
                cols[i].button(label, key=f"group_{groupid}", disabled=True)


# ─── ANALYTICS PAGE ───────────────────────────────────────────────────────────
def analytics_page(start_dt, end_dt):
    st.header("Analytics")

    start_iso = start_dt.isoformat()
    end_iso   = end_dt.isoformat()

    mode = st.radio("View Analytics For", ["Device", "Group"], horizontal=True)

    if mode == "Device":
        devices = cached_get_devices(st.session_state.username, is_admin())
        dev_ids = [d[0] for d in devices]
        if not dev_ids:
            st.warning("No devices found.")
            return

        selected = st.selectbox("Select Device", dev_ids)
        df = cached_device_power(selected, start_iso, end_iso)

        if df.empty:
            st.info("No data for this device in the selected range.")
            return

        c1, c2, c3 = st.columns(3)
        c1.metric("Avg Power",  f"{df['power'].mean():.0f} W")
        c2.metric("Peak Power", f"{df['power'].max():.0f} W")
        c3.metric("Readings",   f"{len(df):,}")

        fig = _line_fig(df, "time", "power",
                        title=f"Device {selected} – Power Usage",
                        y_label="Power (W)")
        st.plotly_chart(fig, width="stretch")

    else:
        groups  = cached_get_groups(st.session_state.username, is_admin())
        grp_ids = [g[0] for g in groups]
        if not grp_ids:
            st.warning("No groups found.")
            return

        selected = st.selectbox("Select Group", grp_ids)
        df = cached_group_power(
            st.session_state.username, selected, start_iso, end_iso, is_admin()
        )

        if df.empty:
            st.info("No data for this group in the selected range.")
            return

        device_cols = [c for c in df.columns if c != "time"]
        MAX_TRACES  = 20

        view = st.radio("Chart view", ["Combined", "Individual grids"], horizontal=True)

        if view == "Combined":
            cols_to_plot = device_cols[:MAX_TRACES]
            if len(device_cols) > MAX_TRACES:
                st.caption(f"Showing first {MAX_TRACES} of {len(device_cols)} devices.")
            fig = _multi_line_fig(df, "time", cols_to_plot,
                                  title=f"Group {selected} – All Devices")
            st.plotly_chart(fig, width="stretch")
        else:
            GRID_COLS = 2
            rows = [device_cols[i:i+GRID_COLS] for i in range(0, len(device_cols), GRID_COLS)]
            for row in rows:
                cols = st.columns(GRID_COLS)
                for idx, dev in enumerate(row):
                    sub = df[["time", dev]].dropna(subset=[dev])
                    if sub.empty:
                        cols[idx].warning(f"Device {dev}: no data")
                        continue
                    fig = _line_fig(sub, "time", dev, title=f"Device {dev}")
                    cols[idx].plotly_chart(fig, width="stretch")


# ─── RBAC PAGE ────────────────────────────────────────────────────────────────
def rbac_page():
    st.header("User Management")

    users = cached_all_users()

    st.subheader("All Users")
    for u in users:
        c1, c2, c3, c4 = st.columns([3, 2, 2, 1])
        c1.write(u["username"])
        c2.write(u["role"])

        new_role = c3.selectbox(
            "Role", options=list(utils.ROLES),
            index=list(utils.ROLES).index(u["role"]),
            key=f"role_sel_{u['username']}",
            label_visibility="collapsed",
        )
        if new_role != u["role"]:
            if utils.update_user_role(u["username"], new_role):
                cached_all_users.clear()
                st.success(f"Updated {u['username']} → {new_role}")
                st.rerun()

        if c4.button("Delete", key=f"del_{u['username']}"):
            if u["username"] == st.session_state.username:
                st.error("Cannot delete yourself.")
            else:
                utils.delete_user(u["username"])
                cached_all_users.clear()
                st.rerun()

    st.divider()
    st.subheader("Create New User")
    nc1, nc2, nc3, nc4 = st.columns([3, 2, 2, 1])
    new_uname = nc1.text_input("Username", key="new_uname")
    new_pass  = nc2.text_input("Password", type="password", key="new_pass")
    new_role  = nc3.selectbox("Role", utils.ROLES, key="new_role")
    if nc4.button("Create"):
        if not new_uname or not new_pass:
            st.error("Username and password required.")
        elif utils.create_user(new_uname, new_pass, new_role):
            cached_all_users.clear()
            st.success(f"Created user: {new_uname} ({new_role})")
            st.rerun()
        else:
            st.error("Username already exists.")


# ─── SCHEDULES PAGE ───────────────────────────────────────────────────────────
WEEKDAY_NAMES = ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"]


@st.cache_data(ttl=30)
def cached_get_schedules(username, admin):
    return utils.get_schedules(created_by=None if admin else username)


def _fmt_run_at(run_at) -> str:
    if isinstance(run_at, datetime.timedelta):
        total = int(run_at.total_seconds())
        h, rem = divmod(total, 3600)
        m, s   = divmod(rem, 60)
    else:
        # Already a time object
        h = run_at.hour
        m = run_at.minute
        s = 0
    
    # Convert to 12-hour format with AM/PM
    am_pm = "AM" if h < 12 else "PM"
    h_12 = h % 12
    if h_12 == 0:
        h_12 = 12
    return f"{h_12}:{m:02d} {am_pm}"


def schedules_page():
    st.header("⏰ Schedules")
    st.caption("Automatic ON/OFF actions for devices or groups (IST).")

    IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
    now_ist = datetime.datetime.now(IST)

    schedules = cached_get_schedules(st.session_state.username, is_admin())
    
    # Filter out past one-time schedules
    filtered_schedules = []
    deleted_any = False
    for s in schedules:
        if s["mode"] == "once" and s["run_date"]:
            # Check if this one-time schedule is in the past
            run_time = (datetime.datetime.min + s["run_at"]).time() if isinstance(s["run_at"], datetime.timedelta) else s["run_at"]
            schedule_datetime = datetime.datetime.combine(s["run_date"], run_time)
            # Add IST timezone
            if schedule_datetime.tzinfo is None:
                schedule_datetime = schedule_datetime.replace(tzinfo=IST)
            if schedule_datetime < now_ist:
                # Delete past one-time schedules
                utils.delete_schedule(s["id"])
                deleted_any = True
                continue
        filtered_schedules.append(s)
    
    # Clear cache if we deleted any schedules
    if deleted_any:
        cached_get_schedules.clear()
    
    schedules = filtered_schedules

    if schedules:
        st.subheader("Active & Past Schedules")
        for s in schedules:
            active     = bool(s["active"])
            run_at_str = _fmt_run_at(s["run_at"])

            if s["mode"] == "once":
                when = f"Once on {s['run_date']} at {run_at_str} IST"
            elif s["mode"] == "daily":
                when = f"Daily at {run_at_str} IST"
            else:
                day_name = WEEKDAY_NAMES[s["weekday"]] if s["weekday"] is not None else "?"
                when = f"Every {day_name} at {run_at_str} IST"

            label = (
                f"{'🟢' if active else '⚫'}  "
                f"**{s['target_type'].capitalize()} {s['target_id']}** → "
                f"turn **{s['action'].upper()}**  |  {when}"
            )
            if is_admin():
                label += f"  |  by `{s['created_by']}`"

            c1, c2, c3 = st.columns([6, 1, 1])
            c1.markdown(label)
            if c2.button("Pause" if active else "Resume", key=f"tog_{s['id']}"):
                utils.toggle_schedule(s["id"], not active)
                cached_get_schedules.clear()
                st.rerun()
            if c3.button("Delete", key=f"del_sched_{s['id']}"):
                utils.delete_schedule(s["id"])
                cached_get_schedules.clear()
                st.rerun()
    else:
        st.info("No schedules yet.")

    st.divider()
    st.subheader("Create New Schedule")

    IST     = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
    now_ist = datetime.datetime.now(IST)

    c1, c2 = st.columns(2)
    with c1:
        target_type = st.selectbox("Target type", ["device", "group"], key="sched_ttype")
    with c2:
        if target_type == "device":
            target_ids = [d[0] for d in cached_get_devices(st.session_state.username, is_admin())]
        else:
            target_ids = [g[0] for g in cached_get_groups(st.session_state.username, is_admin())]
        target_id = st.selectbox(f"Select {target_type}", target_ids, key="sched_tid")

    c3, c4 = st.columns(2)
    with c3:
        action = st.selectbox("Action", ["on", "off"], key="sched_action")
    with c4:
        mode = st.selectbox("Repeat", ["once", "daily", "weekly"], key="sched_mode")

    # Time selector with hour/minute/AM-PM
    st.markdown("**Schedule Time (IST)**")
    tc1, tc2, tc3 = st.columns(3)
    
    # Default to current IST time
    current_hour_24 = now_ist.hour
    current_minute = now_ist.minute
    current_am_pm = "AM" if current_hour_24 < 12 else "PM"
    current_hour_12 = current_hour_24 % 12
    if current_hour_12 == 0:
        current_hour_12 = 12
    
    with tc1:
        hour_12 = st.selectbox(
            "Hour",
            options=list(range(1, 13)),
            index=current_hour_12 - 1,  # default to current hour
            key="sched_hour",
        )
    with tc2:
        minute = st.selectbox(
            "Minute",
            options=list(range(0, 60)),
            index=current_minute,  # default to current minute
            key="sched_minute",
        )
    with tc3:
        am_pm = st.selectbox(
            "AM/PM",
            options=["AM", "PM"],
            index=0 if current_am_pm == "AM" else 1,  # default to current AM/PM
            key="sched_ampm",
        )

    # Convert to 24-hour format
    hour_24 = hour_12 if am_pm == "AM" else hour_12 + 12
    if hour_12 == 12 and am_pm == "AM":
        hour_24 = 0
    elif hour_12 == 12 and am_pm == "PM":
        hour_24 = 12
    run_time = datetime.time(hour_24, minute, 0)

    c6 = st.columns(1)[0]
    with c6:
        run_date = None
        weekday  = None
        if mode == "once":
            run_date = st.date_input(
                "Date (IST)",
                value=now_ist.date(),
                min_value=now_ist.date(),
                key="sched_date",
            )
        elif mode == "weekly":
            day_name = st.selectbox("Day of week", WEEKDAY_NAMES, key="sched_weekday")
            weekday  = WEEKDAY_NAMES.index(day_name)
        else:
            st.write("")

    if st.button("➕ Create Schedule", type="primary"):
        if target_id is None:
            st.error("No target selected.")
        else:
            ok = utils.create_schedule(
                created_by  = st.session_state.username,
                target_type = target_type,
                target_id   = int(target_id),
                action      = action,
                mode        = mode,
                run_at      = run_time,
                run_date    = run_date,
                weekday     = weekday,
            )
            if ok:
                cached_get_schedules.clear()
                st.success(
                    f"Schedule created: {target_type} {target_id} → {action.upper()} "
                    f"({'once on ' + str(run_date) if mode == 'once' else mode}) "
                    f"at {run_time.strftime('%H:%M:%S')} IST"
                )
                st.rerun()
            else:
                st.error("Failed to create schedule — check logs.")


# ─── MAIN DASHBOARD ───────────────────────────────────────────────────────────
def dashboard():
    _inject_global_css()

    st.sidebar.markdown("""
    <div style="font-family:'Syne',sans-serif; font-size:1.3rem;
                font-weight:800; color:#e0e8ff; letter-spacing:-0.02em;
                padding: 4px 0 2px 0;">
        eIoT Dashboard
    </div>
    """, unsafe_allow_html=True)
    st.sidebar.caption(
        f"**{st.session_state.username}**  ·  `{st.session_state.role}`"
    )

    pages = ["Devices", "Groups", "Analytics", "Schedules"]
    if is_admin():
        pages.append("User Management")

    page = st.sidebar.radio("Navigation", pages)

    if st.sidebar.button("Sign Out"):
        for k in list(st.session_state.keys()):
            del st.session_state[k]
        st.rerun()

    start_dt, end_dt = render_date_range_selector()

    if page == "Devices":
        device_page(start_dt, end_dt)
    elif page == "Groups":
        group_page(start_dt, end_dt)
    elif page == "Analytics":
        analytics_page(start_dt, end_dt)
    elif page == "Schedules":
        schedules_page()
    elif page == "User Management":
        if is_admin():
            rbac_page()
        else:
            st.error("Access denied.")


# ─── ENTRY POINT ──────────────────────────────────────────────────────────────
if not st.session_state.logged_in:
    login_page()
else:
    dashboard()

log.info("── script rerun complete [%.0f ms] ──",
         (time.perf_counter() - _t_script_start) * 1000)