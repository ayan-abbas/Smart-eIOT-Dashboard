import streamlit as st
import pandas as pd
import plotly.express as px
from streamlit_autorefresh import st_autorefresh

import utils

st.set_page_config(layout="wide")


# Pre-warm the DB connection pool once (not on every rerun)
@st.cache_resource
def _warm_pool():
    conn = utils.get_connection()
    conn.close()  # return connection back to pool
    return True

_warm_pool()


# ---------------- CACHED DATA HELPERS ---------------- #

@st.cache_data(ttl=30)
def cached_get_devices(username):
    return utils.get_devices(username)


@st.cache_data(ttl=30)
def cached_get_latest_power_usage():
    return utils.get_latest_power_usage()


@st.cache_data(ttl=60)
def cached_get_device_power_usage(deviceid):
    return utils.get_device_power_usage(deviceid)


@st.cache_data(ttl=30)
def cached_get_groups(username):
    return utils.get_groups(username)


@st.cache_data(ttl=60)
def cached_get_group_power_usage(username, groupid):
    return utils.get_group_power_usage(username, groupid)

# ---------------- SESSION ---------------- #

if "logged_in" not in st.session_state:
    st.session_state.logged_in = False

if "username" not in st.session_state:
    st.session_state.username = None

if "selected_device" not in st.session_state:
    st.session_state.selected_device = None

if "auto_refresh" not in st.session_state:
    st.session_state.auto_refresh = False


# ---------------- LOGIN PAGE ---------------- #

def login_page():

    st.title("Enterprise IoT Dashboard")

    col1, col2 = st.columns(2)

    with col1:

        st.subheader("Login")

        username = st.text_input("Username")
        password = st.text_input("Password", type="password")

        if st.button("Login"):

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

        if st.button("Create User"):
            if utils.create_user(new_user, new_pass):
                st.success("User created")
            else:
                st.error("User exists")


# ---------------- DEVICE GRID ---------------- #

def device_page():

    st.header("Devices")

    # Fix large spacing between rows
    st.markdown("""
    <style>
    div[data-testid="stVerticalBlock"]{
        gap:0.35rem;
    }
    </style>
    """, unsafe_allow_html=True)

    col1, col2, col3 = st.columns([1,1,2])

    with col1:
        if st.button("Refresh Device States"):
            cached_get_devices.clear()
            cached_get_latest_power_usage.clear()
            st.rerun()

    with col2:
        if st.button("Refresh Power Usage"):
            cached_get_latest_power_usage.clear()
            cached_get_device_power_usage.clear()
            st.rerun()

    with col3:
        st.session_state.auto_refresh = st.toggle(
            "Auto Refresh (5 sec)",
            value=st.session_state.auto_refresh
        )

    if st.session_state.auto_refresh:
        st_autorefresh(interval=5000, key="refresh")

    devices = cached_get_devices(st.session_state.username)
    latest_power = cached_get_latest_power_usage()

    devices = sorted(devices, key=lambda x: x[0])

    # Show device detail panel ABOVE the grid so it's immediately visible
    device_modal(devices)

    # --- Build all device button CSS in a single block ---
    css_parts = []
    for device in devices:
        deviceid, groupid, state = device
        state = bool(state)
        color = "#2ecc71" if state else "#e74c3c"
        css_parts.append(f"""
        .st-key-device_{deviceid} button {{
            height:70px;
            width:100%;
            border-radius:12px;
            background:{color};
            color:white;
            font-weight:600;
            border:1px solid rgba(255,255,255,0.15);
            display:flex;
            flex-direction:column;
            justify-content:center;
            align-items:center;
        }}
        .st-key-device_{deviceid} button:hover {{
            transform:scale(1.05);
            box-shadow:0 0 10px rgba(255,255,255,0.35);
        }}""")

    if css_parts:
        st.markdown(f"<style>{''.join(css_parts)}</style>", unsafe_allow_html=True)

    grid_cols = 10
    rows = [devices[i:i+grid_cols] for i in range(0, len(devices), grid_cols)]

    for row in rows:

        cols = st.columns(grid_cols)

        for i, device in enumerate(row):

            deviceid, groupid, state = device
            state = bool(state)

            power = latest_power.get(str(deviceid), None)
            power_text = f"{power} W" if power else "-"

            tooltip = f"Device {deviceid} | Group {groupid} | {'ON' if state else 'OFF'} | {power_text}"

            clicked = cols[i].button(
                f"{deviceid}\n{power_text}",
                key=f"device_{deviceid}",
                help=tooltip
            )

            if clicked:
                st.session_state.selected_device = deviceid
                st.rerun()


# ---------------- DEVICE MODAL ---------------- #

