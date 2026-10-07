"""resolve_entity: names, nicknames and misspellings -> Oddsmith ids, via trigram search."""

import unicodedata
from typing import Any

from orchestrator.tools.context import ToolContext
from orchestrator.tools.envelope import SOURCE_API_FOOTBALL, ToolError, success

MIN_SCORE = 0.3
AMBIGUITY_MARGIN = 0.1
MAX_MATCHES = 5

# Letters NFKD does not decompose into base letter + accent.
_EXTRA_FOLDS = str.maketrans(
    {"ø": "o", "æ": "ae", "œ": "oe", "đ": "d", "ł": "l", "ı": "i", "þ": "th", "ð": "d"}
)

# Best alias per entity: full-string trigram similarity, or the query as a whole word inside
# the alias ("saka" in "bukayo saka").
_SQL = """
WITH scored AS (
    SELECT entity_type, entity_id,
           max(greatest(similarity(alias_search, $1), word_similarity($1, alias_search)))
               AS score
    FROM entity_aliases
    WHERE $2::text = 'any' OR entity_type = $2
    GROUP BY entity_type, entity_id
)
SELECT s.entity_type, s.score,
       coalesce(p.id, t.id)                 AS id,
       coalesce(p.name, t.name)             AS name,
       p.team_id, pt.name                   AS team_name,
       p.position,
       coalesce(p.fetched_at, t.fetched_at) AS fetched_at
FROM scored s
LEFT JOIN players p ON s.entity_type = 'player' AND p.id = s.entity_id
LEFT JOIN teams pt  ON pt.id = p.team_id
LEFT JOIN teams t   ON s.entity_type = 'team' AND t.id = s.entity_id
WHERE s.score >= $3
  AND coalesce(p.id, t.id) IS NOT NULL
  AND ($4::bigint IS NULL OR s.entity_type = 'team' OR p.team_id = $4)
ORDER BY s.score DESC, name
LIMIT $5
"""


def normalise(text: str) -> str:
    """Lowercase, strip accents and collapse spaces, matching entity_aliases.alias_search."""
    folded = unicodedata.normalize("NFKD", text.casefold().translate(_EXTRA_FOLDS))
    stripped = "".join(c for c in folded if not unicodedata.combining(c))
    return " ".join(stripped.split())


def _match(row: Any) -> dict[str, Any]:
    player_fields = (
        {"team_id": row["team_id"], "team_name": row["team_name"], "position": row["position"]}
        if row["entity_type"] == "player"
        else {}
    )
    return {
        "entity_type": row["entity_type"],
        "id": row["id"],
        "name": row["name"],
        "score": round(min(float(row["score"]), 1.0), 3),
        **player_fields,
    }


async def run(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    query = args["query"]
    entity_type = args["entity_type"]
    rows = await ctx.conn.fetch(
        _SQL, normalise(query), entity_type, MIN_SCORE, args.get("team_id"), MAX_MATCHES
    )
    if not rows:
        label = "player or team" if entity_type == "any" else entity_type
        raise ToolError("not_found", f"No {label} matched '{query}'. Ask the user to check it.")

    matches = [_match(row) for row in rows]
    is_ambiguous = len(matches) > 1 and (
        matches[0]["score"] - matches[1]["score"] < AMBIGUITY_MARGIN
    )
    return success(
        source=SOURCE_API_FOOTBALL,
        fetched_at=[row["fetched_at"] for row in rows],
        limit_hours=None,
        now=ctx.now,
        data={"matches": matches, "is_ambiguous": is_ambiguous},
    )
