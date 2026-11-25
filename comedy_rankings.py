"""Confidence-adjusted audience and popularity ordering (not view counts)."""
import math

def audience_score(rating, votes, popularity):
    votes = max(0, int(votes or 0))
    rating = max(0, min(10, float(rating or 0)))
    popularity = max(0, float(popularity or 0))
    # A small sample shrinks toward 6.0; votes also indicate audience reach.
    if not rating:
        votes = 0
    return (votes * rating + 25 * 6.0) / (votes + 25) + 0.55 * math.log10(votes + 1) + 0.25 * math.log10(popularity + 1)
