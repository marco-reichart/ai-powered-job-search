import copy
from typing import Any

import streamlit as st

from src.job_search.defaults import (
    DEFAULT_CANDIDATE_PROFILE,
    DEFAULT_DISCOVERY_CONFIG,
    DEFAULT_EVALUATION_CONFIG,
    DEFAULT_FILTERING_CONFIG,
)
from src.job_search.profiles import (
    get_active_search_profile,
    save_search_profile,
)
from src.job_search.sidebar import require_selected_search

st.set_page_config(
    page_title="Search Configuration",
    page_icon="⚙️",
    layout="wide",
)

search_id = require_selected_search()


# ==================================================
# HELPER FUNCTIONS
# ==================================================


def list_to_text(values: list[Any] | None) -> str:
    """Convert values to newline-separated text.

    Args:
        values (list[Any] | None): Values to display.

    Returns:
        Newline-separated text.
    """
    if not values:
        return ""

    return "\n".join(str(value) for value in values)


def text_to_list(value: str) -> list[str]:
    """Split non-empty lines into values.

    Args:
        value (str): Newline-separated text.

    Returns:
        Stripped non-empty lines.
    """
    return [item.strip() for item in value.splitlines() if item.strip()]


def convert_skills_to_categories(technical_skills: dict[str, Any]) -> list[dict[str, Any]]:
    """Convert stored skills to editable categories.

    Args:
        technical_skills (dict[str, Any]): Skills grouped by category.

    Returns:
        Editable category records.
    """

    categories = []

    if not isinstance(technical_skills, dict):
        return categories

    for index, (category_name, skills) in enumerate(technical_skills.items()):
        # Convert old keys such as programming_languages
        # into readable category names.
        display_name = category_name.replace("_", " ").strip()
        display_name = display_name.title()

        if not isinstance(skills, list):
            skills = []

        categories.append(
            {
                "id": index,
                "name": display_name,
                "skills": [
                    {
                        "id": skill_index,
                        "value": str(skill),
                    }
                    for skill_index, skill in enumerate(skills)
                ],
            }
        )

    return categories


def initialize_configuration_state(search_id: int) -> None:
    """Load a search profile into Streamlit state.

    Args:
        search_id (int): Search ID.
    """

    profile = get_active_search_profile(search_id)

    if profile is None:
        candidate = copy.deepcopy(DEFAULT_CANDIDATE_PROFILE)
        discovery = copy.deepcopy(DEFAULT_DISCOVERY_CONFIG)
        filtering = copy.deepcopy(DEFAULT_FILTERING_CONFIG)
        evaluation = copy.deepcopy(DEFAULT_EVALUATION_CONFIG)
        profile_version = None

    else:
        candidate = profile["candidate_profile"]
        discovery = profile["discovery_config"]
        filtering = profile["filtering_config"]
        evaluation = profile["evaluation_config"]
        profile_version = profile["version"]

    prefix = f"config_{search_id}_"

    st.session_state[prefix + "profile_version"] = profile_version

    st.session_state[prefix + "candidate"] = candidate
    st.session_state[prefix + "discovery"] = discovery
    st.session_state[prefix + "filtering"] = filtering
    st.session_state[prefix + "evaluation"] = evaluation

    # Convert the technical skills dictionary into
    # editable category objects.
    categories = convert_skills_to_categories(candidate.get("technical_skills", {}))

    st.session_state[prefix + "skill_categories"] = categories

    # Generate unique IDs for new categories and skills.
    next_category_id = (
        max(
            [category["id"] for category in categories],
            default=-1,
        )
        + 1
    )

    next_skill_id = (
        max(
            [skill["id"] for category in categories for skill in category["skills"]],
            default=-1,
        )
        + 1
    )

    st.session_state[prefix + "next_category_id"] = next_category_id
    st.session_state[prefix + "next_skill_id"] = next_skill_id


def add_skill_category(prefix: str) -> None:
    """Add an empty skill category to session state.

    Args:
        prefix (str): Search configuration state prefix.
    """

    category_id = st.session_state[prefix + "next_category_id"]

    st.session_state[prefix + "skill_categories"].append(
        {
            "id": category_id,
            "name": "",
            "skills": [],
        }
    )

    st.session_state[prefix + "next_category_id"] += 1


