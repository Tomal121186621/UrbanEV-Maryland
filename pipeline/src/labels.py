"""Codebook value labels (RTS_Public_File_data_dictionary.xlsx) for publication-quality
axis labelling. Keys are the raw string codes; values are short human-readable labels.
`code_labels(field, codes)` maps a list of codes to labels for a given field.
"""
from __future__ import annotations
from src.encoders import AGE_EDGES

# short axis labels (kept compact so ticks stay readable)
D_ACTIVITY = {"1": "Home", "2": "Work", "3": "Volunteer", "4": "School", "5": "Shopping",
              "6": "Quick meal", "7": "Meal", "8": "Gas", "9": "Health", "10": "Errand",
              "11": "Socialize", "12": "Civic/Relig.", "13": "Exercise", "14": "Recreation",
              "15": "Entertain.", "16": "Drop/pickup", "17": "Misc.", "18": "Other"}
TRAVEL_MODE = {"1": "Walk", "2": "Bike", "3": "Motorcycle", "4": "Auto (drv)", "5": "Auto (pax)",
               "6": "School bus", "7": "Rail", "8": "Bus", "9": "Private bus", "10": "Paratransit",
               "11": "Taxi", "12": "Uber/Lyft", "13": "Air", "14": "Water", "15": "Other"}
HH_INCOME = {"1": "<$15k", "2": "$15–25k", "3": "$25–35k", "4": "$35–50k", "5": "$50–75k",
             "6": "$75–100k", "7": "$100–150k", "8": "$150k+"}
HOME_TYPE = {"1": "SF detached", "2": "SF attached", "3": "Apt/Condo",
             "4": "Mobile home", "5": "Dorm/inst."}
HOME_OWNERSHIP = {"1": "Own", "2": "Rent", "3": "Other"}
LICENSE = {"1": "Licensed", "2": "No licence"}
GENDER = {"1": "Female", "2": "Male"}
EMPLOYMENT = {"0": "Worker", "1": "Retired", "2": "Volunteer", "3": "Homemaker",
              "4": "Unemp. (seeking)", "5": "Unemp. (not)", "6": "Student", "7": "Disabled",
              "8": "Under-16"}
YESNO = {"0": "No", "1": "Yes"}

# Maryland county FIPS -> name
COUNTY = {"24001": "Allegany", "24003": "Anne Arundel", "24005": "Baltimore Co.",
          "24009": "Calvert", "24011": "Caroline", "24013": "Carroll", "24015": "Cecil",
          "24017": "Charles", "24019": "Dorchester", "24021": "Frederick", "24023": "Garrett",
          "24025": "Harford", "24027": "Howard", "24029": "Kent", "24031": "Montgomery",
          "24033": "Prince George's", "24035": "Queen Anne's", "24037": "St. Mary's",
          "24039": "Somerset", "24041": "Talbot", "24043": "Washington", "24045": "Wicomico",
          "24047": "Worcester", "24510": "Baltimore City"}

AGE_BAND = {str(i): (f"{int(AGE_EDGES[i])}–{int(AGE_EDGES[i+1])}" if AGE_EDGES[i + 1] <= 100
                     else f"{int(AGE_EDGES[i])}+") for i in range(len(AGE_EDGES) - 1)}

# field name -> code->label dict (fields not listed keep raw codes, e.g. count variables)
FIELD = {
    "d_activity": D_ACTIVITY, "destination_activity": D_ACTIVITY, "travel_mode": TRAVEL_MODE,
    "hh_income_detailed": HH_INCOME, "home_type": HOME_TYPE, "home_ownership": HOME_OWNERSHIP,
    "license": LICENSE, "gender": GENDER, "employment_status": EMPLOYMENT,
    "home_office": YESNO, "charge_at_work": YESNO, "home_county": COUNTY, "age_band": AGE_BAND,
}


def _norm(c):
    s = str(c)
    try:
        f = float(s); return str(int(f)) if f == int(f) else s
    except (ValueError, TypeError):
        return s


def code_labels(field, codes):
    """Map an iterable of raw codes to short labels for `field` (identity if unmapped)."""
    m = FIELD.get(field, {})
    return [m.get(_norm(c), str(c)) for c in codes]
