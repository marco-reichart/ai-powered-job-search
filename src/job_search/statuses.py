"""Shared application status values and common labels."""

APPLICATION_STATUSES = frozenset(
    {
        "new",
        "not_interested",
        "interested",
        "to_apply",
        "applied",
        "interview",
        "offer",
        "rejected",
        "withdrawn",
        "hired",
    }
)

APPLICATION_STATUS_LABELS = {
    "ai_filtered": "Filtered by AI",
    "new": "Needs review",
    "not_interested": "Not interested",
    "interested": "Interested",
    "to_apply": "To apply",
    "applied": "Applied",
    "interview": "Interview",
    "offer": "Offer received",
    "rejected": "Rejected",
    "withdrawn": "Withdrawn",
    "hired": "Hired",
}

APPLICATION_STARTED_STATUSES = frozenset(
    {
        "applied",
        "interview",
        "offer",
        "rejected",
        "withdrawn",
        "hired",
    }
)
