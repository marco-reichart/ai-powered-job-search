import plotly.graph_objects as go
import streamlit as st

from src.job_search.dashboard_data import get_dashboard_data
from src.job_search.profiles import get_active_search_profile
from src.job_search.sidebar import require_selected_search

st.set_page_config(layout="wide")
search_id = require_selected_search()
st.title("Dashboard")

active_profile = get_active_search_profile(search_id) or {}
evaluation_config = active_profile.get("evaluation_config", {})
try:
    minimum_score = float(evaluation_config.get("minimum_score", 50))
except (TypeError, ValueError):
    minimum_score = 50.0
if not 0 <= minimum_score <= 100:
    minimum_score = 50.0

data = get_dashboard_data(search_id, minimum_score)

st.subheader("Job search overview")
col1, col2, col3 = st.columns(3)
col1.metric("Jobs discovered", data["total_jobs"])
col2.metric("Filtered by initial filters", data["initially_filtered"])
col3.metric("Passed initial filters", data["passed_initial_filters"])
col4, col5, col6 = st.columns(3)
col4.metric("Jobs evaluated", data["total_evaluations"])
col5.metric("Awaiting evaluation", data["awaiting_evaluation"])
col6.metric("Applications started", data["total_applications"])

st.divider()
st.subheader("Job and application progression")
edges = data["flow_edges"]
if edges:
    labels = data["labels"]
    node_index = {label: index for index, label in enumerate(labels)}
    figure = go.Figure(
        data=[
            go.Sankey(
                arrangement="perpendicular",
                node={"label": labels, "pad": 24, "thickness": 18},
                link={
                    "source": [node_index[edge["source"]] for edge in edges],
                    "target": [node_index[edge["target"]] for edge in edges],
                    "value": [edge["value"] for edge in edges],
                    "color": "rgba(100, 116, 139, 0.22)",
                },
            )
        ]
    )
    figure.update_layout(height=850, margin={"l": 24, "r": 24, "t": 24, "b": 24})
    st.plotly_chart(figure, use_container_width=True)
else:
    st.info("No job progression data available yet.")

st.divider()
st.subheader("Recent search runs")
if data["recent_runs"]:
    st.dataframe(data["recent_runs"], use_container_width=True, hide_index=True)
else:
    st.info("No search runs yet.")