def remove_skill_category(prefix: str, category_id: int) -> None:
    """Remove a skill category from session state.

    Args:
        prefix (str): Search configuration state prefix.
        category_id (int): Category ID to remove.
    """

    st.session_state[prefix + "skill_categories"] = [
        category for category in st.session_state[prefix + "skill_categories"] if category["id"] != category_id
    ]


def add_skill(prefix: str, category_id: int) -> None:
    """Add an empty skill to a category.

    Args:
        prefix (str): Search configuration state prefix.
        category_id (int): Category ID to update.
    """

    skill_id = st.session_state[prefix + "next_skill_id"]

    for category in st.session_state[prefix + "skill_categories"]:
        if category["id"] == category_id:
            category["skills"].append(
                {
                    "id": skill_id,
                    "value": "",
                }
            )
            break

    st.session_state[prefix + "next_skill_id"] += 1


def remove_skill(prefix: str, category_id: int, skill_id: int) -> None:
    """Remove a skill from a category.

    Args:
        prefix (str): Search configuration state prefix.
        category_id (int): Category ID to update.
        skill_id (int): Skill ID to remove.
    """

    for category in st.session_state[prefix + "skill_categories"]:
        if category["id"] == category_id:
            category["skills"] = [skill for skill in category["skills"] if skill["id"] != skill_id]
            break


def collect_technical_skills(prefix: str) -> dict[str, list[str]]:
    """Collect skill categories from current widget values.

    Args:
        prefix (str): Search configuration state prefix.

    Returns:
        Skills grouped by category name.
    """

    technical_skills = {}

    for category in st.session_state[prefix + "skill_categories"]:
        category_id = category["id"]

        category_name = st.session_state.get(
            f"{prefix}category_name_{category_id}",
            category["name"],
        ).strip()

        if not category_name:
            continue

        skills = []

        for skill in category["skills"]:
            skill_id = skill["id"]

            skill_value = st.session_state.get(
                f"{prefix}skill_{category_id}_{skill_id}",
                skill["value"],
            ).strip()

            if skill_value:
                skills.append(skill_value)

        if category_name in technical_skills:
            raise ValueError(f"The category '{category_name}' already exists. Please use unique category names.")

        technical_skills[category_name] = skills

    return technical_skills


# ==================================================
# INITIALIZE STATE FOR CURRENT SEARCH
# ==================================================

prefix = f"config_{search_id}_"

if prefix + "candidate" not in st.session_state:
    initialize_configuration_state(search_id)

candidate = st.session_state[prefix + "candidate"]
discovery = st.session_state[prefix + "discovery"]
filtering = st.session_state[prefix + "filtering"]
evaluation = st.session_state[prefix + "evaluation"]


# ==================================================
# PAGE HEADING
# ==================================================

st.title("Search Configuration")

# ==================================================
# CONFIGURATION TABS
# ==================================================

tab_candidate, tab_discovery, tab_filtering, tab_evaluation = st.tabs(
    [
        "Candidate Profile",
        "Job Discovery",
        "Filtering",
        "Evaluation",
    ]
)


# ==================================================
# CANDIDATE PROFILE
# ==================================================

