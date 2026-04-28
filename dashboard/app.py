import time
import logging
import threading

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from streamlit_autorefresh import st_autorefresh

import utils

# --- LOGGING SETUP ---
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s.%(msecs)03d [%(levelname)s] %(funcName)s - %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("eiot.app")

st.set_page_config(layout="wide")

_t_script_start = time.perf_counter()
log.debug("-- script rerun started --")


# --- POOL WARM-UP (non-blocking) ---
# RDS cold-connect from India ~20s SSL handshake latency.
# Background thread means login page renders immediately on startup.

@st.cache_resource
def _start_pool_warmup():
    def _warmup():
        t0 = time.perf_counter()
        try:
            conn = utils.get_connection()
            conn.close()
            log.info("Background pool warm-up done [%.0f ms]", (time.perf_counter() - t0) * 1000)
        except Exception as e:
            log.error("Background pool warm-up failed: %s", e)
    t = threading.Thread(target=_warmup, daemon=True, name="pool-warmup")
    t.start()
    log.info("Pool warm-up started in background thread")
    return True

_start_pool_warmup()


# --- CACHED DATA HELPERS ---

@st.cache_data(ttl=30)
def cached_get_devices(username):
    log.debug("CACHE MISS: cached_get_devices(%s)", username)
    t0 = time.perf_counter()
    result = utils.get_devices(username)
    log.info("cached_get_devices(%s) populated [%.0f ms]", username, (time.perf_counter() - t0) * 1000)
    return result


@st.cache_data(ttl=30)
def cached_get_latest_power_usage():
    log.debug("CACHE MISS: cached_get_latest_power_usage")
    t0 = time.perf_counter()
    result = utils.get_latest_power_usage()
    log.info("cached_get_latest_power_usage populated [%.0f ms]", (time.perf_counter() - t0) * 1000)
    return result


@st.cache_data(ttl=60)
def cached_get_device_power_usage(deviceid):
    log.debug("CACHE MISS: cached_get_device_power_usage(%s)", deviceid)
    t0 = time.perf_counter()
    result = utils.get_device_power_usage(deviceid)
    log.info("cached_get_device_power_usage(%s) populated [%.0f ms]", deviceid, (time.perf_counter() - t0) * 1000)
    return result


@st.cache_data(ttl=30)
def cached_get_groups(username):
    log.debug("CACHE MISS: cached_get_groups(%s)", username)
    t0 = time.perf_counter()
    result = utils.get_groups(username)
    log.info("cached_get_groups(%s) populated [%.0f ms]", username, (time.perf_counter() - t0) * 1000)
    return result


@st.cache_data(ttl=60)
def cached_get_group_power_usage(username, groupid):
    log.debug("CACHE MISS: cached_get_group_power_usage(%s, %s)", username, groupid)
    t0 = time.perf_counter()
    result = utils.get_group_power_usage(username, groupid)
    log.info("cached_get_group_power_usage(%s, %s) populated [%.0f ms]", username, groupid, (time.perf_counter() - t0) * 1000)
    return result


# --- SESSION STATE ---

for key, default in [
    ("logged_in", False),
    ("username", None),
    ("selected_device", None),
    ("auto_refresh", False),
    ("device_page_offset", 0),
]:
    if key not in st.session_state:
        st.session_state[key] = default


# --- LOGIN PAGE ---

def login_page():
    t0 = time.perf_counter()
    st.title("Enterprise IoT Dashboard")

    # Show status while background pool thread is still connecting
    pool_ready = utils._connector_pool is not None
    if not pool_ready:
        st.info(
            "Connecting to database... (first load only, usually 15-20s due to RDS cold start)",
            icon="🔌"
        )
        # Auto-rerun every 2s to re-check pool readiness
        st_autorefresh(interval=2000, key="pool_check")

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Login")
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        btn_label = "Login" if pool_ready else "Waiting for DB..."
        if st.button(btn_label, disabled=not pool_ready):
            if utils.authenticate_user(username, password):
                st.session_state.logged_in = True
                st.session_state.username = username
                st.rerun()
            else:
                st.error("Invalid credentials")

    with col2:
        st.subheader("Create Account")
        new_user = st.text_input("New Username")
        new_pass = st.text_input("New Password", type="password")
        if st.button("Create User", disabled=not pool_ready):
            if utils.create_user(new_user, new_pass):
                st.success("User created")
            else:
                st.error("User exists")

    log.debug("login_page rendered [%.0f ms] pool_ready=%s", (time.perf_counter() - t0) * 1000, pool_ready)


