# Fixtures for pit-clock-randomness.yml (semgrep --test pairs by filename).
import datetime
import random
from datetime import date

import numpy as np


def scoring_clock_bad():
    # ruleid: pit-no-live-clock-in-scoring
    a = datetime.datetime.now()
    # ruleid: pit-no-live-clock-in-scoring
    b = date.today()
    # ruleid: pit-no-live-clock-in-scoring
    c = datetime.datetime.utcnow()
    return a, b, c


def scoring_clock_ok(as_of_date):
    # ok: pit-no-live-clock-in-scoring
    ref = as_of_date
    return ref


def scoring_random_bad():
    # ruleid: pit-no-unseeded-random-in-scoring
    x = random.random()
    # ruleid: pit-no-unseeded-random-in-scoring
    y = np.random.normal()
    # ruleid: pit-no-unseeded-random-in-scoring
    z = np.random.randint(0, 10)
    return x, y, z


def scoring_random_ok():
    # seeded generator must NOT match
    # ok: pit-no-unseeded-random-in-scoring
    rng = np.random.default_rng(seed=42)
    return rng.normal()