def device_modal(devices):

    if "selected_device" not in st.session_state:
        return

    deviceid = st.session_state.selected_device

    current_device = None
    for d in devices:
        if d[0] == deviceid:
            current_device = d
            break

    if current_device is None:
        return

    deviceid, groupid, state = current_device
    state = bool(state)

    st.divider()
    st.subheader(f"Device {deviceid}")

    df = cached_get_device_power_usage(deviceid)

    if not df.empty:
        fig = px.line(df, x="time", y="power")
        st.plotly_chart(fig, width="stretch")

    st.write(f"Group: {groupid}")

    # --- Toggle device state ---
    new_state = st.toggle(
        "Device ON",
        value=state,
        key=f"device_toggle_{deviceid}"
    )

    if new_state != state:

        utils.update_device_state(
            st.session_state.username,
            deviceid,
            int(new_state)   # convert True/False → 1/0
        )

        cached_get_devices.clear()
        st.success("Device state updated")
        st.rerun()

    col1, col2 = st.columns(2)

    with col1:
        if st.button("Delete Device"):

            utils.delete_device(
                st.session_state.username,
                deviceid
            )

            cached_get_devices.clear()
            st.session_state.selected_device = None
            st.rerun()

    with col2:
        if st.button("Close"):

            st.session_state.selected_device = None
            st.rerun()


# ---------------- GROUP PAGE ---------------- #

def group_page():

    st.header("Groups")

    st.markdown("""
    <style>
    div[data-testid="stVerticalBlock"]{
        gap:0.35rem;
    }
    </style>
    """, unsafe_allow_html=True)

    if st.button("Refresh Group States"):
        cached_get_groups.clear()
        st.rerun()

    groups = cached_get_groups(st.session_state.username)
    groups = sorted(groups, key=lambda x: x[0])

    # --- Build all group button CSS in a single block ---
    css_parts = []
    for group in groups:
        groupid, state = group
        state = bool(state)
        color = "#2ecc71" if state else "#e74c3c"
        css_parts.append(f"""
        .st-key-group_{groupid} button {{
            height:80px;
            width:100%;
            border-radius:12px;
            background:{color};
            color:white;
            font-size:18px;
            font-weight:600;
            border:1px solid rgba(255,255,255,0.15);
        }}
        .st-key-group_{groupid} button:hover {{
            transform:scale(1.05);
            box-shadow:0 0 10px rgba(255,255,255,0.35);
        }}""")

    if css_parts:
        st.markdown(f"<style>{''.join(css_parts)}</style>", unsafe_allow_html=True)

    grid_cols = 5
    rows = [groups[i:i+grid_cols] for i in range(0, len(groups), grid_cols)]

    for row in rows:

        cols = st.columns(grid_cols)

        for i, group in enumerate(row):

            groupid, state = group
            state = bool(state)

            tooltip = f"Group {groupid} | {'ON' if state else 'OFF'} | Click to toggle"

            clicked = cols[i].button(
                f"Group {groupid}",
                key=f"group_{groupid}",
                help=tooltip
            )

            if clicked:
                utils.update_group_state(
                    st.session_state.username,
                    groupid,
                    not state
                )
                cached_get_groups.clear()
                cached_get_devices.clear()
                st.rerun()


# ---------------- ANALYTICS PAGE ---------------- #

def analytics_page():

    st.header("Analytics")

    mode = st.radio("View Analytics For", ["Device", "Group"])

    if mode == "Device":

        devices = cached_get_devices(st.session_state.username)

        device_ids = [d[0] for d in devices]

        selected = st.selectbox("Select Device", device_ids)

        df = cached_get_device_power_usage(selected)

        fig = px.line(df, x="time", y="power")

        st.plotly_chart(fig, width="stretch")

    else:

        groups = cached_get_groups(st.session_state.username)

        group_ids = [g[0] for g in groups]

        selected = st.selectbox("Select Group", group_ids)

        df = cached_get_group_power_usage(
            st.session_state.username,
            selected
        )

        if df.empty:
            st.warning("No data")
            return

        devices = list(df.columns)
        devices.remove("time")

        grid_cols = 2
        rows = [devices[i:i+grid_cols] for i in range(0, len(devices), grid_cols)]

        for row in rows:

            cols = st.columns(grid_cols)

            for i, device in enumerate(row):

                fig = px.line(
                    df,
                    x="time",
                    y=device,
                    title=f"Device {device}"
                )

                fig.update_layout(
                    xaxis_title="Time",
                    yaxis_title="Power (W)"
                )

                cols[i].plotly_chart(fig, width="stretch")                


# ---------------- MAIN DASHBOARD ---------------- #

def dashboard():

    st.sidebar.title("Navigation")

    page = st.sidebar.radio(
        "Menu",
        ["Devices", "Groups", "Analytics"]
    )

    st.sidebar.write(f"Logged in as {st.session_state.username}")

    if st.sidebar.button("Logout"):
        st.session_state.logged_in = False
        st.rerun()

    if page == "Devices":
        device_page()

    if page == "Groups":
        group_page()

    if page == "Analytics":
        analytics_page()


# ---------------- APP ENTRY ---------------- #

if not st.session_state.logged_in:
    login_page()
else:
    dashboard()