"""
app.py  –  eiot Dashboard v2
────────────────────────────────────────────────────────────────
Changes from v1:
  • Roles: admin / operator / viewer (gate toggles + RBAC page)
  • Admin sees ALL devices/groups across all users
  • Date-range selector in sidebar (min: 1 h, default: 30 days)
    → all charts honour the selected range via SQL
  • power_usage_normalized replaces wide table for charts
  • Gap-safe Plotly traces (connectgaps=False)
  • Multi-user safe: session state is per browser tab
"""

import time
import logging
import threading
import datetime

import streamlit as st
import plotly.graph_objects as go
from streamlit_autorefresh import st_autorefresh

import utils

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
    "role":             None,      # "admin" | "operator" | "viewer"
    "selected_device":  None,
    "auto_refresh":     False,
    "device_page_offset": 0,
}
for k, v in _DEFAULTS.items():
    if k not in st.session_state:
        st.session_state[k] = v


# ─── ROLE HELPERS ─────────────────────────────────────────────────────────────
def is_admin()    -> bool: return st.session_state.role == "admin"
def is_operator() -> bool: return st.session_state.role in ("admin", "operator")
def is_viewer()   -> bool: return True   # everyone can view


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
    """
    Renders a date-range control in the sidebar.
    Returns (start_dt, end_dt) as UTC-naive datetimes.
    """
    st.sidebar.markdown("---")
    st.sidebar.subheader("📅 Date Range")

    IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
    now = datetime.datetime.now(IST).replace(tzinfo=None)

    preset = st.sidebar.selectbox(
        "Quick range",
        ["Last hour", "Last 6 hours", "Last 24 hours",
         "Last 7 days", "Last 30 days", "Custom"],
        index=4,    # default: Last 30 days
        key="date_preset",
    )

    presets = {
        "Last hour":    now - datetime.timedelta(hours=1),
        "Last 6 hours": now - datetime.timedelta(hours=6),
        "Last 24 hours":now - datetime.timedelta(hours=24),
        "Last 7 days":  now - datetime.timedelta(days=7),
        "Last 30 days": now - datetime.timedelta(days=30),
    }

    if preset != "Custom":
        start_dt = presets[preset]
        end_dt   = now
    else:
        # Date picker: clamp min to 30 days back, max to today
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
        # Enforce min 1 h range
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


# ─── CHART HELPER ─────────────────────────────────────────────────────────────
def _line_fig(df, x_col, y_col, title="", y_label="Power (W)") -> go.Figure:
    """
    Single-series line chart with gap-safe rendering.
    NaN/missing rows show as breaks, not interpolated.
    """
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df[x_col], y=df[y_col],
        mode="lines",
        connectgaps=False,         # gaps stay as gaps
        line=dict(width=1.5),
        name=y_label,
    ))
    fig.update_layout(
        title=title,
        xaxis_title="Time",
        yaxis_title=y_label,
        margin=dict(l=40, r=20, t=40, b=40),
        yaxis=dict(range=[0, 900]),   
        height=350,
    )
    return fig


def _multi_line_fig(df, x_col, device_cols, title="") -> go.Figure:
    """
    Multi-device line chart. Each device is one trace.
    Devices with all-NaN in range are silently skipped.
    """
    fig = go.Figure()
    for col in device_cols:
        series = df[col]
        if series.isna().all():
            continue
        fig.add_trace(go.Scatter(
            x=df[x_col], y=series,
            mode="lines",
            connectgaps=False,
            line=dict(width=1),
            name=f"Dev {col}",
        ))
    fig.update_layout(
        title=title,
        xaxis_title="Time",
        yaxis_title="Power (W)",
        yaxis=dict(range=[0, 900]),   
        legend=dict(orientation="h", y=-0.25, font_size=10),
        margin=dict(l=40, r=20, t=40, b=80),
        height=450,
    )
    return fig


# ─── LOGIN PAGE ───────────────────────────────────────────────────────────────
def login_page():
    st.title("Enterprise IoT Dashboard")

    pool_ready = utils._connector_pool is not None
    if not pool_ready:
        st.info("Connecting to database… (first load, usually 15-20 s)", icon="🔌")
        st_autorefresh(interval=2000, key="pool_check")

    st.subheader("Login")
    username = st.text_input("Username")
    password = st.text_input("Password", type="password")
    btn_label = "Login" if pool_ready else "Waiting for DB…"

    if st.button(btn_label, disabled=not pool_ready):
        result = utils.authenticate_user(username, password)
        if result:
            st.session_state.logged_in = True
            st.session_state.username  = result["username"]
            st.session_state.role      = result["role"]
            st.rerun()
        else:
            st.error("Invalid credentials")

    st.caption("Account creation is managed by an administrator.")