with tab_candidate:
    st.subheader("Professional Experience")

    experience = candidate.get("experience", {})

    professional_summary = st.text_area(
        "Professional Summary",
        value=experience.get("professional_summary", ""),
        height=180,
        key=prefix + "professional_summary",
    )

    years_of_experience = st.number_input(
        "Years of Experience",
        min_value=0,
        max_value=60,
        value=(int(experience["years_of_experience"]) if experience.get("years_of_experience") is not None else 0),
        help="Use 0 if you prefer not to specify this information.",
        key=prefix + "years_of_experience",
    )

    st.divider()

    # ----------------------------------------------
    # DYNAMIC TECHNICAL SKILLS
    # ----------------------------------------------

    st.subheader("Technical Skills")

    st.caption(
        "Create your own skill categories and organize your skills "
        "however you like. Category names are not predefined. "
        "These will be used to evaluate your fit by using a LLM."
    )

    categories = st.session_state[prefix + "skill_categories"]

    if not categories:
        st.info("You haven't created any skill categories yet. Use the button below to add your first category.")

    for category in categories:
        category_id = category["id"]

        with st.container(border=True):
            col_name, col_delete = st.columns([5, 1])

            with col_name:
                st.text_input(
                    "Category Name",
                    value=category["name"],
                    key=f"{prefix}category_name_{category_id}",
                    placeholder="e.g. Programming Languages",
                    label_visibility="collapsed",
                )

            with col_delete:
                if st.button(
                    "🗑️",
                    key=f"{prefix}delete_category_{category_id}",
                    help="Delete this category and all its skills",
                    use_container_width=True,
                ):
                    remove_skill_category(prefix, category_id)
                    st.rerun()

            st.markdown("**Skills**")

            if not category["skills"]:
                st.caption("No skills added yet.")

            for skill in category["skills"]:
                skill_id = skill["id"]

                col_skill, col_remove = st.columns([5, 1])

                with col_skill:
                    st.text_input(
                        "Skill",
                        value=skill["value"],
                        key=f"{prefix}skill_{category_id}_{skill_id}",
                        placeholder="Enter a skill",
                        label_visibility="collapsed",
                    )

                with col_remove:
                    if st.button(
                        "✖",
                        key=(f"{prefix}remove_skill_{category_id}_{skill_id}"),
                        help="Remove this skill",
                        use_container_width=True,
                    ):
                        remove_skill(
                            prefix,
                            category_id,
                            skill_id,
                        )
                        st.rerun()

            if st.button(
                "＋ Add Skill",
                key=f"{prefix}add_skill_{category_id}",
                use_container_width=False,
            ):
                add_skill(prefix, category_id)
                st.rerun()

    st.divider()

    if st.button(
        "＋ Add Category",
        key=prefix + "add_category",
        type="secondary",
    ):
        add_skill_category(prefix)
        st.rerun()

    # ----------------------------------------------
    # TARGET ROLES
    # ----------------------------------------------

    st.divider()

    st.subheader("Target Roles")

    target_roles = text_to_list(
        st.text_area(
            "Target Job Titles used by the LLM to evaluate fit.",
            value=list_to_text(candidate.get("target_roles", [])),
            height=120,
            key=prefix + "target_roles",
            help="Enter one target role per line.",
        )
    )


# ==================================================
# JOB DISCOVERY
# ==================================================