# --- DEVICE GRID ---
# Virtualized: only render PAGE_SIZE devices at a time instead of all 500.
# 500 Streamlit buttons = ~500ms widget serialization per rerun.
# 100 buttons = ~100ms.

PAGE_SIZE = 100

_GRID_CSS = """<style>
div[data-testid="stVerticalBlock"] {{ gap: 0.35rem; }}
{styles}
</style>"""

_BTN_CSS = """.st-key-device_{id} button {{
    height:70px;width:100%;border-radius:12px;background:{color};
    color:white;font-weight:600;border:1px solid rgba(255,255,255,0.15);
    display:flex;flex-direction:column;justify-content:center;align-items:center;
}}
.st-key-device_{id} button:hover {{transform:scale(1.05);box-shadow:0 0 10px rgba(255,255,255,0.35);}}"""


def device_page():
    t0 = time.perf_counter()
    st.header("Devices")

    col1, col2, col3 = st.columns([1, 1, 2])
    with col1:
        if st.button("Refresh Device States"):
            log.info("Manual refresh: device states")
            cached_get_devices.clear()
            cached_get_latest_power_usage.clear()
            st.rerun()
    with col2:
        if st.button("Refresh Power Usage"):
            log.info("Manual refresh: power usage")
            cached_get_latest_power_usage.clear()
            st.rerun()
    with col3:
        st.session_state.auto_refresh = st.toggle(
            "Auto Refresh (5 sec)", value=st.session_state.auto_refresh
        )

    if st.session_state.auto_refresh:
        st_autorefresh(interval=5000, key="refresh")

    t_fetch = time.perf_counter()
    devices = cached_get_devices(st.session_state.username)
    latest_power = cached_get_latest_power_usage()
    log.info("Data fetch (devices + latest_power) [%.0f ms]", (time.perf_counter() - t_fetch) * 1000)

    devices = sorted(devices, key=lambda x: x[0])
    total = len(devices)

    # Show device detail panel above grid
    device_modal(devices)

    # Pagination controls
    offset = st.session_state.device_page_offset
    offset = max(0, min(offset, total - 1))
    page_devices = devices[offset: offset + PAGE_SIZE]

    pcol1, pcol2, pcol3 = st.columns([1, 3, 1])
    with pcol1:
        if st.button("< Prev", disabled=(offset == 0)):
            st.session_state.device_page_offset = max(0, offset - PAGE_SIZE)
            st.rerun()
    with pcol2:
        end = min(offset + PAGE_SIZE, total)
        st.caption(f"Showing devices {offset + 1}-{end} of {total}")
    with pcol3:
        if st.button("Next >", disabled=(offset + PAGE_SIZE >= total)):
            st.session_state.device_page_offset = offset + PAGE_SIZE
            st.rerun()

    # Single CSS block for this page only
    t_css = time.perf_counter()
    css_parts = []
    for deviceid, groupid, state in page_devices:
        color = "#2ecc71" if bool(state) else "#e74c3c"
        css_parts.append(_BTN_CSS.format(id=deviceid, color=color))
    st.markdown(_GRID_CSS.format(styles="\n".join(css_parts)), unsafe_allow_html=True)
    log.debug("CSS injection [%.0f ms] for %d devices", (time.perf_counter() - t_css) * 1000, len(page_devices))

    # Grid
    t_grid = time.perf_counter()
    grid_cols = 10
    rows = [page_devices[i:i + grid_cols] for i in range(0, len(page_devices), grid_cols)]

    for row in rows:
        cols = st.columns(grid_cols)
        for i, (deviceid, groupid, state) in enumerate(row):
            state = bool(state)
            power = latest_power.get(str(deviceid), None)
            power_text = f"{power} W" if power else "-"
            tooltip = f"Device {deviceid} | Group {groupid} | {'ON' if state else 'OFF'} | {power_text}"

            if cols[i].button(f"{deviceid}\n{power_text}", key=f"device_{deviceid}", help=tooltip):
                log.info("Device %s clicked", deviceid)
                st.session_state.selected_device = deviceid
                st.rerun()

    log.info("device_page grid rendered [%.0f ms] (%d on page)", (time.perf_counter() - t_grid) * 1000, len(page_devices))
    log.info("device_page total [%.0f ms]", (time.perf_counter() - t0) * 1000)


