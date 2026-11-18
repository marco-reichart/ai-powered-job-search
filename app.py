
import streamlit as st

from src.job_search.database import initialize_database
from src.job_search.profiles import get_job_searches

st.set_page_config(
    page_title="AI Job Search Assistant",
    page_icon="🔎",
    layout="wide"
)

initialize_database()

st.title("AI Job Search Assistant")
st.caption("Your personal job search workspace")

searches = get_job_searches()

st.subheader("Your job searches")

if not searches:
    st.info(
        "You haven't created a job search yet. "
        "Create your first search to get started."
    )

    st.page_link(
        "pages/job_searches.py",
        label="Create your first job search",
        icon="➕"
    )

else:
    for search in searches:
        with st.container(border=True):
            col1, col2 = st.columns([4, 1])

            with col1:
                st.subheader(search["name"])

                if search.get("description"):
                    st.write(search["description"])

            with col2:
                if st.button(
                    "Open search",
                    key=f"open_search_{search['id']}",
                    use_container_width=True
                ):
                    st.session_state.selected_search_id = search["id"]
                    st.switch_page("pages/dashboard.py")

st.divider()

if st.button("Create new job search", icon="➕"):
    st.switch_page("pages/job_searches.py")
