"""Pipeline that fetches Kosovo regional/business data and writes pipeline/data.json.

Stub — real implementation (ASKdata PXWeb queries + World Bank API) lands in
a follow-up commit. Output shape must match docs/DATA_CONTRACT.md exactly, so
that pipeline/data.json can swap in for pipeline/sample_data.json with zero
changes elsewhere in the project.
"""

import json
from pathlib import Path

OUTPUT_PATH = Path(__file__).parent / "data.json"


def main() -> None:
    raise NotImplementedError("fetch.py pipeline not implemented yet")


if __name__ == "__main__":
    main()