# --- DEVICE MODAL ---

def device_modal(devices):
    t0 = time.perf_counter()
    deviceid = st.session_state.get("selected_device")
    if deviceid is None:
        log.debug("device_modal: no device selected, skipping")
        return

    current_device = next((d for d in devices if d[0] == deviceid), None)
    if current_device is None:
        log.warning("device_modal: selected device %s not found", deviceid)
        return

    deviceid, groupid, state = current_device
    state = bool(state)

    st.divider()
    st.subheader(f"Device {deviceid}")

    t_chart = time.perf_counter()
    df = cached_get_device_power_usage(deviceid)
    log.info("device_modal: chart data fetch [%.0f ms] (%d rows)", (time.perf_counter() - t_chart) * 1000, len(df))

    if not df.empty:
        t_plot = time.perf_counter()
        fig = px.line(df, x="time", y="power")
        st.plotly_chart(fig, width="stretch")
        log.debug("device_modal: plotly render [%.0f ms]", (time.perf_counter() - t_plot) * 1000)

    st.write(f"Group: {groupid}")

    new_state = st.toggle("Device ON", value=state, key=f"device_toggle_{deviceid}")
    if new_state != state:
        log.info("device_modal: toggling device %s -> %s", deviceid, new_state)
        utils.update_device_state(st.session_state.username, deviceid, int(new_state))
        cached_get_devices.clear()
        st.success("Device state updated")
        st.rerun()

    col1, col2 = st.columns(2)
    with col1:
        if st.button("Delete Device"):
            log.info("device_modal: deleting device %s", deviceid)
            utils.delete_device(st.session_state.username, deviceid)
            cached_get_devices.clear()
            st.session_state.selected_device = None
            st.rerun()
    with col2:
        if st.button("Close"):
            st.session_state.selected_device = None
            st.rerun()

    log.info("device_modal total [%.0f ms]", (time.perf_counter() - t0) * 1000)


# --- GROUP PAGE ---

_GROUP_CSS = """<style>
div[data-testid="stVerticalBlock"] {{ gap: 0.35rem; }}
{styles}
</style>"""

_GRP_BTN_CSS = """.st-key-group_{id} button {{
    height:80px;width:100%;border-radius:12px;background:{color};
    color:white;font-size:18px;font-weight:600;border:1px solid rgba(255,255,255,0.15);
}}
.st-key-group_{id} button:hover {{transform:scale(1.05);box-shadow:0 0 10px rgba(255,255,255,0.35);}}"""


def group_page():
    t0 = time.perf_counter()
    st.header("Groups")

    if st.button("Refresh Group States"):
        log.info("Manual refresh: groups")
        cached_get_groups.clear()
        st.rerun()

    t_fetch = time.perf_counter()
    groups = cached_get_groups(st.session_state.username)
    log.info("group_page: data fetch [%.0f ms] (%d groups)", (time.perf_counter() - t_fetch) * 1000, len(groups))
    groups = sorted(groups, key=lambda x: x[0])

    t_css = time.perf_counter()
    css_parts = [_GRP_BTN_CSS.format(id=g[0], color="#2ecc71" if bool(g[1]) else "#e74c3c") for g in groups]
    st.markdown(_GROUP_CSS.format(styles="\n".join(css_parts)), unsafe_allow_html=True)
    log.debug("group_page: CSS injection [%.0f ms]", (time.perf_counter() - t_css) * 1000)

    grid_cols = 5
    rows = [groups[i:i + grid_cols] for i in range(0, len(groups), grid_cols)]
    for row in rows:
        cols = st.columns(grid_cols)
        for i, (groupid, state) in enumerate(row):
            state = bool(state)
            if cols[i].button(
                f"Group {groupid}",
                key=f"group_{groupid}",
                help=f"Group {groupid} | {'ON' if state else 'OFF'} | Click to toggle"
            ):
                log.info("group_page: toggling group %s -> %s", groupid, not state)
                utils.update_group_state(st.session_state.username, groupid, not state)
                cached_get_groups.clear()
                cached_get_devices.clear()
                st.rerun()

    log.info("group_page total [%.0f ms]", (time.perf_counter() - t0) * 1000)