# ─── DEVICE GRID ──────────────────────────────────────────────────────────────
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


def device_page(start_dt: datetime.datetime, end_dt: datetime.datetime):
    st.header("Devices")

    col1, col2, col3 = st.columns([1, 1, 2])
    with col1:
        if st.button("Refresh States"):
            cached_get_devices.clear(); cached_get_latest_power.clear(); st.rerun()
    with col2:
        if st.button("Refresh Power"):
            cached_get_latest_power.clear(); st.rerun()
    with col3:
        st.session_state.auto_refresh = st.toggle(
            "Auto Refresh (5 s)", value=st.session_state.auto_refresh
        )

    if st.session_state.auto_refresh:
        st_autorefresh(interval=5000, key="refresh")

    devices     = cached_get_devices(st.session_state.username, is_admin())
    latest_pwr  = cached_get_latest_power()
    devices     = sorted(devices, key=lambda x: x[0])
    total       = len(devices)

    # Device detail panel
    device_modal(devices, start_dt, end_dt)

    # Pagination
    offset = st.session_state.device_page_offset
    offset = max(0, min(offset, max(0, total - 1)))
    page_devices = devices[offset: offset + PAGE_SIZE]

    pc1, pc2, pc3 = st.columns([1, 3, 1])
    with pc1:
        if st.button("< Prev", disabled=(offset == 0)):
            st.session_state.device_page_offset = max(0, offset - PAGE_SIZE); st.rerun()
    with pc2:
        st.caption(f"Showing {offset+1}–{min(offset+PAGE_SIZE,total)} of {total}")
    with pc3:
        if st.button("Next >", disabled=(offset + PAGE_SIZE >= total)):
            st.session_state.device_page_offset = offset + PAGE_SIZE; st.rerun()

    # CSS
    css_parts = []
    for row in page_devices:
        deviceid, groupid, state, owner = row
        color = "#2ecc71" if bool(state) else "#e74c3c"
        css_parts.append(_BTN_CSS.format(id=deviceid, color=color))
    st.markdown(_GRID_CSS.format(styles="\n".join(css_parts)), unsafe_allow_html=True)

    # Grid
    grid_cols = 10
    rows = [page_devices[i:i+grid_cols] for i in range(0, len(page_devices), grid_cols)]
    for row in rows:
        cols = st.columns(grid_cols)
        for i, (deviceid, groupid, state, owner) in enumerate(row):
            state = bool(state)
            power = latest_pwr.get(str(deviceid), None)
            ptext = f"{power} W" if power else "–"
            tip   = f"Device {deviceid} | Group {groupid} | {'ON' if state else 'OFF'} | {ptext}"
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
    st.subheader(f"Device {deviceid}  |  Group {groupid}  |  Owner: {owner}")

    start_iso = start_dt.isoformat()
    end_iso   = end_dt.isoformat()
    df = cached_device_power(deviceid, start_iso, end_iso)

    if not df.empty:
        fig = _line_fig(df, "time", "power", title=f"Device {deviceid} – Power Usage")
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No power data for selected range.")

    # Operator/admin: can toggle; viewer: read-only
    if is_operator():
        new_state = st.toggle("Device ON", value=state, key=f"device_toggle_{deviceid}")
        if new_state != state:
            utils.update_device_state(owner, deviceid, int(new_state))
            cached_get_devices.clear()
            st.success("Device state updated")
            st.rerun()

        c1, c2 = st.columns(2)
        with c1:
            if st.button("Delete Device"):
                utils.delete_device(owner, deviceid)
                cached_get_devices.clear()
                st.session_state.selected_device = None
                st.rerun()
    else:
        st.info(f"State: {'ON' if state else 'OFF'}  (viewer — no controls)")

    if st.button("Close"):
        st.session_state.selected_device = None
        st.rerun()


# ─── GROUP PAGE ───────────────────────────────────────────────────────────────
_GROUP_CSS = """<style>
div[data-testid="stVerticalBlock"] {{ gap: 0.35rem; }}
{styles}
</style>"""

