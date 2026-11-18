import streamlit as st

from src.job_search.profiles import create_job_search, get_job_searches
from src.job_search.sidebar import render_search_selector

render_search_selector()

st.title("Job Searches")
st.caption("Create and manage your job searches")

st.subheader("Create a new search")

with st.form("create_search_form"):
    name = st.text_input("Search name")
    description = st.text_area("Description")
    submitted = st.form_submit_button("Create search")

    if submitted:
        if not name.strip():
            st.error("Please enter a search name.")
        else:
            try:
                search_id = create_job_search(name, description or None)
                st.success(f"Search created successfully. ID: {search_id}")
                st.rerun()
            except Exception as error:
                st.error(f"Could not create search: {error}")

st.divider()
st.subheader("Existing searches")

try:
    searches = get_job_searches()
    if searches:
        st.dataframe(searches, use_container_width=True, hide_index=True)
    else:
        st.info("No job searches created yet.")
except Exception as error:
    st.error(f"Could not load searches: {error}")
