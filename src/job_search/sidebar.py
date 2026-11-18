import streamlit as st

from .profiles import get_job_searches


def render_search_selector() -> int | None:
    """Render the search selector and navigation links.

    Returns:
        Selected search ID, or None when no search is selected.
    """
    searches = get_job_searches()

    st.sidebar.title("Job Search Assistant")

    if not searches:
        st.session_state.selected_search_id = None
        st.sidebar.info("No job searches created yet.")
        return None

    search_options = {search["id"]: search["name"] for search in searches}

    search_ids = list(search_options.keys())

    if st.session_state.get("selected_search_id") not in search_ids:
        st.session_state.selected_search_id = None

    st.sidebar.divider()

    selected_id = st.sidebar.selectbox(
        "Current job search",
        options=search_ids,
        format_func=lambda search_id: search_options[search_id],
        index=(
            search_ids.index(st.session_state.selected_search_id)
            if st.session_state.selected_search_id is not None
            else None
        ),
        placeholder="Select a job search...",
    )

    st.session_state.selected_search_id = selected_id

    # Only show navigation after a search has been selected
    if selected_id is not None:
        st.sidebar.divider()
        st.sidebar.subheader("Navigation")

        st.sidebar.page_link("app.py", label="All job searches", icon="🏠")

        st.sidebar.page_link("pages/dashboard.py", label="Dashboard", icon="📊")

        st.sidebar.page_link("pages/run_search.py", label="Run Search", icon="🔎")

        st.sidebar.page_link("pages/job_results.py", label="Job Results", icon="💼")

        st.sidebar.page_link(
            "pages/search_configuration.py",
            label="Search Configuration",
            icon="⚙️",
        )

    return selected_id


def require_selected_search() -> int:
    """Require a selected search and return its ID.

    Returns:
        Selected search ID.
    """
    search_id = render_search_selector()

    if search_id is None:
        st.warning("Please select a job search or create a new one before continuing.")
        st.stop()

    return search_id