with tab_discovery:
    st.markdown("### About job discovery settings")

    st.markdown(
        """
        These settings control how job listings are retrieved from the
        **Freehire API**. Their purpose is to narrow down the results and
        remove irrelevant entries before they are evaluated by the AI.

        The available parameters are defined by the Freehire API. Make sure
        to use the correct parameter names and supported values when
        configuring your search.

        **Before changing these settings, check the
        [Freehire API documentation](https://freehire.me/docs/api?utm_source=github&utm_medium=readme&utm_campaign=api#description/introduction)**
        to understand the available filters, accepted values, and how they
        work.

        Incorrect parameter names or unsupported values may lead to
        unexpected search results or no results at all.
        """
    )

    st.divider()

    st.subheader("Job Source")

    st.text_input(
        "Source",
        value=discovery.get("source", "freehire"),
        disabled=True,
        key=prefix + "source_display",
        help="Freehire is currently the configured job source.",
    )

    common_params = discovery.get("common_params", {})

    col1, col2 = st.columns(2)

    with col1:
        seniority = st.text_input(
            "Seniority",
            value=common_params.get("seniority", "junior,middle"),
            key=prefix + "seniority",
            help="Filter jobs based on seniority, e.g. junior or senior.",
        )

        countries = st.text_input(
            "Country Codes",
            value=common_params.get("countries", "DE"),
            key=prefix + "countries",
            help="Filter jobs based on country codes, e.g. DE or US.",
        )

        limit = st.number_input(
            "Jobs per API Request",
            min_value=1,
            max_value=100,
            value=int(common_params.get("limit", 100)),
            key=prefix + "limit",
        )

    with col2:
        st.selectbox(
            "Sort By",
            options=["created_at"],
            index=0,
            key=prefix + "sort",
        )

        order = st.selectbox(
            "Sort Order",
            options=["desc", "asc"],
            index=["desc", "asc"].index(common_params.get("order", "desc")),
            key=prefix + "order",
        )

        seniority_unspecified = st.checkbox(
            "Include unspecified seniority",
            value=(
                str(
                    common_params.get(
                        "seniority_include_unspecified",
                        "true",
                    )
                ).lower()
                == "true"
            ),
            key=prefix + "seniority_unspecified",
            help="Enable if you want to keep jobs where seniority is not specified (recommended).",
        )

    configured_open_days = common_params.get("open_within_days")
    try:
        default_open_days = max(1, int(configured_open_days or 120))
    except (TypeError, ValueError):
        default_open_days = 120

    limit_open_age = st.checkbox(
        "Limit by how recently Freehire first saw the job",
        value=configured_open_days is not None,
        key=prefix + "limit_open_age",
        help=(
            "Uses when Freehire first recorded the listing, which is more reliable than source-reported posting dates."
        ),
    )
    open_within_days = st.number_input(
        "Added to Freehire within the last (days)",
        min_value=1,
        max_value=3650,
        value=default_open_days,
        disabled=not limit_open_age,
        key=prefix + "open_within_days",
    )

    st.divider()

    st.subheader("Category Search")

    category_search = discovery.get("category_search", {})

    category_search_enabled = st.checkbox(
        "Enable category-based discovery",
        value=category_search.get("enabled", True),
        key=prefix + "category_enabled",
    )

    categories_text = st.text_area(
        "Freehire Categories",
        value=list_to_text(category_search.get("categories", [])),
        height=100,
        key=prefix + "categories",
        help="Enter one Freehire category per line.",
    )

    st.divider()

    st.subheader("Job Title Search")

    title_search = discovery.get("title_search", {})

    title_search_enabled = st.checkbox(
        "Enable title-based discovery",
        value=title_search.get("enabled", True),
        key=prefix + "title_enabled",
    )

    title_queries_text = st.text_area(
        "Target Job Titles",
        value=list_to_text(title_search.get("queries", [])),
        height=140,
        key=prefix + "title_queries",
        help="Enter one title per line.",
    )

    st.caption("Freehire title searches match the listing title.")


# ==================================================
# FILTERING
# ==================================================

with tab_filtering:
    st.subheader("Local Eligibility Filters")
    st.caption("These rules run before the LLM evaluation. Listings that fail are not sent to the model.")

    allowed_work_modes = filtering.get("allowed_work_modes", [])

    allowed_employment_types = filtering.get(
        "allowed_employment_types",
        [],
    )

    work_mode_options = ["remote", "hybrid", "onsite"]

    employment_options = [
        "full_time",
        "contract",
        "part_time",
    ]

    selected_work_modes = st.multiselect(
        "Allowed Work Modes",
        options=work_mode_options,
        default=[value for value in allowed_work_modes if value in work_mode_options],
        key=prefix + "allowed_work_modes",
    )

    selected_employment_types = st.multiselect(
        "Allowed Employment Types",
        options=employment_options,
        default=[value for value in allowed_employment_types if value in employment_options],
        key=prefix + "allowed_employment_types",
    )

    allowed_cities_text = st.text_area(
        "Allowed Cities and Regions",
        value=list_to_text(filtering.get("allowed_cities", [])),
        height=140,
        key=prefix + "allowed_cities",
        help="Listings must match one of these values unless their location is unspecified or the remote-location bypass applies.",
    )

    allowed_metros_text = st.text_area(
        "Allowed Metropolitan Areas",
        value=list_to_text(filtering.get("allowed_metros", [])),
        height=100,
        key=prefix + "allowed_metros",
        help="These are combined with Allowed Cities and Regions by the local filter.",
    )

    keep_unspecified_values = st.checkbox(
        "Keep jobs with unspecified values",
        value=filtering.get("keep_unspecified_values", True),
        key=prefix + "keep_unspecified",
        help="Keep a listing when work mode, employment type, or location data is missing.",
    )

    remote_rules = filtering.get("remote_rules", {})

    ignore_location_for_remote = st.checkbox(
        "Ignore office location for remote jobs",
        value=remote_rules.get("ignore_location_for_remote", True),
        key=prefix + "ignore_remote_location",
        help="When enabled, remote listings bypass the local city and metro allow-list.",
    )

    st.divider()
    st.subheader("LLM Location Preferences")
    st.caption(
        "These preferences are included in the model prompt. They guide the LLM's location assessment; they do not filter listings before evaluation."
    )

    preferred_locations_text = st.text_area(
        "Preferred Locations",
        value=list_to_text(filtering.get("preferred_locations", [])),
        height=120,
        key=prefix + "preferred_locations",
        help="Enter one city or location per line. The LLM uses these when judging hybrid and on-site roles.",
    )

    remote_country = st.text_input(
        "Country where you need remote work to be allowed",
        value=remote_rules.get("remote_country", "Germany"),
        key=prefix + "remote_country",
        help="The LLM checks whether the listing allows remote work from this country.",
    )

    allow_mandatory_office_visits = st.checkbox(
        "Allow occasional mandatory office visits for remote jobs",
        value=remote_rules.get(
            "allow_mandatory_office_visits",
            False,
        ),
        key=prefix + "mandatory_visits",
        help="When enabled, the LLM may treat occasional required office visits as acceptable for a remote role.",
    )