# --- ANALYTICS PAGE ---

def analytics_page():
    t0 = time.perf_counter()
    st.header("Analytics")

    mode = st.radio("View Analytics For", ["Device", "Group"])

    if mode == "Device":
        devices = cached_get_devices(st.session_state.username)
        selected = st.selectbox("Select Device", [d[0] for d in devices])

        t_fetch = time.perf_counter()
        df = cached_get_device_power_usage(selected)
        log.info("analytics_page: device data fetch [%.0f ms] (%d rows)", (time.perf_counter() - t_fetch) * 1000, len(df))

        t_plot = time.perf_counter()
        fig = px.line(df, x="time", y="power")
        st.plotly_chart(fig, width="stretch")
        log.debug("analytics_page: device plotly render [%.0f ms]", (time.perf_counter() - t_plot) * 1000)

    else:
        groups = cached_get_groups(st.session_state.username)
        selected = st.selectbox("Select Group", [g[0] for g in groups])

        t_fetch = time.perf_counter()
        df = cached_get_group_power_usage(st.session_state.username, selected)
        log.info("analytics_page: group data fetch [%.0f ms] (%d rows x %d cols)",
                 (time.perf_counter() - t_fetch) * 1000, len(df), len(df.columns) if not df.empty else 0)

        if df.empty:
            st.warning("No data")
            return

        device_cols = [c for c in df.columns if c != "time"]

        # One combined chart vs 50 individual charts (was 2.5s bottleneck)
        t_plot = time.perf_counter()
        view = st.radio("Chart view", ["Combined (fast)", "Individual grids"], horizontal=True)

        if view == "Combined (fast)":
            fig = go.Figure()
            for col in device_cols:
                fig.add_trace(go.Scatter(x=df["time"], y=df[col], mode="lines", name=f"Device {col}"))
            fig.update_layout(
                title=f"Group {selected} - All Devices",
                xaxis_title="Time",
                yaxis_title="Power (W)",
                legend=dict(orientation="h", y=-0.2),
                height=500,
            )
            st.plotly_chart(fig, width="stretch")
            log.debug("analytics_page: combined chart render [%.0f ms]", (time.perf_counter() - t_plot) * 1000)
        else:
            grid_cols = 2
            rows = [device_cols[i:i + grid_cols] for i in range(0, len(device_cols), grid_cols)]
            for row in rows:
                cols = st.columns(grid_cols)
                for i, device in enumerate(row):
                    fig = px.line(df, x="time", y=device, title=f"Device {device}")
                    fig.update_layout(xaxis_title="Time", yaxis_title="Power (W)")
                    cols[i].plotly_chart(fig, width="stretch")
            log.debug("analytics_page: individual charts render [%.0f ms]", (time.perf_counter() - t_plot) * 1000)

    log.info("analytics_page total [%.0f ms]", (time.perf_counter() - t0) * 1000)


# --- MAIN DASHBOARD ---

def dashboard():
    t0 = time.perf_counter()
    st.sidebar.title("Navigation")
    page = st.sidebar.radio("Menu", ["Devices", "Groups", "Analytics"])
    st.sidebar.write(f"Logged in as {st.session_state.username}")

    if st.sidebar.button("Logout"):
        st.session_state.logged_in = False
        st.rerun()

    log.debug("Rendering page: %s", page)

    if page == "Devices":
        device_page()
    elif page == "Groups":
        group_page()
    elif page == "Analytics":
        analytics_page()

    log.info("dashboard() total [%.0f ms]", (time.perf_counter() - t0) * 1000)


# --- ENTRY POINT ---

if not st.session_state.logged_in:
    login_page()
else:
    dashboard()

log.info("-- script rerun complete [%.0f ms] --", (time.perf_counter() - _t_script_start) * 1000)