_GRP_BTN_CSS = """.st-key-group_{id} button {{
    height:80px;width:100%;border-radius:12px;background:{color};
    color:white;font-size:18px;font-weight:600;border:1px solid rgba(255,255,255,0.15);
}}
.st-key-group_{id} button:hover {{transform:scale(1.05);box-shadow:0 0 10px rgba(255,255,255,0.35);}}"""


def group_page(start_dt, end_dt):
    st.header("Groups")
    if st.button("Refresh Groups"):
        cached_get_groups.clear(); st.rerun()

    groups = cached_get_groups(st.session_state.username, is_admin())
    groups = sorted(groups, key=lambda x: x[0])

    css_parts = [_GRP_BTN_CSS.format(id=g[0], color="#2ecc71" if bool(g[1]) else "#e74c3c")
                 for g in groups]
    st.markdown(_GROUP_CSS.format(styles="\n".join(css_parts)), unsafe_allow_html=True)

    grid_cols = 5
    rows = [groups[i:i+grid_cols] for i in range(0, len(groups), grid_cols)]
    for row in rows:
        cols = st.columns(grid_cols)
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
        devices  = cached_get_devices(st.session_state.username, is_admin())
        dev_ids  = [d[0] for d in devices]
        if not dev_ids:
            st.warning("No devices found."); return

        selected = st.selectbox("Select Device", dev_ids)
        df = cached_device_power(selected, start_iso, end_iso)

        if df.empty:
            st.info("No data for this device in the selected range.")
            return

        # Summary stats
        c1, c2, c3 = st.columns(3)
        c1.metric("Avg Power",  f"{df['power'].mean():.0f} W")
        c2.metric("Peak Power", f"{df['power'].max():.0f} W")
        c3.metric("Readings",   f"{len(df):,}")

        fig = _line_fig(df, "time", "power",
                        title=f"Device {selected} – Power Usage",
                        y_label="Power (W)")
        st.plotly_chart(fig, use_container_width=True)

    else:
        groups = cached_get_groups(st.session_state.username, is_admin())
        grp_ids = [g[0] for g in groups]
        if not grp_ids:
            st.warning("No groups found."); return

        selected = st.selectbox("Select Group", grp_ids)
        df = cached_group_power(
            st.session_state.username, selected, start_iso, end_iso, is_admin()
        )

        if df.empty:
            st.info("No data for this group in the selected range.")
            return

        device_cols = [c for c in df.columns if c != "time"]

        # Thin out columns for combined view if >20 devices
        MAX_TRACES = 20
        view = st.radio(
            "Chart view",
            ["Combined", "Individual grids"],
            horizontal=True,
        )

        if view == "Combined (fast)":
            cols_to_plot = device_cols[:MAX_TRACES]
            if len(device_cols) > MAX_TRACES:
                st.caption(f"Showing first {MAX_TRACES} of {len(device_cols)} devices for clarity.")
            fig = _multi_line_fig(df, "time", cols_to_plot,
                                  title=f"Group {selected} – All Devices")
            st.plotly_chart(fig, use_container_width=True)
        else:
            grid_cols = 2
            rows = [device_cols[i:i+grid_cols] for i in range(0, len(device_cols), grid_cols)]
            for row in rows:
                cols = st.columns(grid_cols)
                for idx, dev in enumerate(row):
                    sub = df[["time", dev]].dropna(subset=[dev])
                    if sub.empty:
                        cols[idx].warning(f"Device {dev}: no data")
                        continue
                    fig = _line_fig(sub, "time", dev, title=f"Device {dev}")
                    cols[idx].plotly_chart(fig, use_container_width=True)


# ─── RBAC PAGE (admin only) ───────────────────────────────────────────────────
def rbac_page():
    st.header("User Management (Admin)")

    users = cached_all_users()

    # ── Current users table ──────────────────────────────────
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

    # ── Create new user ──────────────────────────────────────
    st.subheader("Create New User")
    with st.container():
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


# ─── MAIN DASHBOARD ───────────────────────────────────────────────────────────
def dashboard():
    st.sidebar.title("eIoT Dashboard")
    st.sidebar.caption(
        f"**{st.session_state.username}**  |  role: `{st.session_state.role}`"
    )

    pages = ["Devices", "Groups", "Analytics"]
    if is_admin():
        pages.append("User Management")

    page = st.sidebar.radio("Navigation", pages)

    if st.sidebar.button("Logout"):
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