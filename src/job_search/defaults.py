"""Default profile values used when initializing a new search profile."""

DEFAULT_CANDIDATE_PROFILE = {
    "experience": {
        "professional_summary": "",
        "years_of_experience": None,
    },
    "technical_skills": {
        "Programming Languages": ["Python"],
        "Machine Learning": ["PyTorch"],
        "AI and LLMs": ["Generative AI"],
        "Data Science and Analytics": ["pandas"],
        "Cloud Platforms": ["Amazon Web Services (AWS)"],
        "Databases": ["MongoDB"],
        "Tools and Frameworks": ["Docker"],
    },
    "target_roles": [
        "Data Scientist",
    ],
}

DEFAULT_DISCOVERY_CONFIG = {
    "source": "freehire",
    "common_params": {
        "seniority": "junior,middle",
        "seniority_include_unspecified": "true",
        "countries": "DE",
        "open_within_days": 120,
        "limit": 100,
        "sort": "created_at",
        "order": "desc",
        "description_format": "text",
    },
    "category_search": {
        "enabled": True,
        "categories": ["data_science"],
    },
    "title_search": {
        "enabled": True,
        "queries": [
            "Data Scientist",
        ],
    },
}

DEFAULT_FILTERING_CONFIG = {
    "allowed_work_modes": ["remote", "hybrid", "onsite"],
    "allowed_employment_types": ["full_time", "contract"],
    "allowed_metros": [],
    "allowed_cities": [],
    "preferred_locations": [],
    "keep_unspecified_values": True,
    "remote_rules": {
        "ignore_location_for_remote": True,
        "remote_country": "Germany",
        "allow_mandatory_office_visits": False,
    },
}

DEFAULT_EVALUATION_CONFIG = {
    "model": "qwen3.5:9b",
    "context_size": 32768,
    "temperature": 0.1,
    "minimum_score": 50,
    "score_weights": {
        "technical_skills": 0.30,
        "experience": 0.20,
        "role_relevance": 0.50,
    },
}