# ==================================================
# EVALUATION
# ==================================================

with tab_evaluation:
    st.subheader("Local Ollama Model")

    model = st.text_input(
        "Model Name",
        value=evaluation.get(
            "model",
            evaluation.get("model_name", "qwen3.5:9b"),
        ),
        key=prefix + "model",
        help="Use a model available in your local Ollama installation.",
    )

    col1, col2 = st.columns(2)

    with col1:
        context_size = st.number_input(
            "Context Size",
            min_value=1024,
            max_value=131072,
            value=int(evaluation.get("context_size", 8192)),
            step=1024,
            key=prefix + "context_size",
        )

        temperature = st.number_input(
            "Temperature",
            min_value=0.0,
            max_value=2.0,
            value=float(evaluation.get("temperature", 0.1)),
            step=0.1,
            key=prefix + "temperature",
        )

        minimum_score = st.number_input(
            "Minimum Match Score",
            min_value=0,
            max_value=100,
            value=int(evaluation.get("minimum_score", 50)),
            step=1,
            key=prefix + "minimum_score",
            help=("Jobs with an overall match score below this value will be filtered out after LLM evaluation."),
        )
        st.caption(
            "A job is filtered out if its location does not match "
            "or its overall match score is below this threshold. "
            "Jobs with an unspecified location match are assessed "
            "using their match score."
        )

    st.divider()

    st.subheader("Evaluation Score Weights")

    score_weights = evaluation.get("score_weights", {})

    technical_weight = st.number_input(
        "Technical Skills",
        min_value=0.0,
        max_value=1.0,
        value=float(score_weights.get("technical_skills", 0.40)),
        step=0.05,
        key=prefix + "technical_weight",
    )

    experience_weight = st.number_input(
        "Experience",
        min_value=0.0,
        max_value=1.0,
        value=float(score_weights.get("experience", 0.30)),
        step=0.05,
        key=prefix + "experience_weight",
    )

    role_weight = st.number_input(
        "Role Relevance",
        min_value=0.0,
        max_value=1.0,
        value=float(score_weights.get("role_relevance", 0.30)),
        step=0.05,
        key=prefix + "role_weight",
    )

    total_weight = technical_weight + experience_weight + role_weight

    st.metric(
        "Total Score Weight",
        f"{total_weight:.2f}",
    )

    if abs(total_weight - 1.0) > 0.001:
        st.warning("The weights should add up to 1.00. Please adjust them before saving.")


# ==================================================
# SAVE CONFIGURATION
# ==================================================

st.divider()

