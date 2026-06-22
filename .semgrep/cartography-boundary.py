# Fixtures for cartography-boundary.yml (semgrep --test pairs by filename).
# `paths:` constraints are ignored in --test mode, so this file need not live
# under scientific_cartography/.


def write_record_bad(record, score, weight):
    # ruleid: cartography-no-scoring-field-write
    record["final_score"] = score
    # ruleid: cartography-no-scoring-field-write
    record["ranker_v2_score"] = score
    # ruleid: cartography-no-scoring-field-write
    record["position_size"] = weight
    # ruleid: cartography-no-scoring-field-write
    record.target_weight = weight


def write_diagnostic_ok(record):
    # The attestation marker the real exporters emit — must NOT match C1.
    # ok: cartography-no-scoring-field-write
    record["final_score_change"] = False
    # ok: cartography-no-scoring-field-write
    record["disease_count"] = 3
    # ok: cartography-no-scoring-field-write
    record["mechanism"] = "ASO"


def render_text_bad():
    # ruleid: cartography-no-recommendation-language
    note = "strong buy on this asset ahead of catalyst"
    # ruleid: cartography-no-recommendation-language
    rec = "overweight vs peer programs"
    return note, rec


def render_text_ok():
    # ok: cartography-no-recommendation-language
    label = "competitive positioning across mechanisms"
    # ok: cartography-no-recommendation-language
    desc = "count of programs by development stage"
    return label, desc
