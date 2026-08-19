"""Loads the app's dataset: pipeline/data.json if present, else the sample.

This is the entire "swap to real data" mechanism — once fetch.py writes
pipeline/data.json, the app picks it up automatically with no code change.
"""

from __future__ import annotations

import json
from pathlib import Path

import streamlit as st

PIPELINE_DIR = Path(__file__).resolve().parent.parent / "pipeline"
REAL_DATA_PATH = PIPELINE_DIR / "data.json"
SAMPLE_DATA_PATH = PIPELINE_DIR / "sample_data.json"


@st.cache_data
def load_data() -> dict:
    path = REAL_DATA_PATH if REAL_DATA_PATH.exists() else SAMPLE_DATA_PATH
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)