if st.button(
    "Save Configuration",
    type="primary",
    use_container_width=True,
):
    # ----------------------------------------------
    # VALIDATION
    # ----------------------------------------------

    if not model.strip():
        st.error("Please enter a model name.")
        st.stop()

    if not target_roles:
        st.error("Please enter at least one target role.")
        st.stop()

    if not remote_country.strip():
        st.error("Please enter the country where remote work must be allowed.")
        st.stop()

    if not selected_work_modes:
        st.error("Please select at least one allowed work mode.")
        st.stop()

    if not selected_employment_types:
        st.error("Please select at least one employment type.")
        st.stop()

    if abs(total_weight - 1.0) > 0.001:
        st.error("The evaluation weights must add up to 1.00.")
        st.stop()

    # ----------------------------------------------
    # COLLECT DYNAMIC SKILLS
    # ----------------------------------------------

    try:
        updated_technical_skills = collect_technical_skills(prefix)

    except ValueError as error:
        st.error(str(error))
        st.stop()

    # ----------------------------------------------
    # UPDATE CANDIDATE PROFILE
    # ----------------------------------------------

    updated_candidate = {
        **candidate,
        "experience": {
            **candidate.get("experience", {}),
            "professional_summary": professional_summary,
            "years_of_experience": (years_of_experience if years_of_experience > 0 else None),
        },
        "technical_skills": updated_technical_skills,
        "target_roles": target_roles,
    }

    # ----------------------------------------------
    # UPDATE DISCOVERY CONFIGURATION
    # ----------------------------------------------

    updated_common_params = {
        **{key: value for key, value in common_params.items() if key != "posted_within_days"},
        "seniority": seniority,
        "seniority_include_unspecified": str(seniority_unspecified).lower(),
        "countries": countries,
        "limit": int(limit),
        "sort": "created_at",
        "order": order,
        "description_format": common_params.get("description_format", "text"),
    }
    if limit_open_age:
        updated_common_params["open_within_days"] = int(open_within_days)
    else:
        updated_common_params.pop("open_within_days", None)

    updated_discovery = {
        **discovery,
        "source": "freehire",
        "common_params": updated_common_params,
        "category_search": {
            **category_search,
            "enabled": category_search_enabled,
            "categories": text_to_list(categories_text),
        },
        "title_search": {
            **{key: value for key, value in title_search.items() if key != "query_fields"},
            "enabled": title_search_enabled,
            "queries": text_to_list(title_queries_text),
        },
    }

    # ----------------------------------------------
    # UPDATE FILTERING CONFIGURATION
    # ----------------------------------------------

    updated_filtering = {
        **filtering,
        "allowed_work_modes": selected_work_modes,
        "allowed_employment_types": selected_employment_types,
        "allowed_metros": text_to_list(allowed_metros_text),
        "allowed_cities": text_to_list(allowed_cities_text),
        "preferred_locations": text_to_list(preferred_locations_text),
        "keep_unspecified_values": keep_unspecified_values,
        "remote_rules": {
            **remote_rules,
            "ignore_location_for_remote": ignore_location_for_remote,
            "remote_country": remote_country,
            "allow_mandatory_office_visits": (allow_mandatory_office_visits),
        },
    }

    # ----------------------------------------------
    # UPDATE EVALUATION CONFIGURATION
    # ----------------------------------------------

    updated_evaluation = {
        **evaluation,
        "model": model.strip(),
        "context_size": int(context_size),
        "temperature": float(temperature),
        "minimum_score": int(minimum_score),
        "score_weights": {
            "technical_skills": float(technical_weight),
            "experience": float(experience_weight),
            "role_relevance": float(role_weight),
        },
    }

    # Remove the old key if it exists.
    updated_evaluation.pop("model_name", None)

    # ----------------------------------------------
    # SAVE NEW PROFILE VERSION
    # ----------------------------------------------

    try:
        new_profile_id = save_search_profile(
            search_id=search_id,
            candidate_profile=updated_candidate,
            discovery_config=updated_discovery,
            filtering_config=updated_filtering,
            evaluation_config=updated_evaluation,
        )

        saved_profile = get_active_search_profile(search_id)

        # Update session state with the saved profile.
        st.session_state[prefix + "candidate"] = saved_profile["candidate_profile"]

        st.session_state[prefix + "discovery"] = saved_profile["discovery_config"]

        st.session_state[prefix + "filtering"] = saved_profile["filtering_config"]

        st.session_state[prefix + "evaluation"] = saved_profile["evaluation_config"]

        st.session_state[prefix + "profile_version"] = saved_profile["version"]

        st.success(
            "Configuration saved successfully. "
            f"New profile version: {saved_profile['version']} "
            f"(Profile ID: {new_profile_id})"
        )

    except Exception as error:
        st.error(f"Could not save configuration: {error}")
